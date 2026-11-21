import pandas as pd
import pytest

from app.pipeline.factors import (
    COST_ONLY_USAGE_KIND,
    RESEARCH_CSV,
    UNSUPPORTED_USAGE_KINDS,
    load_factors,
)
from app.pipeline.schema import USAGE_KINDS

EXPECTED_FACTOR_UNITS = {
    "vcpu_h": "kWh/vCPU-hour",
    "node_h": "kWh/node-hour",
    "gpu_h": "kWh/GPU-hour",
    "gb_day": "kWh/GB-day",
    "tokens": "kWh/1,000 tokens",
    "messages": "kWh/message",
}


@pytest.fixture
def research():
    rows = [
        ("energy_per_vcpu_hour", 0.01, 0.02, 0.03, "kWh"),
        ("energy_per_node_hour", 0.04, 0.05, 0.06, "kWh"),
        ("energy_per_gpu_hour", 0.07, 0.08, 0.09, "kWh"),
        ("energy_per_gb_storage_day", 0.1, 0.2, 0.3, "kWh"),
        ("energy_per_1000_tokens", 0.4, 0.5, 0.6, "kWh"),
        ("energy_per_subscription_message", 0.7, 0.8, 0.9, "kWh"),
        ("grid_mix_location_based_switzerland", 0.01, 0.02, 0.03, "kg CO2 per kWh"),
        ("grid_mix_location_based_germany", 0.21, 0.22, 0.23, "kg CO2 per kWh"),
        ("grid_mix_location_based_ireland", 0.31, 0.32, 0.33, "kg CO2 per kWh"),
        ("grid_mix_location_based_eu", 0.41, 0.42, 0.43, "kg CO2e per kWh"),
        ("pue", 1.0, 1.2, 1.2, "ratio"),
        ("total_energy_baseline_year_kwh", "", "", "", "kWh per year"),
    ]
    return pd.DataFrame(
        rows, columns=["parameter", "value_low", "value_mid", "value_high", "unit"]
    ).assign(
        must_or_bonus="Must",
        source="Synthetic source, p. 2",
        calculation_or_assumption="Synthetic method",
    )


@pytest.fixture
def load_research(tmp_path):
    def load(frame):
        path = tmp_path / "research.csv"
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        return load_factors(path)

    return load


def test_energy_preserves_research_values_units_and_provenance(research, load_research):
    tokens = load_research(research).energy.loc["tokens"]

    assert tokens["parameter"] == "energy_per_1000_tokens"
    assert tokens[["value_low", "value_mid", "value_high"]].tolist() == [0.4, 0.5, 0.6]
    assert tokens["unit"] == "kWh"
    assert tokens["source"] == "Synthetic source, p. 2"
    assert tokens["calculation_or_assumption"] == "Synthetic method"


def test_energy_factor_metadata_by_usage_kind(research, load_research):
    factors = load_research(research)
    assert factors.energy["usage_divisor"].to_dict() == {
        "vcpu_h": 1, "node_h": 1, "gpu_h": 1, "gb_day": 1, "tokens": 1000, "messages": 1,
    }
    assert factors.energy["factor_unit"].to_dict() == EXPECTED_FACTOR_UNITS
    assert factors.energy["apply_pue"].to_dict() == {
        "vcpu_h": True, "node_h": True, "gpu_h": True, "gb_day": True,
        "tokens": False, "messages": False,
    }
    assert factors.pue["unit"] == "ratio"
    assert factors.pue[["value_low", "value_mid", "value_high"]].tolist() == [1.0, 1.2, 1.2]


def test_grid_intensity_uses_location_codes_and_research_units(research, load_research):
    grid = load_research(research).grid

    assert grid["value_mid"].to_dict() == {"CH": 0.02, "DE": 0.22, "IE": 0.32, "EU": 0.42}
    assert grid.loc["CH", "unit"] == "kg CO2 per kWh"
    assert grid.loc["EU", "unit"] == "kg CO2e per kWh"


def test_distinguishes_unsupported_usage_from_cost_only(research, load_research):
    supported = set(load_research(research).energy.index)
    assert UNSUPPORTED_USAGE_KINDS == {"gb_transfer", "capacity_day", "runner_min", "seat_month"}
    assert COST_ONLY_USAGE_KIND == "none"
    assert supported.isdisjoint(UNSUPPORTED_USAGE_KINDS | {COST_ONLY_USAGE_KIND})
    assert supported | UNSUPPORTED_USAGE_KINDS | {COST_ONLY_USAGE_KIND} == USAGE_KINDS


@pytest.mark.parametrize("parameter", ["energy_per_1000_tokens", "grid_mix_location_based_eu", "pue"])
def test_rejects_missing_required_parameter(research, load_research, parameter):
    with pytest.raises(ValueError, match=f"missing assumptions.*{parameter}"):
        load_research(research.loc[research["parameter"].ne(parameter)])


def test_rejects_duplicate_parameter(research, load_research):
    repeated = pd.concat([research, research.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate parameters.*energy_per_vcpu_hour"):
        load_research(repeated)


def test_rejects_missing_columns(research, load_research):
    with pytest.raises(ValueError, match="missing columns.*value_high"):
        load_research(research.drop(columns="value_high"))


@pytest.mark.parametrize("status", ["Must", "Bonus"])
def test_preserves_documented_requirement_status(research, load_research, status):
    research.loc[research["parameter"].eq("pue"), "must_or_bonus"] = status

    assert load_research(research).pue["must_or_bonus"] == status


@pytest.mark.parametrize(
    ("parameter", "column", "value", "message"),
    [
        ("energy_per_vcpu_hour", "value_mid", "", "finite numbers"),
        ("energy_per_vcpu_hour", "value_mid", "oops", "finite numbers"),
        ("energy_per_vcpu_hour", "value_high", "inf", "finite numbers"),
        ("energy_per_vcpu_hour", "value_mid", 0.05, "low <= mid <= high"),
        ("grid_mix_location_based_eu", "value_mid", 0.4, "low <= mid <= high"),
        ("grid_mix_location_based_eu", "value_low", -0.01, "nonnegative"),
        ("pue", "value_low", 0.9, "at least 1"),
        ("energy_per_1000_tokens", "unit", "Wh", "expected unit"),
        ("grid_mix_location_based_eu", "unit", "g CO2e per kWh", "expected unit"),
        ("energy_per_1000_tokens", "unit", "", "missing unit"),
        ("energy_per_vcpu_hour", "must_or_bonus", "", "missing must_or_bonus"),
        ("grid_mix_location_based_eu", "must_or_bonus", " ", "missing must_or_bonus"),
        ("pue", "must_or_bonus", "", "missing must_or_bonus"),
        ("pue", "must_or_bonus", "Required", "must_or_bonus.*Must.*Bonus"),
        ("energy_per_vcpu_hour", "source", "", "missing source"),
        ("pue", "calculation_or_assumption", " ", "missing calculation_or_assumption"),
    ],
)
def test_rejects_malformed_assumption(research, load_research, parameter, column, value, message):
    research.loc[research["parameter"].eq(parameter), column] = value

    with pytest.raises(ValueError, match=f"{parameter}.*{message}"):
        load_research(research)


def test_loads_real_research_with_all_original_fields_and_scenarios():
    raw = pd.read_csv(RESEARCH_CSV, dtype=str, keep_default_na=False).set_index(
        "parameter", drop=False
    )
    factors = load_factors()

    assert factors.energy["parameter"].to_dict() == {
        "vcpu_h": "energy_per_vcpu_hour",
        "node_h": "energy_per_node_hour",
        "gpu_h": "energy_per_gpu_hour",
        "gb_day": "energy_per_gb_storage_day",
        "tokens": "energy_per_1000_tokens",
        "messages": "energy_per_subscription_message",
    }
    assert factors.energy["factor_unit"].to_dict() == EXPECTED_FACTOR_UNITS
    assert set(factors.grid.index) == {"CH", "DE", "IE", "EU"}
    assert factors.pue["parameter"] == "pue"
    records = [
        *factors.energy.to_dict("records"),
        *factors.grid.to_dict("records"),
        factors.pue.to_dict(),
    ]
    assert len(records) == 11
    scenario_columns = ("value_low", "value_mid", "value_high")
    for record in records:
        original = raw.loc[record["parameter"]]
        for column in scenario_columns:
            assert isinstance(record[column], float)
            assert record[column] == float(original[column])
        for column in ("unit", "must_or_bonus", "source", "calculation_or_assumption"):
            assert record[column] == original[column]
