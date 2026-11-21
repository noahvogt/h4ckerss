import csv
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from app.pipeline.baseline_export import export_baseline, load_calculated_baseline
from app.pipeline.build import KEY
from app.pipeline.common import DATA_DIR
from app.pipeline.factors import RESEARCH_CSV
from app.pipeline.submission_export import export_submission

FILENAME = "template_baseline_and_assumptions.csv"
TEMPLATE = DATA_DIR / FILENAME
HEADERS = [
    "parameter", "must_or_bonus", "value_low", "value_mid", "value_high",
    "unit", "source", "calculation_or_assumption",
]
SCENARIOS = ("low", "mid", "high")
COST = "total_cost_baseline_year_chf"
ENERGY = "total_energy_baseline_year_kwh"
EMISSIONS = "total_co2_location_based_baseline_year_kg"


@pytest.fixture(scope="module")
def calculated():
    return load_calculated_baseline()


def _read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def _by_parameter(rows):
    return {row["parameter"]: row for row in rows}


def _reject_nonstandard_json(value):
    pytest.fail(f"Nonstandard JSON number: {value}")


def test_official_schema_rows_units_and_provenance(calculated, tmp_path):
    path = export_submission(*calculated, tmp_path)
    headers, rows = _read(path)
    template_headers, template_rows = _read(TEMPLATE)
    research = _by_parameter(_read(RESEARCH_CSV)[1])

    assert path.name == FILENAME
    assert headers == template_headers == HEADERS
    assert len(rows) == len(_by_parameter(rows)) == len(template_rows) == 17
    for row, template in zip(rows, template_rows, strict=True):
        assert all(row[k] == template[k] for k in ("parameter", "must_or_bonus", "unit"))
        key = row["parameter"]
        if row["must_or_bonus"] == "Bonus":
            assert row == template
            continue
        assert row["source"] and row["calculation_or_assumption"]
        if key == "allocation_rule_shared_costs":
            assert "cost center" in row["value_mid"]
            assert "FTE" in row["calculation_or_assumption"]
            assert not row["value_low"] and not row["value_high"]
            continue
        values = [float(row[f"value_{s}"]) for s in SCENARIOS if row[f"value_{s}"]]
        assert values and all(map(math.isfinite, values))
        assert values == sorted(values)
        if key in (COST, ENERGY, EMISSIONS):
            assert len(values) == (1 if key == COST else 3)
            assert "2025-09-01 through 2026-08-31 inclusive" in row["calculation_or_assumption"]
        else:
            assert len(values) == 3
            assert all(float(row[f"value_{s}"]) == float(research[key][f"value_{s}"]) for s in SCENARIOS)
            assert row["source"] == research[key]["source"]
            assert row["calculation_or_assumption"] == research[key]["calculation_or_assumption"]

    by_parameter = _by_parameter(rows)
    assert not by_parameter[COST]["value_low"] and not by_parameter[COST]["value_high"]
    eu = research["grid_mix_location_based_eu"]
    emissions = by_parameter[EMISSIONS]
    assert eu["source"] in emissions["source"]
    assert all(eu[f"value_{s}"] in emissions["calculation_or_assumption"] for s in SCENARIOS)
    assert "kg CO2e per year" in emissions["calculation_or_assumption"]


def test_submission_and_supplementary_artifacts_reconcile(calculated, tmp_path):
    facts, factors = calculated
    official = _by_parameter(_read(export_submission(facts, factors, tmp_path))[1])
    json_path, audit_path = export_baseline(facts, factors, tmp_path)
    data = json.loads(json_path.read_text(), parse_constant=_reject_nonstandard_json)
    annual = data["annual"]

    assert data["period_start"] == "2025-09-01"
    assert data["period_end"] == "2026-08-31"
    assert [row["month"] for row in data["monthly"]] == [
        *(f"2025-{m:02d}-01" for m in range(9, 13)),
        *(f"2026-{m:02d}-01" for m in range(1, 9)),
    ]
    assert annual["fact_count"] == 698
    assert float(official[COST]["value_mid"]) == pytest.approx(470300.4703, abs=1e-8, rel=0)
    assert float(official[COST]["value_mid"]) == annual["cost_chf"]
    metrics = ["cost_chf"]
    for parameter, prefix, metric, mid in (
        (ENERGY, "energy_kwh", "energy", 24185.38),
        (EMISSIONS, "co2e_kg", "emissions", 4203.96),
    ):
        assert float(official[parameter]["value_mid"]) == pytest.approx(mid, abs=0.005, rel=0)
        for s in SCENARIOS:
            column = f"{prefix}_{s}"
            metrics.append(column)
            assert float(official[parameter][f"value_{s}"]) == annual[column]
        assert annual[f"{metric}_coverage"] == "partial"
        for field, count in (
            ("calculated", 468), ("unknown", 216), ("cost_only", 14), ("partial_usage", 183)
        ):
            assert annual[f"{metric}_{field}_count"] == count
        note = official[parameter]["calculation_or_assumption"]
        assert all(token in note for token in ("Known modeled subtotal", "468", "216", "14", "183", "134"))
    assert annual["partial_token_fact_count"] == 134
    assert data["units"] == {"cost_chf": "CHF", "energy_kwh": "kWh", "co2e_kg": "kg CO2e"}

    for grouped in [data["monthly"], data["rows"], *data["breakdowns"].values()]:
        assert sum(row["fact_count"] for row in grouped) == 698
        for metric in metrics:
            assert math.fsum(row[metric] for row in grouped if row[metric] is not None) == pytest.approx(
                annual[metric], rel=0, abs=1e-8
            )

    _, audit = _read(audit_path)
    assert len(audit) == len({tuple(row[k] for k in KEY) for row in audit}) == 698
    for row in audit:
        for metric, prefix in (("energy", "energy_kwh"), ("emissions", "co2e_kg")):
            scenarios = [row[f"{prefix}_{s}"] for s in SCENARIOS]
            if row[f"{metric}_status"] == "calculated":
                values = list(map(float, scenarios))
                assert all(math.isfinite(value) and value >= 0 for value in values)
                assert values == sorted(values)
            else:
                assert scenarios == ["", "", ""]


def test_unavailable_totals_are_blank_and_credit_is_preserved(calculated, tmp_path):
    facts, factors = calculated
    costs_and_unknown = facts.loc[facts["energy_status"].ne("calculated")]
    rows = _by_parameter(_read(export_submission(costs_and_unknown, factors, tmp_path))[1])
    assert float(rows[COST]["value_mid"]) == pytest.approx(costs_and_unknown["cost_chf"].sum())
    for parameter in (ENERGY, EMISSIONS):
        assert [rows[parameter][f"value_{s}"] for s in SCENARIOS] == ["", "", ""]
        assert "unavailable" in rows[parameter]["calculation_or_assumption"]

    credit = facts.loc[facts["energy_status"].eq("cost_only") & facts["cost_chf"].lt(0)].iloc[[0]]
    rows = _by_parameter(_read(export_submission(credit, factors, tmp_path))[1])
    assert float(rows[COST]["value_mid"]) == credit["cost_chf"].item()
    assert rows[ENERGY]["value_mid"] == rows[EMISSIONS]["value_mid"] == ""
    assert "inapplicable" in rows[ENERGY]["calculation_or_assumption"]


def test_repeatable_cli_outputs_and_protects_source_template(calculated, tmp_path):
    facts, factors = calculated
    output = tmp_path / "submission"
    sentinel = output / "measures_package.csv"
    output.mkdir()
    sentinel.write_text("owned elsewhere", encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "app.pipeline.submission_export", "--output-dir", str(output)],
        cwd=Path(__file__).resolve().parents[1],
        check=True, capture_output=True, text=True,
    )
    path = output / FILENAME
    original = path.read_bytes()
    assert export_submission(facts.iloc[::-1], factors, output).read_bytes() == original
    assert sentinel.read_text(encoding="utf-8") == "owned elsewhere"
    template_contents = TEMPLATE.read_bytes()
    with pytest.raises(ValueError, match="source template"):
        export_submission(facts, factors, TEMPLATE.parent)
    assert TEMPLATE.read_bytes() == template_contents
