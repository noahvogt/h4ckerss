"""Estimate location-based CO₂e emissions for each monthly baseline fact."""

import pandas as pd

from app.pipeline.factors import ResearchFactors


def calculate_emissions(energy_facts: pd.DataFrame, factors: ResearchFactors) -> pd.DataFrame:
    """Append kg CO₂e and preserve the original grid factor parameter and unit.

    Use energy facts from calculate_energy() and validated grid factors from
    load_factors(). A missing location match or any unavailable energy scenario
    leaves all three emissions estimates unknown. Cost-only rows stay cost-only.
    """
    scenarios = ("low", "mid", "high")
    energy = energy_facts[[f"energy_kwh_{s}" for s in scenarios]].apply(
        pd.to_numeric, errors="coerce"
    )
    grid = factors.grid.reindex(energy_facts["location"]).set_axis(energy_facts.index)
    energy_status = energy_facts["energy_status"]
    cost_only = energy_status.eq("cost_only").fillna(False)
    valid_energy = (energy.ge(0) & energy.lt(float("inf"))).fillna(False).all(axis=1)
    calculated = (
        energy_status.eq("calculated").fillna(False) & grid["parameter"].notna() & valid_energy
    )

    result = energy_facts.copy()
    for scenario in scenarios:
        co2e = energy[f"energy_kwh_{scenario}"].where(calculated) * grid[f"value_{scenario}"]
        column = f"co2e_kg_{scenario}"
        valid_co2e = co2e.loc[calculated].between(0, float("inf"), inclusive="left")
        if not valid_co2e.fillna(False).all():
            raise ValueError(f"{column} must be finite and nonnegative for calculated facts")
        result[column] = co2e

    status = pd.Series("unknown", index=energy_facts.index, dtype="string")
    result["emissions_status"] = status.mask(cost_only, "cost_only").mask(calculated, "calculated")
    result["grid_factor_parameter"] = grid["parameter"].astype("string")
    result["grid_factor_unit"] = grid["unit"].astype("string")
    return result
