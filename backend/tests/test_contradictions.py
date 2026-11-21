"""Pins the numbers in docs/answers/contradictions.md."""

import pytest
from fastapi.testclient import TestClient

from app.limits.contradictions import effective_criticality, provider_report_vs_invoices, server_criticality
from app.main import app


def test_provider_report_vs_invoices():
    r = provider_report_vs_invoices()
    assert len(r) == 22
    assert r["diff_share"].abs().median() == pytest.approx(0.04, abs=0.005)
    assert r["flagged"].sum() == 8
    march = r.loc["2026-03-01"]
    assert (round(march.report_chf), round(march.invoices_chf)) == (28240, 24794)
    assert march.diff_share == pytest.approx(0.139, abs=0.001)


def test_prod_servers_without_criticality():
    s = server_criticality()
    assert s["server_id"].tolist() == ["app-01", "app-03", "app-06", "app-08", "app-10", "app-11", "app-12"]
    assert (s["effective_criticality"] == "high").all()


def test_effective_criticality():
    assert effective_criticality("app-01") == "high"  # prod, criticality empty
    assert effective_criticality("dr-failover") == "high"
    assert effective_criticality("no-such-server") == "unknown"


def test_api_contradictions():
    body = TestClient(app).get("/api/rules/contradictions").json()
    assert [c["id"] for c in body] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    c1 = body[0]
    assert c1["trusted"] == "invoices" and len(c1["details"]) == 8
    assert {"month": "2026-03", "report_chf": 28240, "invoices_chf": 24794, "diff_share": 0.139} in c1["details"]
