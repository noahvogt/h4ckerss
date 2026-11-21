"""Shared logic for billing sources (Azure, AWS, hoster): daily rows -> monthly facts.

Each loader only translates its file into the standard daily frame (DAILY_COLUMNS).
Everything else is done here, the same way for every source:
- missing cost estimated from the unit price (never mixing units),
- one fact row per month x resource x unit,
- department / tool / cost center from the master data (mapping wins over tags),
- data-quality notes. Free text is never copied, only flagged.
"""

import pandas as pd

from app.pipeline.common import lookup
from app.pipeline.schema import REGION_TO_LOCATION

DAILY_COLUMNS = [
    "day",  # datetime, one row per resource and day
    "month",  # first day of the month
    "resource_id",  # as in mapping_departments_tools.csv
    "service",  # provider service name, e.g. "Compute instances"
    "unit",  # provider billing unit, e.g. "vCPU-hour"
    "region",  # raw region string, see REGION_TO_LOCATION
    "quantity",  # amount in `unit`
    "cost_chf",  # converted cost, may be missing
    "tag_department",  # department from the source's tags, may be missing
    "row_note",  # fixed note for this row (never source free text), may be empty
]

SERVER_SERVICES = {"Compute instances", "GPU instances"}  # VMs; everything else is "cloud"


def days_label(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def join_notes(*parts: pd.Series) -> pd.Series:
    """Combine note columns row-wise into one '; '-separated string."""
    frame = pd.concat(parts, axis=1).fillna("")
    return frame.apply(lambda r: "; ".join(p for p in r if p), axis=1)


def category(service: pd.Series) -> pd.Series:
    return service.map(lambda s: "server" if s in SERVER_SERVICES else "cloud")


def check_known(df: pd.DataFrame, source: str, **allowed: set) -> None:
    """Raise if a column holds values we have no rule for, e.g. check_known(df, src, unit={...})."""
    problems = {col: set(df[col].dropna()) - ok for col, ok in allowed.items()}
    problems = {col: sorted(bad) for col, bad in problems.items() if bad}
    if problems:
        raise ValueError(f"{source}: unexpected values {problems}")


def estimate_missing_costs(daily: pd.DataFrame) -> pd.DataFrame:
    """Fill missing cost with quantity x median unit price.

    The price comes from the same resource, service and billing unit in the same
    month, falling back to all months. Units are never mixed. Adds column `estimated`.
    """
    daily = daily.copy()
    price = daily["cost_chf"] / daily["quantity"].where(daily["quantity"] > 0)
    unit_keys = [daily["resource_id"], daily["service"], daily["unit"]]
    month_median = price.groupby([*unit_keys, daily["month"]]).transform("median")
    overall_median = price.groupby(unit_keys).transform("median")
    estimate = daily["quantity"] * month_median.fillna(overall_median)

    daily["estimated"] = daily["cost_chf"].isna() & estimate.notna()
    daily["cost_chf"] = daily["cost_chf"].fillna(estimate)
    return daily


def monthly_facts(
    daily: pd.DataFrame,
    source: str,
    unit_to_usage_kind: dict[str, str],
    *,
    count_days: bool = True,
) -> pd.DataFrame:
    """Daily rows -> one fact row per month x resource x unit (not yet validated).

    count_days=False for monthly charges (fees), where "days with data" means nothing.
    """
    daily = estimate_missing_costs(daily[DAILY_COLUMNS])
    keys = ["month", "resource_id", "service", "unit", "region"]
    g = daily.groupby(keys, as_index=False).agg(
        usage_qty=("quantity", "sum"),
        # Sum of the known days; all missing -> stays missing. A partial total is
        # marked "cost incomplete" below, so it never looks complete.
        cost_chf=("cost_chf", lambda s: s.sum(min_count=1)),
        missing_cost=("cost_chf", lambda s: int(s.isna().sum())),
        estimated=("estimated", "sum"),
        days=("day", "nunique"),
        tag_departments=("tag_department", lambda s: sorted(set(s.dropna()))),
        row_notes=("row_note", lambda s: sorted(set(s.dropna()) - {""})),
    )

    master = lookup(g["resource_id"])
    usage_kind = g["unit"].map(unit_to_usage_kind)
    days_in_month = g["month"].dt.days_in_month
    tag_conflict = [
        sorted(set(tags) - {dept}) for tags, dept in zip(g["tag_departments"], master["department"])
    ]

    notes = join_notes(
        g["estimated"].map(lambda n: f"cost estimated for {days_label(n)}" if n else ""),
        g["missing_cost"].map(
            lambda n: f"cost incomplete: missing for {days_label(n)}, total too low" if n else ""
        ),
        pd.Series(
            [
                f"data for {d} of {m} days" if count_days and d < m else ""
                for d, m in zip(g["days"], days_in_month)
            ],
            index=g.index,
        ),
        pd.Series(
            [f"tag department {', '.join(c)} differs from mapping" if c else "" for c in tag_conflict],
            index=g.index,
        ),
        g["row_notes"].map("; ".join),
    )

    return pd.DataFrame(
        {
            "month": g["month"],
            "category": category(g["service"]),
            "source": source,
            "resource_id": g["resource_id"],
            "tool": master["tool"].fillna(g["service"]),
            "department": master["department"],
            "cost_center": master["cost_center"],
            "location": g["region"].map(REGION_TO_LOCATION),
            "usage_kind": usage_kind,
            "usage_qty": g["usage_qty"].where(usage_kind != "none", 0.0),
            "cost_chf": g["cost_chf"],
            "note": notes,
        }
    )


def single_facts(rows: pd.DataFrame, source: str, note: str) -> pd.DataFrame:
    """One cost-only fact per row, e.g. credits (not yet validated)."""
    master = lookup(rows["resource_id"])
    return pd.DataFrame(
        {
            "month": rows["month"],
            "category": category(rows["service"]),
            "source": source,
            "resource_id": rows["resource_id"],
            "tool": master["tool"].fillna(rows["service"]),
            "department": master["department"],
            "cost_center": master["cost_center"],
            "location": rows["region"].map(REGION_TO_LOCATION),
            "usage_kind": "none",
            "usage_qty": 0.0,
            "cost_chf": rows["cost_chf"],
            "note": note,
        }
    )


def finish(facts: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate fact parts in a stable order."""
    out = pd.concat(facts, ignore_index=True)
    return out.sort_values(["month", "resource_id", "usage_kind"], ignore_index=True)
