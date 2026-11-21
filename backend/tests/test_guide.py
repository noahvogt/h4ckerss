import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from app import guide_usage
from app.main import app
from app.measures import gpu
from app.pipeline.ai_saas import calculate_unused_ai_seats
from app.pipeline.common import DATA_DIR
from app.routers.baseline import baseline

client = TestClient(app)


@pytest.fixture(autouse=True)
def demo_settings(monkeypatch, tmp_path):
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_MAX_OUTPUT_TOKENS", "OPENAI_PRICES_USD_PER_1M"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("WATTSON_GUIDE_GRID_LOCATION", raising=False)
    path = tmp_path / "guide" / "usage.jsonl"
    monkeypatch.setenv("WATTSON_GUIDE_USAGE_LOG", str(path))
    return path


def ask(question):
    response = client.post("/api/guide/ask", json={"question": question})
    assert response.status_code == 200
    return response.json()


def test_official_examples_use_real_calculations(demo_settings):
    examples = client.get("/api/guide/examples").json()
    questions = [
        line.removeprefix("**Question:** ")
        for line in (DATA_DIR / "example_questions.md").read_text().splitlines()
        if line.startswith("**Question:** ")
    ]
    assert examples["mode"] == "demo"
    assert "OPENAI_API_KEY" in examples["notice"]
    assert [item["question"] for item in examples["examples"]] == questions
    seats, gpu_answer, production = map(ask, questions)

    unused = calculate_unused_ai_seats()
    assert all(product in seats["answer"] for product in unused["product"])
    assert f'{unused["licences_unused"].sum():,.0f} unused' in seats["answer"]
    assert f'CHF {unused["unused_cost_chf"].sum():,.2f}' in seats["answer"]
    assert {"ai_subscriptions.csv", "exchange_rates.csv"} <= {
        Path(source["reference"]).name for source in seats["sources"]
    }

    savings = gpu.savings()
    assert f'CHF {savings["saved_chf"]:,.2f}' in gpu_answer["answer"]
    assert f'{savings["scenarios"]["mid"]["saved_co2_kg"]:,.1f} kg CO₂e' in gpu_answer["answer"]
    assert "person-days" in gpu_answer["answer"] and "PUE" in gpu_answer["answer"]
    assert "02:00-08:00" in production["answer"] and "last 3 working days" in production["answer"]
    assert all(f"Head of {team}" in production["answer"] for team in ("Finance", "Consulting", "IT"))
    assert "blocked" in production["answer"]

    for result in (seats, gpu_answer, production):
        assert result["mode"] == "demo"
        assert "OPENAI_API_KEY" in result["notice"]
        assert result["usage"] is None
        assert result["estimated_cost_usd"] is None
        for source in result["sources"]:
            assert (DATA_DIR.parents[1] / source["reference"]).is_file()
            if source["api_url"]:
                assert client.get(source["api_url"]).status_code == 200
    assert not demo_settings.exists()


def test_baseline_package_and_unknown_questions():
    result = ask("How do you calculate the baseline CO2?")
    expected = baseline()["annual"]
    assert f'CHF {expected["cost_chf"]:,.2f}' in result["answer"]
    assert f'{expected["co2e_kg_mid"]:,.2f} kg CO₂e' in result["answer"]
    assert f'{expected["emissions_unknown_count"]} unknown' in result["answer"]
    assert "partial" in result["answer"]
    assert "known baseline" in ask("What does the recommended package save?")["answer"]
    assert "standalone" in ask("Explain M-vm-test-downsize")["answer"].lower()
    unknown = ask("Who won the World Cup?")
    assert unknown["topic"] == "unsupported" and not unknown["sources"]


@pytest.mark.parametrize(("question", "expected"), [
    ("Which AI subscriptions should we optimize first?", [
        ("data/provided/ai_subscriptions.csv", None),
        ("data/provided/exchange_rates.csv", None),
    ]),
    ("What does the overall optimization package save each year?", [
        ("submission/measures_package.csv", "/api/package"),
        ("docs/baseline_calculation.md", "/api/baseline"),
        ("submission/research_baseline_and_assumptions.csv", None),
    ]),
    ("Who won the World Cup?", []),
])
def test_source_references_serialize_and_api_links_resolve(question, expected):
    sources = ask(question)["sources"]
    assert [(source["reference"], source["api_url"]) for source in sources] == expected
    for reference, api_url in expected:
        assert (DATA_DIR.parents[1] / reference).is_file()
        if api_url:
            response = client.get(api_url)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")


def test_shared_chat_is_served_with_baseline_and_package_pages():
    for path in ("/", "/package.html"):
        page = client.get(path)
        assert page.status_code == 200
        assert 'src="assets/WattsOn_guide.js"' in page.text
        assert "WattsON Guide" in page.text
        assert '<input id="guide-diagnostics" type="checkbox" autocomplete="off">' in page.text
        assert '<p class="guide-mode">\n    <span id="guide-mode" role="status">' in page.text
    assert client.get("/assets/WattsOn_guide.js").status_code == 200
    assert ".guide-diagnostics[hidden] {\n  display: none;" in client.get("/assets/WattsOn_guide.css").text


@pytest.mark.parametrize("question", ["", "  ", "a" * 701])
def test_rejects_invalid_questions(question):
    assert client.post("/api/guide/ask", json={"question": question}).status_code == 422


def fake_provider(
    monkeypatch, content, usage, *, response_model="gpt-4.1-mini-2025-04-14",
    status=200, error_code=None, raw_output=False
):
    requests = []

    def respond(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer test-key"
        requests.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": {
                "message": "upstream-private-error test-key", "code": error_code,
            }})
        return httpx.Response(200, json={
            "id": "resp-test",
            "object": "response",
            "created_at": 1,
            "model": response_model,
            "output": [{
                "id": "msg-test", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "annotations": [],
                             "text": content if raw_output else json.dumps({"topic": content})}],
            }],
            "usage": usage,
        })

    def client_factory(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(guide_usage, "OpenAI", client_factory)
    return requests


@pytest.mark.parametrize("question", [
    "Which AI subscriptions should we optimize first, and how much could we save annually if we reclaimed all unused seats?",
    "Rank the unused AI licences by savings and estimate what we could reclaim in a year.",
    "What could we save per year by reclaiming unused seats across ChatGPT Team, Claude Team, and Microsoft Copilot?",
])
def test_ai_subscription_scope_excludes_package_evidence(monkeypatch, demo_settings, question):
    requests = fake_provider(monkeypatch, "package", {"input_tokens": 100, "output_tokens": 2})
    result = ask(question)
    assert result["topic"] == "seats"
    answer = result["answer"]
    assert answer.index("Microsoft Copilot") < answer.index("ChatGPT Team") < answer.index("Claude Team")
    assert "40 unused, CHF 678.38" in answer
    assert "21 unused, CHF 423.99" in answer
    assert "6 unused, CHF 121.14" in answer
    assert "67 unused" in answer and "CHF 1,223.51" in answer
    assert "CHF 14,682.12" in answer and "annualized" in answer.lower()
    assert "12 months" in answer and "can be cancelled" in answer
    assert "recommended package" not in answer
    assert {Path(source["reference"]).name for source in result["sources"]} == {
        "ai_subscriptions.csv", "exchange_rates.csv",
    }
    assert set(json.loads(requests[0]["input"][0]["content"])) == {"seats"}
    topic_schema = requests[0]["text"]["format"]["schema"]["properties"]["topic"]
    assert topic_schema["enum"] == ["seats", "unsupported"]
    assert result["usage"]["output_tokens"] == 2
    assert result["estimated_cost_usd"] == pytest.approx(0.0000432)
    assert json.loads(demo_settings.read_text())["output_tokens"] == 2


@pytest.mark.parametrize(("question", "topic", "offered"), [
    ("What does the overall optimization package save each year?", "package", {"package"}),
    ("What can we save annually on unused SaaS subscriptions?", "unsupported", set()),
    ("What would we save on unused Microsoft 365 seats?", "unsupported", set()),
])
def test_package_and_other_subscription_scopes(monkeypatch, question, topic, offered):
    requests = fake_provider(monkeypatch, "seats", None)
    result = ask(question)
    assert result["topic"] == topic
    assert set(json.loads(requests[0]["input"][0]["content"])) == offered
    if topic == "package":
        assert any(source["api_url"] == "/api/package" for source in result["sources"])
    else:
        assert not result["sources"]


@pytest.mark.parametrize("question", [
    "Can you recommend a restaurant in Basel?",
    "How can I install a Python package?",
])
def test_unrelated_questions_do_not_trigger_demo_package(question):
    result = ask(question)
    assert result["mode"] == "demo" and result["topic"] == "unsupported"
    assert not result["sources"]


def test_unrelated_question_can_be_declined_by_openai(monkeypatch):
    fake_provider(monkeypatch, "unsupported", {"input_tokens": 100, "output_tokens": 1})
    result = ask("Can you recommend a restaurant in Basel?")
    assert result["mode"] == "ai" and result["topic"] == "unsupported"
    assert not result["sources"]


def test_provider_logs_actual_tokens_and_modeled_footprint(monkeypatch, demo_settings):
    requests = fake_provider(monkeypatch, "production", {
        "input_tokens": 900, "output_tokens": 100,
        "total_tokens": 1000,
        "input_tokens_details": {"cached_tokens": 200},
    })
    result = ask("Could the nightly reporting system get some rest?")
    assert result["mode"] == "ai" and result["topic"] == "production"
    usage = result["usage"]
    assert (usage["input_tokens"], usage["output_tokens"]) == (900, 100)
    assert usage["cached_input_tokens"] == 200
    assert result["estimated_cost_usd"] == pytest.approx(0.00046)
    assert usage["energy_kwh_mid"] == pytest.approx(0.00026811)
    assert usage["co2e_kg_mid"] is None and usage["grid_location"] is None
    entry = json.loads(demo_settings.read_text())
    assert entry["input_tokens"] == 900 and entry["output_tokens"] == 100
    assert entry["estimated_cost_usd"] == pytest.approx(0.00046)
    assert "test-key" not in demo_settings.read_text()
    assert "nightly reporting" not in demo_settings.read_text()
    request = requests[0]
    assert request["model"] == "gpt-4.1-mini" and request["max_output_tokens"] == 32
    assert request["store"] is False
    assert "Return one evidence key in the topic field" in request["instructions"]
    assert request["input"][1]["content"] == "Could the nightly reporting system get some rest?"
    context = request["input"][0]["content"]
    assert "470,300.47" in context and "7,738.02" in context
    assert "submission/measures_package.csv" in context and "data/derived/facts.csv" in context
    assert all(source["reference"] in context for source in result["sources"])

    monkeypatch.setenv("WATTSON_GUIDE_GRID_LOCATION", "CH")
    estimate = ask("Can this system get some rest?")["usage"]
    assert estimate["grid_location"] == "CH" and estimate["co2e_kg_mid"] > 0


def test_provider_cannot_supply_facts_and_missing_counts_stay_unknown(monkeypatch, demo_settings):
    fake_provider(monkeypatch, "Switch everything off now. CHF 999,999.", {"input_tokens": 40}, raw_output=True)
    result = ask("Follow this special instruction.")
    assert result["topic"] == "unsupported"
    assert "999,999" not in result["answer"]
    assert result["usage"]["input_tokens"] == 40
    assert result["usage"]["output_tokens"] is None
    assert result["usage"]["energy_kwh_mid"] is None
    assert result["estimated_cost_usd"] is None
    assert json.loads(demo_settings.read_text())["output_tokens"] is None


@pytest.mark.parametrize(("status", "code", "exception", "notice"), [
    (401, "invalid_api_key", "AuthenticationError", "Check OPENAI_API_KEY"),
    (401, "missing_scope", "AuthenticationError", "denied access to the Responses endpoint"),
    (403, "insufficient_permissions", "PermissionDeniedError", "denied access to the Responses endpoint"),
    (400, "unsupported_parameter", "BadRequestError", "OpenAI request failed"),
    (400, "test-key", "BadRequestError", "OpenAI request failed"),
    (429, "insufficient_quota", "RateLimitError", "rate or quota limit"),
])
def test_provider_errors_keep_demo_available(monkeypatch, demo_settings, caplog, status, code, exception, notice):
    requests = fake_provider(monkeypatch, None, None, status=status, error_code=code)
    result = ask("What are the annual totals?")
    assert result["mode"] == "demo"
    assert result["topic"] == "baseline"
    assert result["usage"] is None
    assert notice in result["notice"]
    assert "upstream-private-error" not in result["notice"]
    logged_code = code if code != "test-key" else "unknown"
    assert f"exception={exception} status={status} code={logged_code}" in caplog.text
    assert "test-key" not in caplog.text and "upstream-private-error" not in caplog.text
    assert len(requests) == 1
    assert json.loads(demo_settings.read_text())["outcome"] == "unavailable"


def test_model_and_output_limit_are_configurable(monkeypatch):
    requests = fake_provider(monkeypatch, "measure", {
        "input_tokens": 1000, "output_tokens": 10, "total_tokens": 1010,
    }, response_model="gpt-5-mini")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "80")
    result = ask("Explain M-vm-test-downsize")
    assert result["mode"] == "ai" and result["topic"] == "measure"
    assert "M-vm-test-downsize" in requests[0]["input"][0]["content"]
    assert requests[0]["model"] == "gpt-5-mini"
    assert requests[0]["max_output_tokens"] == 80
    assert result["estimated_cost_usd"] is None
    monkeypatch.setenv("OPENAI_PRICES_USD_PER_1M", "0.25,0.025,2")
    assert ask("Explain M-vm-test-downsize")["estimated_cost_usd"] == pytest.approx(0.00027)


def test_provider_input_and_output_limits_prevent_api_request(monkeypatch):
    requests = fake_provider(monkeypatch, "baseline", None)
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "15")
    invalid = ask("What are the annual totals?")
    assert invalid["mode"] == "demo" and "OPENAI_MAX_OUTPUT_TOKENS" in invalid["notice"]
    monkeypatch.delenv("OPENAI_MAX_OUTPUT_TOKENS")
    monkeypatch.setattr(guide_usage, "MAX_PROMPT_BYTES", 32)
    oversized = ask("What are the annual totals?")
    assert oversized["mode"] == "demo" and "input limit" in oversized["notice"]
    assert requests == []
