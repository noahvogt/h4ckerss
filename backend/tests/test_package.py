import pandas as pd
import pytest

from app.measures.catalogue import build_catalogue
from app.measures.package import (
    BUDGET_CHF, OUTPUT, TEMPLATE_COLUMNS, Co2Inputs, _targets, attribute, baseline_cost_chf, eligible,
    evaluate, recommend, search, to_template,
)
from app.pipeline.common import DATA_DIR


@pytest.fixture(scope="module")
def cat():
    return build_catalogue()


@pytest.fixture(scope="module")
def baseline():
    return baseline_cost_chf()


def pick(cat, *ids):
    return cat[cat["measure_id"].isin(ids)]


def test_same_resource_measures_are_combined_not_added(cat, baseline):
    both = pick(cat, "M-dp-dev-pause", "M-dp-dev-relocate")
    pause, move = (both.set_index("measure_id").loc[m] for m in ["M-dp-dev-pause", "M-dp-dev-relocate"])
    expected = pause["baseline_cost_chf"] * (1 - pause["cost_factor"] * move["cost_factor"])
    assert evaluate(both, baseline)["savings_chf"] == pytest.approx(expected)
    # per-measure rows add up to the combined total
    assert attribute(both)["savings_chf"].sum() == pytest.approx(expected)


def test_recommended_package_meets_cost_target_within_budget(baseline):
    rows, best, ranked = recommend()
    assert best["within_budget"] and best["meets_cost_target"]
    assert best["effort_chf"] <= BUDGET_CHF
    assert best["savings_chf"] == pytest.approx(132_850, abs=1)
    assert best["cost_reduction"] == pytest.approx(0.282, abs=0.001)
    assert best["effort_person_days"] == 13
    assert best["needs_approval"] == []
    assert best["targets"] == "pending" and best["meets_co2_target"] is None  # CO2 not known yet
    assert rows["savings_chf"].sum() == pytest.approx(best["savings_chf"])
    assert len(ranked) > 1  # alternatives exist for the trade-off view


def test_needs_human_only_in_the_variant_with_approvals():
    _, safe, _ = recommend()
    _, with_human, _ = recommend(include_needs_human=True)
    assert "M-sub-chatgpt" not in safe["measures"]
    assert with_human["needs_approval"] == ["M-sub-chatgpt"]
    assert with_human["savings_chf"] > safe["savings_chf"]


def test_blocked_measures_are_never_eligible(cat):
    blocked = cat.assign(status=cat["status"].where(cat["measure_id"] != "M-vm-test-downsize", "blocked"))
    assert "M-vm-test-downsize" not in set(eligible(blocked, include_needs_human=True)["measure_id"])


def test_co2_makes_the_relocation_worth_it(cat, baseline):
    # Synthetic CO2 until #4 is merged: dp-dev dominates, Frankfurt grid is dirty.
    co2 = Co2Inputs(
        resource_kg={"dp-dev": 10_000, "dp-prod": 3_000, "gpu-ml": 2_000, "vm-test": 2_000},
        total_kg=20_000, grid={"CH": 0.09, "DE": 0.34, "IE": 0.26, "EU": 0.22},
    )
    both = pick(cat, "M-dp-dev-pause", "M-dp-dev-relocate")
    pause = cat.set_index("measure_id").loc["M-dp-dev-pause", "usage_factor"]
    assert evaluate(both, baseline, co2)["savings_co2_kg"] == pytest.approx(10_000 * (1 - pause * 0.09 / 0.34))
    best = search(cat, baseline, co2).iloc[0]
    assert "M-dp-dev-relocate" in best["measures"] and best["meets_co2_target"]


def test_seat_measures_save_no_co2(cat, baseline):
    co2 = Co2Inputs(resource_kg={"sub-copilot": 500}, total_kg=1_000, grid={"EU": 0.22, "CH": 0.09})
    assert evaluate(pick(cat, "M-sub-copilot"), baseline, co2)["savings_co2_kg"] == 0


def test_without_co2_no_package_counts_as_meeting_the_co2_target(cat, baseline):
    ranked = search(cat, baseline)
    assert "met" not in set(ranked["targets"])
    assert set(ranked["targets"]) == {"pending", "not_met"}
    assert ranked["meets_co2_target"].isna().all()


@pytest.mark.parametrize("dp_prod_kg", [None, float("nan")])
def test_unknown_co2_stays_unknown_not_zero(cat, baseline, dp_prod_kg):
    kg = {"vm-test": 1_000} | ({} if dp_prod_kg is None else {"dp-prod": dp_prod_kg})
    co2 = Co2Inputs(resource_kg=kg, total_kg=10_000, grid={"CH": 0.09, "IE": 0.26, "EU": 0.22})
    selected = pick(cat, "M-dp-prod-schedule", "M-vm-test-downsize", "M-sub-copilot")
    rows = attribute(selected, co2).set_index("measure_id")
    assert pd.isna(rows.loc["M-dp-prod-schedule", "savings_co2_kg"])
    assert rows.loc["M-vm-test-downsize", "savings_co2_kg"] == pytest.approx(750)
    assert rows.loc["M-sub-copilot", "savings_co2_kg"] == 0  # seats: known zero, even without data
    result = evaluate(selected, baseline, co2)
    assert result["co2_unknown"] == ["M-dp-prod-schedule"]
    assert result["savings_co2_kg"] == pytest.approx(750)  # lower bound
    assert result["meets_co2_target"] is None  # undecidable, not met and not failed


def test_known_savings_can_meet_the_co2_target_despite_unknowns(cat, baseline):
    co2 = Co2Inputs(resource_kg={"vm-test": 1_000}, total_kg=1_000, grid={"CH": 0.09, "IE": 0.26})
    result = evaluate(pick(cat, "M-dp-prod-schedule", "M-vm-test-downsize"), baseline, co2)
    assert result["co2_unknown"] == ["M-dp-prod-schedule"]
    assert result["meets_co2_target"] is True


def test_known_shortfall_does_not_meet_the_co2_target(cat, baseline):
    co2 = Co2Inputs(resource_kg={"vm-test": 100}, total_kg=1_000, grid={"IE": 0.26})
    result = evaluate(pick(cat, "M-vm-test-downsize"), baseline, co2)
    assert result["meets_co2_target"] is False


@pytest.mark.parametrize("cost, co2, expected", [
    (True, True, "met"), (True, None, "pending"), (True, False, "not_met"),
    (False, True, "not_met"), (False, None, "not_met"),
])
def test_package_meets_targets_only_when_both_are_known_to_be_met(cost, co2, expected):
    assert _targets(cost, co2) == expected


def test_template_has_the_submission_columns():
    template = pd.read_csv(DATA_DIR / "template_measures_package.csv", encoding="utf-8-sig", nrows=0)
    assert TEMPLATE_COLUMNS == list(template.columns)
    rows, _, _ = recommend()
    out = to_template(rows)
    assert list(out.columns) == TEMPLATE_COLUMNS
    assert out.loc[out["measure_id"] == "M-dp-prod-schedule", "risks_and_exceptions"].iat[0].count("R0") >= 1


def test_committed_package_is_up_to_date():
    """Fix: cd backend && uv run python -m app.measures.package"""
    rows, _, _ = recommend()
    committed = pd.read_csv(OUTPUT).set_index("measure_id").sort_index()
    expected = to_template(rows).set_index("measure_id").sort_index()
    pd.testing.assert_series_equal(
        committed["savings_cost_chf_per_year"], expected["savings_cost_chf_per_year"], check_dtype=False
    )
