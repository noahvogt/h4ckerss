import csv
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from app.pipeline.baseline import select_baseline_facts
from app.pipeline.baseline_export import build_baseline_payload, export_baseline
from app.pipeline.build import KEY, read_facts
from app.pipeline.emissions import calculate_emissions
from app.pipeline.energy import calculate_energy
from app.pipeline.factors import load_factors
from app.pipeline.schema import validate

METRICS = [
    "cost_chf",
    "energy_kwh_low", "energy_kwh_mid", "energy_kwh_high",
    "co2e_kg_low", "co2e_kg_mid", "co2e_kg_high",
]


@pytest.fixture(scope="module")
def factors():
    return load_factors()


@pytest.fixture
def facts(factors):
    baseline = validate(pd.DataFrame({
        "month": ["2025-10-01", "2025-09-01", "2025-09-01", "2025-10-01", "2025-09-01"],
        "category": ["server", "server", "saas", "ai", "server"],
        "source": ["azure_costs.csv", "azure_costs.csv", "saas_contracts.csv", "ai_usage.csv", "aws_costs.csv"],
        "resource_id": ["vm-app", "vm-app", "saas-other", "ai-assistant", "vm-test"],
        "tool": ["App server", "App server", "Other SaaS contracts", "Office AI assistant", "Test environments"],
        "department": ["IT", "IT", "Sales", "IT", "IT"],
        "cost_center": ["4500", "4500", "4100", "4500", "4500"],
        "location": ["CH", "CH", "EU", "EU", "unknown"],
        "usage_kind": ["vcpu_h", "none", "seat_month", "tokens", "vcpu_h"],
        "usage_qty": [0, 0, 4, 1000, 8],
        "cost_chf": [100, -25, 50, 10, None],
        "note": ["", "SLA credit", "", "incomplete token usage; known tokens only", "missing cost"],
    }))
    return calculate_emissions(calculate_energy(baseline, factors), factors)


def _reject_nonstandard_json(value):
    raise AssertionError(f"Invalid JSON numeric value: {value}")


def test_json_contract_and_months(facts, factors, tmp_path):
    json_path, csv_path = export_baseline(facts, factors, tmp_path)
    data = json.loads(json_path.read_text(), parse_constant=_reject_nonstandard_json)

    assert data["schema_version"] == 1
    assert data["period_start"] == "2025-09-01"
    assert data["period_end"] == "2026-08-31"
    assert data["illustrative"] is False
    assert data["scenarios"] == ["low", "mid", "high"]
    assert data["default_scenario"] == "mid"
    assert data["units"] == {"cost_chf": "CHF", "energy_kwh": "kWh", "co2e_kg": "kg CO2e"}
    assert data["details_file"] == csv_path.name == "baseline_details.csv"
    assert [row["month"] for row in data["monthly"]] == ["2025-09-01", "2025-10-01"]
    assert set(data["breakdowns"]) == {"location", "department", "tool", "category"}
    assert set(data["drivers"]) == {"cost_chf", "energy_kwh", "co2e_kg"}
    assert all(
        set(ranks) == {"resource_id", "department", "tool", "location"}
        for ranks in data["drivers"].values()
    )
    assert all("energy_coverage" in row and "emissions_coverage" in row for row in data["rows"])


def test_zero_unknown_and_inapplicable_survive_json(facts, factors, tmp_path):
    path, _ = export_baseline(facts, factors, tmp_path)
    data = json.loads(path.read_text(), parse_constant=_reject_nonstandard_json)
    rows = {row["tool"]: row for row in data["rows"]}

    assert rows["App server"]["cost_chf"] == 75
    assert rows["App server"]["energy_kwh"] == rows["App server"]["co2_kg"] == 0
    assert rows["App server"]["energy_coverage"] == "complete"
    assert rows["App server"]["energy_cost_only_count"] == 1
    assert rows["Other SaaS contracts"]["energy_kwh"] is None
    assert rows["Other SaaS contracts"]["energy_coverage"] == "unavailable"

    unlocated = rows["Test environments"]
    assert unlocated["cost_chf"] is None
    assert unlocated["energy_kwh"] > 0
    assert unlocated["co2_kg"] is None
    assert (
        unlocated["cost_coverage"], unlocated["energy_coverage"], unlocated["emissions_coverage"]
    ) == ("unavailable", "complete", "unavailable")
    credit = data["monthly"][0]
    assert credit["energy_cost_only_count"] == 1
    assert data["annual"]["partial_token_fact_count"] == 1

    cost_only = build_baseline_payload(facts.loc[facts["energy_status"].eq("cost_only")])["annual"]
    assert cost_only["cost_chf"] == -25
    assert cost_only["energy_kwh_mid"] is cost_only["co2e_kg_mid"] is None
    assert cost_only["energy_coverage"] == cost_only["emissions_coverage"] == "inapplicable"


def test_csv_preserves_facts_and_factor_provenance(facts, factors, tmp_path):
    _, path = export_baseline(facts, factors, tmp_path)
    actual = pd.read_csv(path, keep_default_na=False, dtype=str)
    expected = facts.sort_values(KEY, ignore_index=True)
    expected = expected.assign(month=expected["month"].dt.strftime("%Y-%m-%d"))
    pd.testing.assert_frame_equal(
        actual[facts.columns], expected.astype("string").fillna("").astype(str),
        check_dtype=False,
    )
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    ai = next(row for row in rows if row["usage_kind"] == "tokens")
    assert ai["energy_factor_source"] == factors.energy.loc["tokens", "source"]
    assert ai["energy_factor_calculation_or_assumption"] == factors.energy.loc["tokens", "calculation_or_assumption"]
    assert float(ai["energy_factor_usage_divisor"]) == 1000
    assert float(ai["energy_factor_value_mid"]) == factors.energy.loc["tokens", "value_mid"]
    assert ai["grid_factor_source"] == factors.grid.loc["EU", "source"]
    assert float(ai["grid_factor_value_mid"]) == factors.grid.loc["EU", "value_mid"]
    assert float(ai["pue_multiplier_mid"]) == 1
    assert ai["energy_coverage"] == ai["emissions_coverage"] == "partial"
    server = next(row for row in rows if row["location"] == "CH" and row["usage_kind"] == "vcpu_h")
    assert server["grid_factor_unit"] == "kg CO2 per kWh"
    assert float(server["pue_multiplier_mid"]) == factors.pue["value_mid"]
    assert server["pue_source"] == factors.pue["source"]
    credit = next(row for row in rows if row["energy_status"] == "cost_only")
    assert credit["energy_kwh_mid"] == credit["co2e_kg_mid"] == ""
    assert credit["energy_coverage"] == credit["emissions_coverage"] == "inapplicable"


def test_exports_are_repeatable_and_leave_inputs_unchanged(facts, factors, tmp_path):
    original = facts.copy(deep=True)
    original_factors = [part.copy(deep=True) for part in factors]
    paths = export_baseline(facts, factors, tmp_path)
    first = [path.read_bytes() for path in paths]
    export_baseline(facts.iloc[::-1], factors, tmp_path)

    assert [path.read_bytes() for path in paths] == first
    pd.testing.assert_frame_equal(facts, original)
    pd.testing.assert_frame_equal(factors.energy, original_factors[0])
    pd.testing.assert_frame_equal(factors.grid, original_factors[1])
    pd.testing.assert_series_equal(factors.pue, original_factors[2])


def test_export_rejects_infinite_values_before_writing(facts, factors, tmp_path):
    invalid = facts.iloc[[0]].assign(cost_chf=float("inf"))

    with pytest.raises(ValueError, match="Out of range float values"):
        export_baseline(invalid, factors, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_real_cli_exports_reconcile(tmp_path, factors):
    output = tmp_path / "baseline"
    subprocess.run(
        [sys.executable, "-m", "app.pipeline.baseline_export", "--output-dir", str(output)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads((output / "baseline.json").read_text(), parse_constant=_reject_nonstandard_json)
    annual = data["annual"]

    assert annual["fact_count"] == 698
    assert len(data["monthly"]) == 12
    assert annual["cost_chf"] == pytest.approx(470300.4703, rel=0, abs=1e-8)
    assert annual["energy_kwh_mid"] == pytest.approx(24185.38, rel=0, abs=0.005)
    assert annual["co2e_kg_mid"] == pytest.approx(4203.96, rel=0, abs=0.005)
    for metric in ("energy", "emissions"):
        assert annual[f"{metric}_calculated_count"] == 468
        assert annual[f"{metric}_unknown_count"] == 216
        assert annual[f"{metric}_cost_only_count"] == 14
        assert annual[f"{metric}_partial_usage_count"] == 183
        assert annual[f"{metric}_coverage"] == "partial"
    assert annual["partial_token_fact_count"] == 134
    for grouping in [data["monthly"], data["rows"], *data["breakdowns"].values()]:
        assert sum(row["fact_count"] for row in grouping) == 698
        for metric in METRICS:
            assert sum(row[metric] for row in grouping if row[metric] is not None) == pytest.approx(annual[metric])
    assert all(row["energy_kwh"] == row["energy_kwh_mid"] and row["co2_kg"] == row["co2e_kg_mid"] for row in data["rows"])

    expected = calculate_emissions(calculate_energy(select_baseline_facts(read_facts()), factors), factors)
    details = pd.read_csv(
        output / data["details_file"],
        parse_dates=["month"],
        dtype=expected.dtypes.drop("month").to_dict(),
    )
    details["month"] = details["month"].astype(expected["month"].dtype)
    pd.testing.assert_frame_equal(
        details[expected.columns].fillna({"note": ""}),
        expected.sort_values(KEY, ignore_index=True),
        check_exact=False,
        rtol=1e-14,
        atol=0,
    )
