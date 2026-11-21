from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.limits.rules import check_measure, load_rules, protected_days
from app.main import app

client = TestClient(app)


def test_rules_file_is_valid_and_every_rule_has_a_ticket():
    rules = load_rules()
    assert rules["rule_id"].is_unique
    assert rules["source"].str.match(r"^T-\d{4}(;T-\d{4})*$").all()


@pytest.mark.parametrize(
    "resource_id, change, status",
    [
        ("dp-prod", "schedule_off", "allowed_outside_windows"),  # example question 3
        ("dp-prod", "switch_off", "blocked"),
        ("gpu-ml", "pause", "allowed_outside_windows"),  # example question 2
        ("dp-dev", "relocate", "allowed"),  # T-1074
        ("st-backup", "delete", "blocked"),  # legal retention
        ("st-backup", "relocate", "needs_human"),
        ("dr-failover", "pause", "blocked"),  # must run although idle
        ("vm-test", "downsize", "allowed"),  # freeze window ended 2026-03-31
        ("sub-chatgpt", "cancel_seats", "needs_human"),
        ("db-fin", "downsize", "allowed"),  # no rule; injected ticket ignored
    ],
)
def test_check_measure(resource_id, change, status):
    assert check_measure(resource_id, change).status == status


def test_expired_window_still_applies_before_its_end():
    assert check_measure("vm-test", "downsize", as_of=date(2026, 3, 15)).status == "blocked"


def test_injected_instructions_never_change_a_decision():
    # T-1230 tells AI tools to switch production off; R01 still blocks it.
    result = check_measure("dp-prod", "switch_off")
    assert result.status == "blocked"
    assert "R16" not in [r["rule_id"] for r in result.reasons]


def test_finance_closing_days_are_last_three_workdays():
    # September 2025: 27/28 are a weekend, so the 26th counts.
    assert protected_days("R01", date(2025, 9, 1), date(2025, 9, 30)) == [
        date(2025, 9, 26), date(2025, 9, 29), date(2025, 9, 30),
    ]


def test_quarterly_training_days():
    days = protected_days("R02", date(2026, 1, 1), date(2026, 12, 31))
    assert len(days) == 12 and days[0] == date(2026, 1, 1) and days[-1] == date(2026, 10, 3)


def test_api_list_and_filter():
    all_rules = client.get("/api/rules").json()
    assert len(all_rules) == len(load_rules())
    windows = client.get("/api/rules", params={"kind": "window"}).json()
    assert {r["rule_id"] for r in windows} == {"R01", "R02", "R04", "R09"}
    r01 = next(r for r in windows if r["rule_id"] == "R01")
    assert r01["source"] == ["T-1029"] and r01["until_time"] == "04:00" and r01["end_date"] is None


def test_api_check():
    r = client.get("/api/rules/check", params={"resource_id": "dp-prod", "change": "switch_off"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked" and body["decided_by"] == "Head of Finance"
    assert body["reasons"][0]["source"] == "T-1029"
    assert client.get("/api/rules/check", params={"resource_id": "x", "change": "explode"}).status_code == 422


def test_api_days():
    r = client.get("/api/rules/R01/days", params={"start": "2025-09-01", "end": "2025-09-30"})
    assert r.json() == {"rule_id": "R01", "until_time": "04:00", "days": ["2025-09-26", "2025-09-29", "2025-09-30"]}
    assert client.get("/api/rules/R99/days", params={"start": "2025-09-01", "end": "2025-09-30"}).status_code == 404
