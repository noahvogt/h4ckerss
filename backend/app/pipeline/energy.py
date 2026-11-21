"""Estimate facility energy for each validated monthly baseline fact."""

import pandas as pd

from app.pipeline.factors import COST_ONLY_USAGE_KIND, ResearchFactors


def calculate_energy(baseline: pd.DataFrame, factors: ResearchFactors) -> pd.DataFrame:
    """Append scenario energy and factor metadata in the original fact order.

    Missing, nonnumeric, negative, or non-finite usage leaves energy unknown.
    A valid zero quantity yields zero energy. For partial source usage, the
    estimate uses the available quantity and retains the original source note.

    Use factors from load_factors() or satisfy its invariants, including unique
    usage kinds, positive divisors, boolean PUE flags, and finite, nonnegative,
    ordered factor values with PUE at least 1. An invalid calculated result,
    such as floating-point overflow, raises ValueError.
    """
    usage_kind = baseline["usage_kind"]
    matched = factors.energy.reindex(usage_kind).set_axis(baseline.index)
    usage = pd.to_numeric(baseline["usage_qty"], errors="coerce")
    cost_only = usage_kind.eq(COST_ONLY_USAGE_KIND).fillna(False)
    valid_usage = usage.ge(0) & usage.lt(float("inf"))
    calculated = matched["parameter"].notna() & ~cost_only & valid_usage
    calculated = calculated.fillna(False)

    quantity = usage.where(calculated) / matched["usage_divisor"]
    apply_pue = matched["apply_pue"].astype("boolean")
    unit_multiplier = pd.Series(1.0, index=baseline.index)
    result = baseline.copy()
    for scenario in ("low", "mid", "high"):
        value = f"value_{scenario}"
        multiplier = unit_multiplier.mask(apply_pue.fillna(False), factors.pue[value])
        energy = quantity * matched[value] * multiplier
        column = f"energy_kwh_{scenario}"
        valid_energy = energy.loc[calculated].between(0, float("inf"), inclusive="left")
        if not valid_energy.fillna(False).all():
            raise ValueError(f"{column} must be finite and nonnegative for calculated facts")
        result[column] = energy

    status = pd.Series("unknown", index=baseline.index, dtype="string")
    result["energy_status"] = status.mask(cost_only, "cost_only").mask(calculated, "calculated")
    result["energy_factor_parameter"] = matched["parameter"].astype("string")
    result["energy_factor_unit"] = matched["factor_unit"].astype("string")
    result["energy_apply_pue"] = apply_pue
    return result
