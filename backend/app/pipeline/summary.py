"""Aggregate baseline facts and rank drivers by their known subtotals."""

from collections.abc import Sequence

import pandas as pd

_RANK_DIMENSIONS = {"resource_id", "department", "tool", "location"}
_DIMENSIONS = _RANK_DIMENSIONS | {"month", "category", "source", "usage_kind"}
_RANK_COLUMNS = {
    "cost_chf": "cost_chf",
    "energy_kwh": "energy_kwh_mid",
    "co2e_kg": "co2e_kg_mid",
}
_METRICS = ["cost_chf"] + [
    f"{metric}_{scenario}"
    for metric in ("energy_kwh", "co2e_kg")
    for scenario in ("low", "mid", "high")
]


def _coverage(known: pd.Series, unknown: pd.Series, partial: pd.Series) -> pd.Series:
    status = pd.Series("complete", index=known.index, dtype="string")
    return status.mask(unknown.gt(0) | partial.gt(0), "partial").mask(
        known.eq(0), "unavailable"
    )


def summarize_baseline(
    facts: pd.DataFrame, by: str | Sequence[str] = ()
) -> pd.DataFrame:
    """Sum emitted facts by dimension, or across the full baseline if by is empty.

    Complete coverage means all applicable input facts have estimates and no
    recognized partial-usage flags. It describes the model's input coverage.
    """
    dimensions = [by] if isinstance(by, str) else list(by)
    if set(dimensions) - _DIMENSIONS or len(set(dimensions)) != len(dimensions):
        raise ValueError(f"invalid summary dimensions: {dimensions}")

    notes = facts["note"].astype("string")
    partial_tokens = notes.str.contains("known tokens only", regex=False, na=False)
    partial_usage = partial_tokens | notes.str.contains(
        r"known messages only|\bdata for \d+ of \d+ days\b", na=False
    )
    cost_known = facts["cost_chf"].notna()
    counts = {
        "fact_count": 1,
        "cost_known_count": cost_known,
        "cost_unknown_count": ~cost_known,
        "cost_partial_count": cost_known & notes.str.contains(
            "cost incomplete:", regex=False, na=False
        ),
        "partial_token_fact_count": partial_tokens,
    }
    for metric in ("energy", "emissions"):
        status = facts[f"{metric}_status"]
        calculated = status.eq("calculated").fillna(False)
        cost_only = status.eq("cost_only").fillna(False)
        counts[f"{metric}_calculated_count"] = calculated
        counts[f"{metric}_unknown_count"] = ~(calculated | cost_only)
        counts[f"{metric}_cost_only_count"] = cost_only
        counts[f"{metric}_partial_usage_count"] = calculated & partial_usage

    grouped = facts.assign(_company=0, **counts).groupby(
        dimensions or ["_company"], dropna=False, observed=True, sort=True
    )
    summary = grouped[_METRICS].sum(min_count=1).join(grouped[list(counts)].sum())
    summary["cost_coverage"] = _coverage(
        summary["cost_known_count"], summary["cost_unknown_count"], summary["cost_partial_count"]
    )
    for metric in ("energy", "emissions"):
        coverage = _coverage(
            summary[f"{metric}_calculated_count"],
            summary[f"{metric}_unknown_count"],
            summary[f"{metric}_partial_usage_count"],
        )
        all_inapplicable = summary[f"{metric}_cost_only_count"].eq(summary["fact_count"])
        summary[f"{metric}_coverage"] = coverage.mask(all_inapplicable, "inapplicable")
    return summary.reset_index(drop=not dimensions)


def rank_drivers(
    facts: pd.DataFrame, *, by: str, metric: str, limit: int | None = None
) -> pd.DataFrame:
    """Rank known annual CHF, mid kWh, or mid kg CO₂e with group labels as ties."""
    if by not in _RANK_DIMENSIONS:
        raise ValueError(f"invalid ranking dimension: {by}")
    if metric not in _RANK_COLUMNS:
        raise ValueError(f"invalid ranking metric: {metric}")
    if limit is not None and limit < 0:
        raise ValueError("ranking limit must be nonnegative")

    value_column = _RANK_COLUMNS[metric]
    ranked = summarize_baseline(facts, by=by).dropna(subset=[value_column])
    ranked = ranked.sort_values([value_column, by], ascending=[False, True], ignore_index=True)
    if limit is not None:
        ranked = ranked.head(limit).copy()
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ranked
