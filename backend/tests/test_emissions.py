from sys import float_info

import pandas as pd
import pytest

from app.pipeline.baseline import select_baseline_facts
from app.pipeline.build import read_facts
from app.pipeline.emissions import calculate_emissions
from app.pipeline.energy import calculate_energy
from app.pipeline.factors import ResearchFactors, load_factors

ENERGY_COLUMNS = ["energy_kwh_low", "energy_kwh_mid", "energy_kwh_high"]
EMISSIONS_COLUMNS = ["co2e_kg_low", "co2e_kg_mid", "co2e_kg_high"]


@pytest.fixture
def factors():
    grid = pd.DataFrame(
        [
            ("grid_mix_location_based_switzerland", "kg CO2 per kWh", 0.125, 0.25, 0.5),
            ("grid_mix_location_based_germany", "kg CO2 per kWh", 0.5, 1.0, 2.0),
            ("grid_mix_location_based_eu", "kg CO2e per kWh", 0.25, 0.5, 1.0),
        ],
        index=pd.Index(["CH", "DE", "EU"], name="location"),
        columns=["parameter", "unit", "value_low", "value_mid", "value_high"],
    )
    return ResearchFactors(energy=pd.DataFrame(), grid=grid, pue=pd.Series(dtype=float))


@pytest.fixture
def energy_facts():
    return pd.DataFrame(
        {
            "location": ["DE", "EU", "CH"],
            "energy_status": "calculated",
            "energy_kwh_low": 4.0,
            "energy_kwh_mid": 8.0,
            "energy_kwh_high": 16.0,
            "cost_chf": [100.0, 25.0, 50.0],
            "note": ["", "known tokens only", ""],
        },
        index=[14, 2, 6],
    )


def test_multiplies_matched_scenarios_and_uses_location(energy_facts, factors):
    result = calculate_emissions(energy_facts, factors).set_index("location")

    assert result.loc["CH", EMISSIONS_COLUMNS].tolist() == [0.5, 2.0, 8.0]
    assert result.loc["DE", EMISSIONS_COLUMNS].tolist() == [2.0, 8.0, 32.0]
    assert result.loc["EU", EMISSIONS_COLUMNS].tolist() == [1.0, 4.0, 16.0]
    assert result["emissions_status"].eq("calculated").all()
    assert result["grid_factor_parameter"].to_dict() == {
        "DE": "grid_mix_location_based_germany",
        "EU": "grid_mix_location_based_eu",
        "CH": "grid_mix_location_based_switzerland",
    }
    assert result["grid_factor_unit"].to_dict() == {
        "DE": "kg CO2 per kWh",
        "EU": "kg CO2e per kWh",
        "CH": "kg CO2 per kWh",
    }


@pytest.mark.parametrize("location", ["unknown", pd.NA])
def test_unknown_location_preserves_calculated_energy(energy_facts, factors, location):
    fact = energy_facts.iloc[[0]].assign(location=location)
    row = calculate_emissions(fact, factors).iloc[0]

    assert row["emissions_status"] == "unknown"
    assert row[EMISSIONS_COLUMNS].isna().all()
    assert row[ENERGY_COLUMNS].tolist() == [4.0, 8.0, 16.0]
    assert pd.isna(row["grid_factor_parameter"])
    assert pd.isna(row["grid_factor_unit"])


@pytest.mark.parametrize("status", ["unknown", "calculated"])
def test_missing_energy_leaves_all_emissions_scenarios_unknown(energy_facts, factors, status):
    fact = energy_facts.iloc[[0]].assign(energy_status=status, energy_kwh_mid=float("nan"))
    row = calculate_emissions(fact, factors).iloc[0]

    assert row["emissions_status"] == "unknown"
    assert row[EMISSIONS_COLUMNS].isna().all()
    assert row["grid_factor_parameter"] == "grid_mix_location_based_germany"


def test_cost_only_credit_preserves_cost_with_missing_emissions(energy_facts, factors):
    fact = energy_facts.iloc[[0]].assign(
        energy_status="cost_only", cost_chf=-25.0, **dict.fromkeys(ENERGY_COLUMNS, float("nan"))
    )
    row = calculate_emissions(fact, factors).iloc[0]

    assert row["emissions_status"] == "cost_only"
    assert row[EMISSIONS_COLUMNS].isna().all()
    assert row["cost_chf"] == -25.0


def test_zero_energy_produces_zero_emissions(energy_facts, factors):
    fact = energy_facts.iloc[[0]].assign(**dict.fromkeys(ENERGY_COLUMNS, 0.0))
    row = calculate_emissions(fact, factors).iloc[0]

    assert row["emissions_status"] == "calculated"
    assert row[EMISSIONS_COLUMNS].tolist() == [0.0, 0.0, 0.0]


def test_preserves_duplicate_index_row_order_and_input(energy_facts, factors):
    facts = energy_facts.set_axis(pd.Index([7, 2, 7], name="fact_index"))
    original = facts.copy()

    result = calculate_emissions(facts, factors)

    pd.testing.assert_frame_equal(result.iloc[:, : len(original.columns)], original)
    assert result["co2e_kg_mid"].tolist() == [8.0, 4.0, 2.0]
    result.iloc[0, result.columns.get_loc("cost_chf")] = 0.0
    pd.testing.assert_frame_equal(facts, original)


def test_rejects_overflow_from_finite_inputs(energy_facts, factors):
    fact = energy_facts.iloc[[0]].assign(energy_kwh_high=float_info.max)

    with pytest.raises(ValueError, match="co2e_kg_high.*finite and nonnegative"):
        calculate_emissions(fact, factors)


def test_real_baseline_preserves_facts_and_has_ordered_emissions_scenarios():
    factors = load_factors()
    baseline = select_baseline_facts(read_facts())
    energy = calculate_energy(baseline, factors)

    result = calculate_emissions(energy, factors)

    pd.testing.assert_frame_equal(result[energy.columns], energy)
    assert len(result) == 698
    assert result["month"].nunique() == 12
    assert result["cost_chf"].sum() == pytest.approx(470300.4703, rel=0, abs=1e-8)
    assert result["emissions_status"].value_counts().to_dict() == {
        "calculated": 468,
        "unknown": 216,
        "cost_only": 14,
    }
    calculated = result["emissions_status"].eq("calculated")
    values = result.loc[calculated, EMISSIONS_COLUMNS]
    assert values.ge(0).all().all()
    assert values.lt(float("inf")).all().all()
    assert values["co2e_kg_low"].le(values["co2e_kg_mid"]).all()
    assert values["co2e_kg_mid"].le(values["co2e_kg_high"]).all()
    assert result.loc[~calculated, EMISSIONS_COLUMNS].isna().all().all()
