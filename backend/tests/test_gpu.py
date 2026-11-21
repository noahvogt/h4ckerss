"""Pins the numbers in docs/answers/q2_gpu_on_demand.md (example question 2)."""

import pytest

from app.measures import gpu, package as pkg


@pytest.fixture(scope="module")
def answer():
    return gpu.answer()


def test_today_the_server_runs_around_the_clock_and_is_mostly_idle(answer):
    u = answer["utilisation"]
    assert u["weeks"] == 52 and u["always_on"] and u["uptime_h_per_week"] == 168
    assert u["gpu_avg_pct"] == pytest.approx(9.2, abs=0.05)
    assert u["training_weeks"] == 4
    assert u["gpu_avg_pct_training_weeks"] == pytest.approx(42.9, abs=0.05)
    assert u["gpu_avg_pct_other_weeks"] == pytest.approx(6.4, abs=0.05)
    assert answer["server"]["region"] == "Germany (Frankfurt)" and answer["server"]["environment"] == "dev"


def test_schedule_keeps_working_days_and_training(answer):
    s = answer["schedule"]
    assert (s["workdays"], s["training_days"], s["kept_h"]) == (244, 12, 2728)
    assert s["workdays"] * 10 + s["training_days"] * 24 == s["kept_h"]
    assert s["kept_share"] == pytest.approx(0.3114, abs=0.0001)


def test_billing(answer):
    b = answer["billing"]
    assert b["gpu_h"] == 8640 and b["cost_chf"] == pytest.approx(11_237.58, abs=0.01)
    assert b["chf_per_gpu_h"] == pytest.approx(1.30, abs=0.005) and b["location"] == "DE"


def test_savings_match_the_package(answer):
    s = answer["savings"]
    assert s["saved_chf"] == pytest.approx(7738, abs=1)
    assert s["effort_person_days"] == 2 and s["effort_chf"] == 2200
    assert s["payback_months"] == pytest.approx(3.4, abs=0.05)
    mid = s["scenarios"]["mid"]
    assert mid["saved_kwh"] == pytest.approx(480, abs=1) and mid["saved_co2_kg"] == pytest.approx(163, abs=1)
    rows = pkg.recommend()[0].set_index("measure_id")
    assert rows.loc[gpu.MEASURE, "savings_co2_kg"] == pytest.approx(mid["saved_co2_kg"])


def test_scenarios_and_idle_only_lower_bound(answer):
    sc = answer["savings"]["scenarios"]
    assert [round(sc[s]["saved_co2_kg"]) for s in pkg.SCENARIOS] == [85, 163, 1097]
    assert [round(sc[s]["idle_only_co2_kg"]) for s in pkg.SCENARIOS] == [85, 108, 168]
    # at 0 % load (low factor) both ways of counting agree
    assert sc["low"]["idle_only_kwh"] == pytest.approx(sc["low"]["saved_kwh"])
    for s in pkg.SCENARIOS:  # open calculation: hours x kWh per hour x PUE, times the grid
        expected = 8640 * sc[s]["kwh_per_gpu_h"] * sc[s]["pue"]
        assert sc[s]["baseline_kwh"] == pytest.approx(expected)
        assert sc[s]["saved_co2_kg"] == pytest.approx(sc[s]["saved_kwh"] * sc[s]["grid_kg_per_kwh"])


def test_decision(answer):
    d = answer["decision"]
    assert d["status"] == "allowed_outside_windows" and d["decided_by"] == "Head of Consulting"
    assert d["conditions"] == ["days 1-3 of January, April, July and October"]
    assert d["switch_off"] == "blocked"
