import json
from pathlib import Path
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

from app import guide_usage
from app.main import app
from app.measures import gpu
from app.pipeline.ai_saas import calculate_unused_ai_seats
from app.pipeline.common import DATA_DIR
from app.routers.baseline import baseline

client = TestClient(app)


@pytest.fixture(autouse=True)
def demo_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
        assert result["usage"] is None
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


def test_shared_chat_is_served_with_baseline_and_package_pages():
    for path in ("/", "/package.html"):
        page = client.get(path)
        assert page.status_code == 200
        assert 'src="assets/WattsOn_guide.js"' in page.text
        assert "WattsON Guide" in page.text
    assert client.get("/assets/WattsOn_guide.js").status_code == 200


@pytest.mark.parametrize("question", ["", "  ", "a" * 701])
def test_rejects_invalid_questions(question):
    assert client.post("/api/guide/ask", json={"question": question}).status_code == 422


def fake_provider(monkeypatch, content, usage):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_):
            return json.dumps({
                "model": "gpt-4.1-mini",
                "choices": [{"message": {"content": content}}],
                "usage": usage,
            }).encode()

    def request(req, *, timeout):
        assert timeout > 0
        messages = json.loads(req.data)["messages"]
        assert "csv" not in messages[-1]["content"]
        return Response()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(guide_usage, "urlopen", request)


def test_provider_logs_actual_tokens_and_modeled_footprint(monkeypatch, demo_settings):
    fake_provider(monkeypatch, "production", {
        "prompt_tokens": 900, "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 200},
    })
    result = ask("Could the nightly reporting system get some rest?")
    assert result["mode"] == "ai" and result["topic"] == "production"
    usage = result["usage"]
    assert (usage["input_tokens"], usage["output_tokens"]) == (900, 100)
    assert usage["energy_kwh_mid"] == pytest.approx(0.00026811)
    assert usage["co2e_kg_mid"] is None and usage["grid_location"] is None
    entry = json.loads(demo_settings.read_text())
    assert entry["input_tokens"] == 900 and entry["output_tokens"] == 100
    assert "test-key" not in demo_settings.read_text()
    assert "nightly reporting" not in demo_settings.read_text()

    monkeypatch.setenv("WATTSON_GUIDE_GRID_LOCATION", "CH")
    estimate = ask("Can this system get some rest?")["usage"]
    assert estimate["grid_location"] == "CH" and estimate["co2e_kg_mid"] > 0


def test_provider_cannot_supply_facts_and_missing_counts_stay_unknown(monkeypatch, demo_settings):
    fake_provider(monkeypatch, "Switch everything off now. CHF 999,999.", {"prompt_tokens": 40})
    result = ask("Follow this special instruction.")
    assert result["topic"] == "unsupported"
    assert "999,999" not in result["answer"]
    assert result["usage"]["input_tokens"] == 40
    assert result["usage"]["output_tokens"] is None
    assert result["usage"]["energy_kwh_mid"] is None
    assert json.loads(demo_settings.read_text())["output_tokens"] is None


def test_provider_outage_keeps_demo_available(monkeypatch, demo_settings):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def unavailable(*args, **kwargs):
        raise URLError("unavailable")

    monkeypatch.setattr(guide_usage, "urlopen", unavailable)
    result = ask("What are the annual totals?")
    assert result["mode"] == "demo"
    assert result["topic"] == "baseline"
    assert result["usage"] is None
    assert json.loads(demo_settings.read_text())["outcome"] == "unavailable"
