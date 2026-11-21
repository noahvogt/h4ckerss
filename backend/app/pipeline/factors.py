"""Load the researched factors and their units for baseline calculations."""

from math import isfinite
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from app.pipeline.common import DATA_DIR
from app.pipeline.schema import USAGE_KINDS

RESEARCH_CSV = DATA_DIR.parents[1] / "submission" / "research_baseline_and_assumptions.csv"

# usage kind -> (research parameter, usage divisor, factor unit, apply PUE)
_ENERGY = {
    "vcpu_h": ("energy_per_vcpu_hour", 1, "kWh/vCPU-hour", True),
    "node_h": ("energy_per_node_hour", 1, "kWh/node-hour", True),
    "gpu_h": ("energy_per_gpu_hour", 1, "kWh/GPU-hour", True),
    "gb_day": ("energy_per_gb_storage_day", 1, "kWh/GB-day", True),
    "tokens": ("energy_per_1000_tokens", 1000, "kWh/1,000 tokens", False),
    "messages": ("energy_per_subscription_message", 1, "kWh/message", False),
}
_GRID = {
    "CH": "grid_mix_location_based_switzerland",
    "DE": "grid_mix_location_based_germany",
    "IE": "grid_mix_location_based_ireland",
    "EU": "grid_mix_location_based_eu",
}
COST_ONLY_USAGE_KIND = "none"
UNSUPPORTED_USAGE_KINDS = frozenset(USAGE_KINDS - _ENERGY.keys() - {COST_ONLY_USAGE_KIND})

_VALUES = ["value_low", "value_mid", "value_high"]
_PROVENANCE = ["source", "calculation_or_assumption"]
_COLUMNS = ["parameter", "must_or_bonus", *_VALUES, "unit", *_PROVENANCE]


class ResearchFactors(NamedTuple):
    """Energy by usage kind, grid intensity by location, and the PUE row.

    Values are deterministic sensitivity scenarios with no statistical
    confidence interpretation. Use value_mid as the display default and
    value_low and value_high for the sensitivity range.

    Energy factor_unit describes the original value per usage_divisor raw units.
    apply_pue tells the future calculation whether to apply facility overhead.

    Grid unit stores the research CSV label. CH, DE and IE retain the template
    label "kg CO2 per kWh" and document a CO2e basis. EU already uses "kg CO2e
    per kWh". Use the documented CO2e basis for display.
    """

    energy: pd.DataFrame
    grid: pd.DataFrame
    pue: pd.Series


def load_factors(path: str | Path = RESEARCH_CSV) -> ResearchFactors:
    """Read required research rows without rescaling their scenario values."""
    rows = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    missing_columns = sorted(set(_COLUMNS) - set(rows.columns))
    if missing_columns:
        raise ValueError(f"{path}: missing columns: {missing_columns}")
    duplicates = rows.loc[rows["parameter"].duplicated(), "parameter"].unique()
    if len(duplicates):
        raise ValueError(f"{path}: duplicate parameters: {duplicates.tolist()}")

    units = {
        **{parameter: "kWh" for parameter, *_ in _ENERGY.values()},
        **dict.fromkeys(_GRID.values(), "kg CO2 per kWh"),
        _GRID["EU"]: "kg CO2e per kWh",
        "pue": "ratio",
    }
    missing_parameters = sorted(set(units) - set(rows["parameter"]))
    if missing_parameters:
        raise ValueError(f"{path}: missing assumptions: {missing_parameters}")

    assumptions = rows.set_index("parameter").loc[list(units), _COLUMNS[1:]]
    values = assumptions[_VALUES].apply(pd.to_numeric, errors="coerce").astype(float)
    for parameter, unit in units.items():
        label = f"{path}: {parameter}"
        row = assumptions.loc[parameter]
        for column in ("must_or_bonus", "unit", *_PROVENANCE):
            if not row[column].strip():
                raise ValueError(f"{label}: missing {column}")
        if row["must_or_bonus"] not in {"Must", "Bonus"}:
            raise ValueError(f"{label}: must_or_bonus must be 'Must' or 'Bonus'")
        if row["unit"] != unit:
            raise ValueError(f"{label}: expected unit {unit!r}, got {row['unit']!r}")

        low, mid, high = values.loc[parameter]
        if not all(map(isfinite, (low, mid, high))):
            raise ValueError(f"{label}: value_low, value_mid and value_high must be finite numbers")
        if not low <= mid <= high:
            raise ValueError(f"{label}: expected low <= mid <= high")
        if parameter == "pue" and low < 1:
            raise ValueError(f"{label}: PUE must be at least 1")
        if low < 0:
            raise ValueError(f"{label}: values must be nonnegative")

    assumptions = assumptions.assign(**values)
    energy = pd.DataFrame.from_dict(
        _ENERGY,
        orient="index",
        columns=["parameter", "usage_divisor", "factor_unit", "apply_pue"],
    ).rename_axis("usage_kind")
    grid = pd.Series(_GRID, name="parameter").rename_axis("location").to_frame()
    pue = assumptions.loc["pue"].copy()
    pue["parameter"] = pue.name
    return ResearchFactors(
        energy=energy.join(assumptions, on="parameter"),
        grid=grid.join(assumptions, on="parameter"),
        pue=pue,
    )
