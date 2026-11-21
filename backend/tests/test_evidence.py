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


def test_off_schedule_never_hits_a_job_run():
    from app.limits.evidence import off_schedule_conflicts, off_windows

    windows = off_windows()
    assert len(windows) == 311
    assert sum((b - a).total_seconds() for a, b in windows) / 3600 == 3210
    checked, conflicts = off_schedule_conflicts()
    assert checked == 1487 and conflicts.empty  # baseline year plus 2025-08-31


def test_business_use_on_working_days_fits_before_20h():
    from app.limits.evidence import business_hours

    b = business_hours().round(2)
    assert b.loc["workday", "other_h"] == 6.06  # about 6 h of interactive use
    assert b.loc["workday", "other_h_max"] == 9.07  # < 10 h office day 08:00-18:00
