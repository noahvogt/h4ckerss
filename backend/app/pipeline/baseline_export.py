"""Export the calculated baseline for the map overview and for fact audits."""

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.pipeline.baseline import select_baseline_facts
from app.pipeline.build import BASELINE, KEY, OUTPUT, read_facts
from app.pipeline.emissions import calculate_emissions
from app.pipeline.energy import calculate_energy
from app.pipeline.factors import ResearchFactors, load_factors
from app.pipeline.summary import rank_drivers, summarize_baseline

DEFAULT_OUTPUT_DIR = OUTPUT.parents[2] / "out" / "baseline"
JSON_FILENAME = "baseline.json"
DETAILS_FILENAME = "baseline_details.csv"
_SCENARIOS = ("low", "mid", "high")
_DEFAULT_SCENARIO = "mid"
_BREAKDOWNS = ("location", "department", "tool", "category")
_DRIVER_DIMENSIONS = ("resource_id", "department", "tool", "location")
_DRIVER_LIMIT = 10
_UNITS = {"cost_chf": "CHF", "energy_kwh": "kWh", "co2e_kg": "kg CO2e"}
_PROVENANCE = ["source", "calculation_or_assumption"]
_FACTOR_FIELDS = [*(f"value_{s}" for s in _SCENARIOS), *_PROVENANCE]
_DETAIL_COVERAGE = [
    "cost_coverage", "energy_coverage", "emissions_coverage",
    "partial_token_fact_count", "energy_partial_usage_count", "emissions_partial_usage_count",
]


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "month" in frame:
        frame = frame.assign(month=frame["month"].dt.strftime("%Y-%m-%d"))
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def build_baseline_payload(facts: pd.DataFrame) -> dict[str, Any]:
    """Build JSON from calculated facts selected by select_baseline_facts().

    Callers must supply unique baseline fact keys, as enforced by the selector.
    """
    facts = facts.sort_values(KEY, ignore_index=True)
    annual = _records(summarize_baseline(facts))
    map_rows = summarize_baseline(facts, by=_BREAKDOWNS).assign(
        energy_kwh=lambda frame: frame[f"energy_kwh_{_DEFAULT_SCENARIO}"],
        co2_kg=lambda frame: frame[f"co2e_kg_{_DEFAULT_SCENARIO}"],
    )
    return {
        "schema_version": 1,
        "period_start": BASELINE[0].date().isoformat(),
        "period_end": (BASELINE[1] + pd.offsets.MonthEnd(0)).date().isoformat(),
        "illustrative": False,
        "scenarios": list(_SCENARIOS),
        "default_scenario": _DEFAULT_SCENARIO,
        "units": _UNITS.copy(),
        "annual": annual[0] if annual else None,
        "monthly": _records(summarize_baseline(facts, by="month")),
        "breakdowns": {
            by: _records(summarize_baseline(facts, by=by)) for by in _BREAKDOWNS
        },
        "drivers": {
            metric: {
                by: _records(rank_drivers(facts, by=by, metric=metric, limit=_DRIVER_LIMIT))
                for by in _DRIVER_DIMENSIONS
            }
            for metric in _UNITS
        },
        "rows": _records(map_rows),
        "details_file": DETAILS_FILENAME,
    }


def build_audit_details(facts: pd.DataFrame, factors: ResearchFactors) -> pd.DataFrame:
    """Append operands and provenance to calculated, validated baseline facts.

    The coverage join requires one row per baseline fact key.
    """
    facts = facts.sort_values(KEY, ignore_index=True)
    coverage = summarize_baseline(facts, by=KEY).set_index(KEY)[_DETAIL_COVERAGE]
    details = facts.join(coverage, on=KEY, validate="one_to_one")
    energy = factors.energy.set_index("parameter")[["usage_divisor", "unit", *_FACTOR_FIELDS]]
    energy = energy.rename(columns={"unit": "research_unit"})
    grid = factors.grid.set_index("parameter")[_FACTOR_FIELDS]
    details = details.join(energy.add_prefix("energy_factor_"), on="energy_factor_parameter")
    details = details.join(grid.add_prefix("grid_factor_"), on="grid_factor_parameter")

    apply_pue = details["energy_apply_pue"].astype("boolean")
    multiplier = pd.Series(1.0, index=details.index).where(apply_pue.notna())
    for scenario in _SCENARIOS:
        details[f"pue_multiplier_{scenario}"] = multiplier.mask(
            apply_pue.fillna(False), factors.pue[f"value_{scenario}"]
        )
    for field in ("parameter", "unit", *_PROVENANCE):
        details[f"pue_{field}"] = pd.Series(factors.pue[field], index=details.index).where(
            apply_pue.fillna(False)
        )
    return details


def export_baseline(
    facts: pd.DataFrame, factors: ResearchFactors, output_dir: Path = DEFAULT_OUTPUT_DIR
) -> tuple[Path, Path]:
    """Write both files from calculated facts selected by select_baseline_facts().

    Fact keys must be unique. The audit join checks this before either file is written.
    """
    payload = json.dumps(build_baseline_payload(facts), ensure_ascii=False, allow_nan=False, indent=2)
    details = build_audit_details(facts, factors)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_FILENAME
    csv_path = output_dir / DETAILS_FILENAME
    json_path.write_text(payload + "\n", encoding="utf-8", newline="\n")
    details.to_csv(csv_path, index=False, date_format="%Y-%m-%d", lineterminator="\n")
    return json_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    baseline = select_baseline_facts(read_facts())
    factors = load_factors()
    facts = calculate_emissions(calculate_energy(baseline, factors), factors)
    for path in export_baseline(facts, factors, args.output_dir):
        print(f"written: {path}")


if __name__ == "__main__":
    main()
