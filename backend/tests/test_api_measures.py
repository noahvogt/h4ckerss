import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.measures.package import OUTPUT

client = TestClient(app)


@pytest.fixture(scope="module")
def package():
    r = client.get("/api/package")
    assert r.status_code == 200
    return r.json()


def test_baseline_matches_the_submission_template():
    r = client.get("/api/baseline")
    assert r.status_code == 200
    annual = r.json()["annual"]
    assert annual["cost_chf"] == pytest.approx(470_300.47, abs=0.01)
    assert annual["co2e_kg_mid"] == pytest.approx(4203.96, abs=0.01)
    assert annual["emissions_coverage"] == "partial"
    assert r.json()["rows"]  # the map overview needs them


def test_package_is_the_submitted_one(package):
    submitted = pd.read_csv(OUTPUT)
    assert package["summary"]["measures"] == submitted["measure_id"].tolist()
    by_id = {m["measure_id"]: m for m in package["measures"]}
    for row in submitted.to_dict("records"):
        assert by_id[row["measure_id"]]["savings_chf"] == pytest.approx(row["savings_cost_chf_per_year"], abs=0.5)
        assert by_id[row["measure_id"]]["savings_co2_kg"] == pytest.approx(row["savings_co2_kg_location_based"], abs=0.5)


def test_package_summary_targets_and_sensitivity(package):
    s = package["summary"]
    assert s["targets"] == "met_known_baseline" and s["within_budget"] and s["needs_approval"] == []
    assert s["effort_chf"] <= package["targets"]["budget_chf"] == 16_500
    assert package["targets"]["co2_baseline_complete"] is False
    assert sum(m["savings_chf"] for m in package["measures"]) == pytest.approx(s["savings_chf"])
    assert list(package["sensitivity"]) == ["low", "mid", "high"]
    assert package["sensitivity"]["mid"]["co2_reduction"] == pytest.approx(s["co2_reduction"])
    assert len(package["alternatives"]) == 5
    assert package["alternatives"][0]["measures"] != s["measures"]


def test_measures_link_to_their_explanation(package):
    m = next(m for m in package["measures"] if m["measure_id"] == "M-dp-prod-schedule")
    assert m["conditions"][0].startswith("R01") and m["decided_by"] == "Head of Finance"
    r = client.get(m["explain_url"])
    assert r.status_code == 200 and r.json()["status"] == m["status"]


def test_variant_with_approvals():
    s = client.get("/api/package", params={"approvals": True, "alternatives": 0}).json()
    assert s["summary"]["needs_approval"] == ["M-sub-chatgpt"] and s["alternatives"] == []


def test_catalogue_lists_every_measure_with_standalone_savings():
    measures = {m["measure_id"]: m for m in client.get("/api/measures").json()}
    assert len(measures) == 11 and measures["M-sub-chatgpt"]["status"] == "needs_human"
    assert measures["M-dp-dev-relocate"]["savings_co2_kg"] > 0  # on its own: all of dp-dev moves
    assert measures["M-saas-other"]["savings_co2_kg"] == 0 and measures["M-saas-other"]["savings_kwh"] == 0
    assert measures["M-dp-dev-pause"]["interacts_with"] == ["M-dp-dev-relocate"]


def test_evaluate_a_selection_after_a_rejection(package):
    rejected = "M-saas-other"
    ids = [m for m in package["summary"]["measures"] if m != rejected]
    r = client.post("/api/package/evaluate", json={"measure_ids": ids})
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["measures"] == ids and s["targets"] == "not_met"  # without SaaS the cost target is missed
    assert s["co2_reduction"] == pytest.approx(package["summary"]["co2_reduction"])  # seats save no CO2


@pytest.mark.parametrize("ids, status", [(["M-nope"], 404), ([], 422)])
def test_evaluate_rejects_bad_selections(ids, status):
    assert client.post("/api/package/evaluate", json={"measure_ids": ids}).status_code == status


def test_evaluate_rejects_blocked_measures(monkeypatch):
    from app.measures import package as pkg

    cat = pkg.catalogue()
    blocked = cat.assign(status=cat["status"].where(cat["measure_id"] != "M-vm-test-downsize", "blocked"))
    monkeypatch.setattr(pkg, "catalogue", lambda: blocked)
    r = client.post("/api/package/evaluate", json={"measure_ids": ["M-vm-test-downsize"]})
    assert r.status_code == 422 and "blocked" in r.json()["detail"]


def test_startup_warms_the_caches():
    with TestClient(app) as warm:  # runs the lifespan
        assert warm.get("/api/health").status_code == 200
