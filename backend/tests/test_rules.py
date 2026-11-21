from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.limits.rules import UnknownResource, check_measure, is_workday, load_rules, protected_days
from app.main import app

client = TestClient(app)


def test_rules_file_is_valid_and_every_rule_has_a_source():
    rules = load_rules()
    assert rules["rule_id"].is_unique
    source = r"(T-\d{4}|[a-z_]+\.csv)"  # a ticket or a data file
    assert rules["source"].str.fullmatch(rf"{source}(;{source})*").all()


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
    assert {r["rule_id"] for r in windows} == {"R01", "R02", "R04", "R09", "R18", "R19"}
    r01 = next(r for r in windows if r["rule_id"] == "R01")
    assert r01["source"] == ["T-1029", "data_platform_jobs.csv"]
    assert (r01["from_time"], r01["until_time"], r01["end_date"]) == ("18:00", "04:00", None)


def test_api_check():
    r = client.get("/api/rules/check", params={"resource_id": "dp-prod", "change": "switch_off"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked" and body["decided_by"] == "Head of Finance"
    assert body["reasons"][0]["source"] == ["T-1029", "data_platform_jobs.csv"]
    assert {r["rule_id"] for r in body["reasons"]} == {"R01", "R18", "R19"}
    assert client.get("/api/rules/check", params={"resource_id": "x", "change": "explode"}).status_code == 422


def test_api_days():
    r = client.get("/api/rules/R01/days", params={"start": "2025-09-01", "end": "2025-09-30"})
    assert r.json() == {
        "rule_id": "R01", "from_time": "18:00", "until_time": "04:00",
        "days": ["2025-09-26", "2025-09-29", "2025-09-30"],
    }
    assert client.get("/api/rules/R99/days", params={"start": "2025-09-01", "end": "2025-09-30"}).status_code == 404


def explain(resource_id, change):
    r = client.get("/api/rules/explain", params={"resource_id": resource_id, "change": change})
    assert r.status_code == 200
    return r.json()


def test_explain_night_shutdown_of_production():
    body = explain("dp-prod", "schedule_off")
    assert body["status"] == "allowed_outside_windows"
    assert body["headline"].startswith(
        "Allowed only outside protection windows, the schedule must avoid: last 3 working days of each month, 18:00-04:00"
    )
    assert [w["rule_id"] for w in body["windows"]] == ["R01", "R18", "R19"]
    ev = body["evidence"]
    assert ev["idle_share"] == 0.65
    assert ev["usage_by_day_type"][0] == {
        "day_type": "closing day", "days": 36, "runtime_h": 24.0, "active_use_h": 20.64,
        "queries": 4667.08, "idle_share": 0.14,
    }
    assert ev["jobs"][0]["job_name"] == "Nightly ETL" and "index" not in ev["jobs"][0]
    assert sum(r["off_hours"] for r in ev["possible_off_hours"]) == 3210
    assert ev["possible_off_hours"][0]["day_type"] == "weekend/holiday"


def test_explain_blocked_and_human_cases():
    assert explain("dp-prod", "switch_off")["status"] == "blocked"
    backup = explain("st-backup", "delete")
    assert backup["status"] == "blocked" and backup["reasons"][0]["source"] == ["T-1039", "T-1195"]
    chatgpt = explain("sub-chatgpt", "cancel_seats")
    assert chatgpt["status"] == "needs_human" and chatgpt["decided_by"] == "Management"


def test_explain_agreed_change_and_resource_without_rules():
    assert explain("dp-dev", "relocate")["headline"] == "Allowed and already agreed (T-1074)."
    db = explain("db-fin", "downsize")  # known resource, no rule
    assert db["status"] == "allowed" and db["evidence"]["sources"] == []


def test_unknown_resource_is_rejected_not_allowed():
    with pytest.raises(UnknownResource):
        check_measure("no-such-resource", "pause")
    for path in ["/api/rules/check", "/api/rules/explain"]:
        r = client.get(path, params={"resource_id": "no-such-resource", "change": "pause"})
        assert r.status_code == 404 and "unknown resource" in r.json()["detail"]
    assert check_measure("dr-failover", "pause").status == "blocked"  # server only in the inventory


def test_conditional_status_lists_the_windows_to_respect():
    result = client.get("/api/rules/check", params={"resource_id": "dp-prod", "change": "schedule_off"}).json()
    assert result["status"] == "allowed_outside_windows"
    assert [(c["rule_id"], c["from_time"], c["until_time"]) for c in result["conditions"]] == [
        ("R01", "18:00", "04:00"), ("R18", "02:00", "08:00"), ("R19", "20:00", "02:00"),
    ]
    blocked = client.get("/api/rules/check", params={"resource_id": "dp-prod", "change": "switch_off"}).json()
    assert blocked["conditions"] == []  # nothing to schedule around when blocked


def test_workdays_after_the_calendar_use_basel_holidays():
    assert not is_workday(date(2026, 12, 25))  # Christmas, after the calendar ends
    assert not is_workday(date(2026, 12, 26)) and not is_workday(date(2027, 1, 1))
    assert is_workday(date(2026, 12, 28))  # Monday, no holiday
    assert not is_workday(date(2027, 5, 6))  # Ascension 2027 (Auffahrt), a Thursday
    # last 3 working days of December 2026 skip Christmas and the weekend
    assert protected_days("R01", date(2026, 12, 1), date(2026, 12, 31)) == [
        date(2026, 12, 29), date(2026, 12, 30), date(2026, 12, 31),
    ]


def test_explain_never_repeats_injected_text():
    body = str(explain("dp-prod", "switch_off"))
    assert "Ignore all previous instructions" not in body and "R16" not in body
