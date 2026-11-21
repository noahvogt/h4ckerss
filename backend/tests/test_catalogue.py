import pandas as pd
import pytest

from app.limits.rules import known_resources
from app.measures.catalogue import OUTPUT, PERSON_DAY_CHF, build_catalogue, kept_hours_on_demand


@pytest.fixture(scope="module")
def cat():
    return build_catalogue().set_index("measure_id")


def test_every_measure_is_checkable(cat):
    assert set(cat["resource_id"]) <= known_resources()
    assert cat.index.is_unique
    assert (cat["effort_chf"] == cat["effort_person_days"] * PERSON_DAY_CHF).all()


@pytest.mark.parametrize(
    "measure_id, savings, status",
    [
        ("M-saas-other", 33_596, "allowed"),
        ("M-dp-prod-schedule", 32_855, "allowed_outside_windows"),
        ("M-dp-dev-pause", 26_360, "allowed_outside_windows"),
        ("M-vm-test-downsize", 18_462, "allowed"),
        ("M-gpu-ml-pause", 7_738, "allowed_outside_windows"),
        ("M-sub-copilot", 6_920, "allowed"),
        ("M-ai-assistant-model", 5_927, "allowed"),
        ("M-sub-chatgpt", 5_088, "needs_human"),
        ("M-dp-dev-relocate", -38, "allowed"),
    ],
)
def test_savings_and_status(cat, measure_id, savings, status):
    assert cat.loc[measure_id, "savings_cost_chf_per_year"] == pytest.approx(savings, abs=1)
    assert cat.loc[measure_id, "status"] == status


def test_credits_are_not_counted_as_saveable_cost(cat):
    # dp-prod had a CHF -2,400 SLA credit in June 2026; a schedule cannot save it.
    assert cat.loc["M-dp-prod-schedule", "baseline_cost_chf"] == pytest.approx(89_660, abs=1)


def test_relocation_changes_location_not_usage(cat):
    m = cat.loc["M-dp-dev-relocate"]
    assert (m["location"], m["location_after"], m["usage_factor"]) == ("DE", "CH", 1.0)


def test_seat_measures_do_not_claim_energy_savings(cat):
    for mid in ["M-sub-copilot", "M-sub-claude", "M-sub-chatgpt"]:
        assert cat.loc[mid, "usage_factor"] == 1.0 and cat.loc[mid, "cost_factor"] < 1.0


def test_windows_are_carried_as_conditions(cat):
    assert cat.loc["M-dp-prod-schedule", "conditions"].split("; ")[0].startswith("R01 last 3 working days")


def test_on_demand_hours():
    # 247 working days x 10 h + 12 training days x 24 h (some of them working days)
    assert kept_hours_on_demand("R02") == pytest.approx(2728, abs=1)


def test_committed_csv_is_up_to_date(cat):
    """Fix: cd backend && uv run python -m app.measures.catalogue"""
    committed = pd.read_csv(OUTPUT).set_index("measure_id").sort_index()
    pd.testing.assert_series_equal(
        committed["savings_cost_chf_per_year"], cat["savings_cost_chf_per_year"].sort_index(), check_dtype=False
    )
