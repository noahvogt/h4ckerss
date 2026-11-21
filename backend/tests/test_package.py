import pandas as pd
import pytest

from app.measures.catalogue import build_catalogue
from app.measures.package import (
    BUDGET_CHF, CO2_TARGET, OUTPUT, TEMPLATE_COLUMNS, Co2Inputs, _targets, attribute, baseline_cost_chf,
    co2_inputs, eligible, evaluate, recommend, search, sensitivity, to_template,
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


@pytest.fixture(scope="module")
def recommended():
    return recommend()


def test_co2_inputs_come_from_the_baseline_calculation():
    co2 = co2_inputs()
    assert co2.total_kg == pytest.approx(4203.96, abs=0.01)  # = template_baseline_and_assumptions.csv
    assert co2.resource_kg["dp-dev"] == pytest.approx(1303.65, abs=0.01)
    assert co2.grid["DE"] == pytest.approx(0.339236)
    assert pd.isna(co2.resource_kg["saas-other"])  # no energy factor: unknown, not 0
    assert co2.resource_kg["support"] == 0  # only fees: a known 0
    assert not co2.complete()  # partial coverage in #4
    assert sum(v for v in co2.resource_kg.values() if not pd.isna(v)) == pytest.approx(co2.total_kg)


def test_recommended_package_meets_both_targets_within_budget(recommended):
    rows, best, ranked = recommended
    assert best["within_budget"] and best["meets_cost_target"] and best["meets_co2_target"]
    assert best["effort_chf"] <= BUDGET_CHF
    assert best["savings_chf"] == pytest.approx(126_912, abs=1)
    assert best["cost_reduction"] == pytest.approx(0.270, abs=0.001)
    assert best["co2_reduction"] == pytest.approx(0.459, abs=0.001)
    assert best["effort_person_days"] == 15
    assert best["needs_approval"] == [] and best["co2_unknown"] == []
    assert best["targets"] == "met_known_baseline"  # -40 % proven on the known part of the baseline only
    assert "M-dp-dev-relocate" in best["measures"]  # only worth it because of CO2
    assert rows["savings_chf"].sum() == pytest.approx(best["savings_chf"])
    assert rows["savings_co2_kg"].sum() == pytest.approx(best["savings_co2_kg"])
    assert len(ranked) > 1  # alternatives exist for the trade-off view


def test_without_co2_the_package_would_be_chosen_on_chf_only(cat, baseline):
    best = search(cat, baseline).iloc[0]
    assert best["savings_chf"] == pytest.approx(132_850, abs=1) and best["effort_person_days"] == 13
    assert "M-dp-dev-relocate" not in best["measures"] and best["targets"] == "pending"


def test_co2_target_holds_in_all_scenarios(recommended):
    _, best, _ = recommended
    result = sensitivity(best["measures"])
    assert list(result) == ["low", "mid", "high"]
    assert all(r["co2_reduction"] >= CO2_TARGET for r in result.values())
    assert result["high"]["co2_reduction"] == pytest.approx(0.406, abs=0.001)  # the tightest


def test_needs_human_only_in_the_variant_with_approvals(recommended):
    _, safe, _ = recommended
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


@pytest.mark.parametrize("cost, co2, complete, expected", [
    (True, True, True, "met"), (True, True, False, "met_known_baseline"), (True, None, True, "pending"),
    (True, False, True, "not_met"), (False, True, True, "not_met"), (False, None, False, "not_met"),
])
def test_package_meets_targets_only_when_both_are_known_to_be_met(cost, co2, complete, expected):
    assert _targets(cost, co2, complete) == expected


DP_DEV = {"dp-dev": 10_000}
GRID = {"CH": 0.09, "DE": 0.34}


@pytest.mark.parametrize("complete, kg, expected", [
    (False, DP_DEV, "met_known_baseline"),  # default: a partial baseline proves nothing for the company
    (True, DP_DEV, "met"),
    (True, DP_DEV | {"saas-other": float("nan")}, "met_known_baseline"),  # unknown part: not complete
])
def test_co2_target_is_proven_only_on_a_complete_baseline(cat, baseline, complete, kg, expected):
    co2 = Co2Inputs(resource_kg=kg, total_kg=10_000, grid=GRID, baseline_complete=complete)
    # every allowed measure: enough CHF; dp-dev pause + relocate save far more than 40 % of 10 t
    result = evaluate(eligible(cat), baseline, co2)
    assert result["meets_co2_target"] is True and result["targets"] == expected


def test_zero_start_grid_does_not_divide_by_zero(cat, baseline):
    both = pick(cat, "M-dp-dev-pause", "M-dp-dev-relocate")
    zero = {"CH": 0.09, "DE": 0.0}
    rows = attribute(both, Co2Inputs(resource_kg={"dp-dev": 0.0}, total_kg=1_000, grid=zero)).set_index("measure_id")
    assert rows.loc["M-dp-dev-pause", "savings_co2_kg"] == 0  # same grid: share of the baseline kg
    assert pd.isna(rows.loc["M-dp-dev-relocate", "savings_co2_kg"])  # kWh not derivable from 0 kg / 0
    # with kWh known the relocation can be computed: moving to a dirtier grid costs CO2
    with_kwh = Co2Inputs(resource_kg={"dp-dev": 0.0}, total_kg=1_000, grid=zero, resource_kwh={"dp-dev": 1_000})
    pause = cat.set_index("measure_id").loc["M-dp-dev-pause", "usage_factor"]
    moved = attribute(both, with_kwh).set_index("measure_id").loc["M-dp-dev-relocate", "savings_co2_kg"]
    assert moved == pytest.approx(-1_000 * pause * 0.09)


def test_relocation_uses_kwh_when_known_and_agrees_with_kg(cat, baseline):
    both = pick(cat, "M-dp-dev-pause", "M-dp-dev-relocate")
    from_kg = evaluate(both, baseline, Co2Inputs(resource_kg=DP_DEV, total_kg=20_000, grid=GRID))
    from_kwh = evaluate(both, baseline, Co2Inputs(resource_kg=DP_DEV, total_kg=20_000, grid=GRID,
                                                  resource_kwh={"dp-dev": 10_000 / 0.34}))
    assert from_kwh["savings_co2_kg"] == pytest.approx(from_kg["savings_co2_kg"])


def test_zero_co2_baseline_leaves_the_target_undecided(cat, baseline):
    co2 = Co2Inputs(resource_kg={"vm-test": 0.0}, total_kg=0.0, grid={"IE": 0.26})
    result = evaluate(pick(cat, "M-vm-test-downsize"), baseline, co2)
    assert result["co2_reduction"] is None and result["meets_co2_target"] is None


def test_template_has_the_submission_columns(recommended):
    template = pd.read_csv(DATA_DIR / "template_measures_package.csv", encoding="utf-8-sig", nrows=0)
    assert TEMPLATE_COLUMNS == list(template.columns)
    rows, best, _ = recommended
    out = to_template(rows).set_index("measure_id")
    assert list(out.reset_index().columns) == TEMPLATE_COLUMNS
    assert out.loc["M-dp-prod-schedule", "risks_and_exceptions"].count("R0") >= 1
    # kWh and CO2 filled: usage measures save both, a relocation only CO2, seats nothing
    assert out.loc["M-dp-dev-pause", ["savings_energy_kwh_per_year", "savings_co2_kg_location_based"]].gt(0).all()
    assert out.loc["M-dp-dev-relocate", "savings_energy_kwh_per_year"] == 0
    assert out.loc["M-dp-dev-relocate", "savings_co2_kg_location_based"] > 0
    assert out.loc["M-saas-other", ["savings_energy_kwh_per_year", "savings_co2_kg_location_based"]].eq(0).all()
    assert "no change in energy use" in out.loc["M-saas-other", "assumptions_and_sources"]
    assert out["savings_co2_kg_location_based"].sum() == pytest.approx(best["savings_co2_kg"], abs=len(out))


def test_committed_package_is_up_to_date(recommended):
    """Fix: cd backend && uv run python -m app.measures.package"""
    rows, _, _ = recommended
    committed = pd.read_csv(OUTPUT).set_index("measure_id").sort_index()
    expected = to_template(rows).set_index("measure_id").sort_index()
    columns = ["effort_person_days", "savings_cost_chf_per_year", "savings_energy_kwh_per_year",
               "savings_co2_kg_location_based"]
    pd.testing.assert_frame_equal(committed[columns], expected[columns], check_dtype=False)
