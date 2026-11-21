"""Fill ALTYCA's official baseline and assumptions template."""

import argparse
import csv
from math import isfinite
from pathlib import Path

import pandas as pd

from app.pipeline.baseline_export import load_calculated_baseline
from app.pipeline.build import BASELINE, KEY
from app.pipeline.common import DATA_DIR
from app.pipeline.factors import RESEARCH_CSV, ResearchFactors
from app.pipeline.summary import summarize_baseline

TEMPLATE = DATA_DIR / "template_baseline_and_assumptions.csv"
SUBMISSION_DIR = RESEARCH_CSV.parent
_SCENARIOS = ("low", "mid", "high")
_VALUE_FIELDS = [f"value_{s}" for s in _SCENARIOS]
_INPUTS = "data/derived/facts.csv; submission/research_baseline_and_assumptions.csv"


def _number(value: float) -> float | str:
    if pd.isna(value):
        return ""
    if not isfinite(value):
        raise ValueError("Non-finite value in baseline submission")
    return float(value)


def _physical_coverage(annual: pd.Series, metric: str) -> str:
    return (
        f"Known modeled subtotal. Coverage is {annual[f'{metric}_coverage']}: "
        f"{annual[f'{metric}_calculated_count']} calculated, "
        f"{annual[f'{metric}_unknown_count']} unknown, "
        f"{annual[f'{metric}_cost_only_count']} cost-only. "
        f"{annual[f'{metric}_partial_usage_count']} calculated facts have flagged partial usage. "
        f"The baseline includes {annual['partial_token_fact_count']} partial-token facts. "
        "The subtotal covers reported activity with supported factors. "
        "Unavailable amounts are blank."
    )


def export_submission(
    facts: pd.DataFrame, factors: ResearchFactors, output_dir: Path = SUBMISSION_DIR
) -> Path:
    """Fill the official CSV from the shared calculated facts and research factors."""
    path = output_dir / TEMPLATE.name
    if path.resolve() == TEMPLATE.resolve() or path.is_symlink():
        raise ValueError("Cannot overwrite the source template or write through a symlink")

    with TEMPLATE.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers, rows = reader.fieldnames, list(reader)

    annual = summarize_baseline(facts.sort_values(KEY, ignore_index=True)).iloc[0]
    assumptions = {
        row["parameter"]: row
        for row in (
            *factors.energy.to_dict("records"),
            *factors.grid.to_dict("records"),
            factors.pue.to_dict(),
        )
    }
    eu = factors.grid.loc["EU"]
    eu_values = " / ".join(str(eu[field]) for field in _VALUE_FIELDS)
    end = BASELINE[1] + pd.offsets.MonthEnd(0)
    period = f"{BASELINE[0]:%Y-%m-%d} through {end:%Y-%m-%d} inclusive."

    totals = {
        "total_cost_baseline_year_chf": {
            "value_mid": _number(annual["cost_chf"]),
            "source": _INPUTS,
            "calculation_or_assumption": (
                f"{period} Sum of recorded CHF costs after ingestion and currency conversion, "
                "including signed credits. Cost has a single estimate. "
                f"Coverage is {annual['cost_coverage']} with "
                f"{annual['cost_known_count']} known and {annual['cost_unknown_count']} missing amounts."
            ),
        },
        "total_energy_baseline_year_kwh": {
            **{f"value_{s}": _number(annual[f"energy_kwh_{s}"]) for s in _SCENARIOS},
            "source": _INPUTS,
            "calculation_or_assumption": (
                f"{period} Sum of facility electricity estimates in kWh with PUE applied where required. "
                + _physical_coverage(annual, "energy")
            ),
        },
        "total_co2_location_based_baseline_year_kg": {
            **{f"value_{s}": _number(annual[f"co2e_kg_{s}"]) for s in _SCENARIOS},
            "source": f"{_INPUTS}; EU mixed grid: {eu['source']}",
            "calculation_or_assumption": (
                f"{period} Sum of facility kWh multiplied by the matching location and scenario intensity. "
                "The emissions basis is kg CO2e per year. "
                f"{_physical_coverage(annual, 'emissions')} "
                f"EU mixed grid low / mid / high: {eu_values} {eu['unit']}. "
                f"{eu['calculation_or_assumption']}"
            ),
        },
        "allocation_rule_shared_costs": {
            "value_mid": (
                "Keep the department attribution in the baseline facts, including "
                "subscription allocations by source cost center."
            ),
            "source": "data/provided/mapping_departments_tools.csv; docs/data_decisions.md",
            "calculation_or_assumption": (
                "Cloud and hoster billing use the master resource mapping. Subscription department "
                "attribution follows each source cost center. Gateway usage follows source departments. "
                "The baseline retains existing Overhead and Unallocated attribution. "
                "The proposed FTE redistribution has not been applied."
            ),
        },
    }
    for row in rows:
        parameter = row["parameter"]
        if row["must_or_bonus"] == "Bonus":
            continue
        if parameter in totals:
            row.update(totals[parameter])
            continue
        factor = assumptions[parameter]
        if row["unit"] != factor["unit"]:
            raise ValueError(f"Template unit differs from the research unit for {parameter}")
        row.update({field: _number(factor[field]) for field in _VALUE_FIELDS})
        row.update({field: factor[field] for field in ("source", "calculation_or_assumption")})

    output_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=SUBMISSION_DIR)
    args = parser.parse_args()

    print(f"written: {export_submission(*load_calculated_baseline(), args.output_dir)}")


if __name__ == "__main__":
    main()
