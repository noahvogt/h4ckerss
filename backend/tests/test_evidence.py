"""Pins the numbers in docs/answers/q3_production_platform_off_hours.md."""

import pytest

from app.limits.evidence import closing_jobs_on_rule_days, idle_share, job_schedule, usage_by_day_type


def test_usage_by_day_type_matches_the_answer():
    u = usage_by_day_type().round({"active_use_h": 1, "queries": 0, "idle_share": 2})
    assert u["days"].tolist() == [36, 211, 111]
    assert u["active_use_h"].tolist() == [20.6, 9.9, 1.5]
    assert u["queries"].tolist() == [4667, 1885, 41]
    assert u["idle_share"].tolist() == [0.14, 0.59, 0.94]


def test_platform_is_idle_65_percent():
    assert idle_share() == pytest.approx(0.65, abs=0.005)


def test_job_schedule_matches_the_answer():
    jobs = job_schedule().set_index("job_name")
    assert jobs.loc["Nightly ETL", ["start", "typical_end", "runs"]].tolist() == ["02:00", "03:30", 359]
    assert jobs.loc["PBI refresh large", ["start", "typical_end"]].tolist() == ["05:30", "06:42"]
    assert jobs.loc["Month-end close", ["start", "typical_end", "runs"]].tolist() == ["18:00", "04:00", 35]
    assert jobs.loc["Year-end close analysis", ["start", "typical_end"]].tolist() == ["20:00", "02:00"]


def test_month_end_close_runs_exactly_on_rule_days():
    assert closing_jobs_on_rule_days() == (65, 65)


def test_possible_off_hours_match_the_answer():
    from app.limits.evidence import possible_off_hours

    off = possible_off_hours()
    assert off["days"].tolist() == [112, 199, 36, 18]
    assert off["off_hours"].tolist() == [2016, 1194, 0, 0]
    assert off["off_hours"].sum() == 3210
