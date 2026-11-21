"""Loader for azure_costs.csv -> fact rows (issue #1).

Decisions (see also docs/data_decisions.md):
- Exact duplicate rows are dropped.
- Usage rows are summed per month and resource.
- Missing cost with known quantity -> estimated as quantity x median unit price of the
  same resource in the same month (fallback: all months). Noted as "cost estimated".
- Credits (SLA) stay in as their own row: negative cost, usage_kind "none".
- Master data (mapping_departments_tools.csv) wins over the Tags JSON. A tag
  department that differs from the mapping is noted; tool spelling differences are not.
- Days without data are not extrapolated, only noted ("data for 29 of 31 days").
- Free text in Notes is never copied; instruction-like text is flagged.
"""

import json

import pandas as pd

from app.pipeline.common import is_suspicious_text, lookup, month_start, read_csv, to_chf
from app.pipeline.schema import REGION_TO_LOCATION, validate

SOURCE = "azure_costs.csv"

SERVER_SERVICES = {"Compute instances", "GPU instances"}  # VMs; everything else is "cloud"

UNIT_TO_USAGE_KIND = {
    "vCPU-hour": "vcpu_h",
    "vCore-hour": "vcpu_h",
    "node-hour": "node_h",
    "GPU-hour": "gpu_h",
    "GB-day": "gb_day",
    "capacity-day": "capacity_day",
}


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def _join_notes(*parts: pd.Series) -> pd.Series:
    """Combine note columns row-wise into one '; '-separated string."""
    frame = pd.concat(parts, axis=1).fillna("")
    return frame.apply(lambda r: "; ".join(p for p in r if p), axis=1)


def _read() -> pd.DataFrame:
    raw = read_csv(SOURCE)
    df = raw.drop_duplicates().copy()

    unknown_units = set(df["UnitOfMeasure"]) - set(UNIT_TO_USAGE_KIND)
    unknown_charges = set(df["ChargeType"]) - {"Usage", "Credit"}
    unknown_regions = set(df["ResourceLocation"]) - set(REGION_TO_LOCATION)
    if unknown_units or unknown_charges or unknown_regions:
        raise ValueError(
            f"{SOURCE}: unexpected units {unknown_units}, charge types {unknown_charges}, "
            f"regions {unknown_regions}"
        )

    df["resource_id"] = df["ResourceId"].str.split("/").str[-1]
    df["day"] = pd.to_datetime(df["Date"], format="ISO8601")
    df["month"] = month_start(df["Date"])
    df["cost_chf"] = to_chf(df["CostInBillingCurrency"], df["BillingCurrency"], df["Date"])
    tags = df["Tags"].fillna("{}").map(json.loads)
    df["tag_department"] = tags.map(lambda t: t.get("department") or None)
    df["suspicious"] = is_suspicious_text(df["Notes"])
    return df


def _estimate_missing_costs(usage: pd.DataFrame) -> pd.DataFrame:
    usage = usage.copy()
    price = usage["cost_chf"] / usage["Quantity"].where(usage["Quantity"] > 0)
    month_median = price.groupby([usage["resource_id"], usage["month"]]).transform("median")
    overall_median = price.groupby(usage["resource_id"]).transform("median")
    estimate = usage["Quantity"] * month_median.fillna(overall_median)

    usage["estimated"] = usage["cost_chf"].isna() & estimate.notna()
    usage["cost_chf"] = usage["cost_chf"].fillna(estimate)
    return usage


def _usage_facts(usage: pd.DataFrame) -> pd.DataFrame:
    usage = _estimate_missing_costs(usage)
    keys = ["month", "resource_id", "ServiceName", "UnitOfMeasure", "ResourceLocation"]
    g = usage.groupby(keys, as_index=False).agg(
        usage_qty=("Quantity", "sum"),
        cost_chf=("cost_chf", lambda s: s.sum(min_count=1)),  # all missing -> stays missing
        missing_cost=("cost_chf", lambda s: int(s.isna().sum())),
        estimated=("estimated", "sum"),
        days=("day", "nunique"),
        suspicious=("suspicious", "any"),
        tag_departments=("tag_department", lambda s: sorted(set(s.dropna()))),
    )

    days_in_month = g["month"].dt.days_in_month
    master = lookup(g["resource_id"])
    tag_conflict = [
        sorted(set(tags) - {dept}) for tags, dept in zip(g["tag_departments"], master["department"])
    ]

    notes = _join_notes(
        g["estimated"].map(lambda n: f"cost estimated for {_days(n)}" if n else ""),
        g["missing_cost"].map(lambda n: f"cost missing for {_days(n)}" if n else ""),
        pd.Series(
            [f"data for {d} of {m} days" if d < m else "" for d, m in zip(g["days"], days_in_month)],
            index=g.index,
        ),
        pd.Series(
            [f"tag department {', '.join(c)} differs from mapping" if c else "" for c in tag_conflict],
            index=g.index,
        ),
        g["suspicious"].map(lambda s: "suspicious free text in source ignored" if s else ""),
    )

    return pd.DataFrame(
        {
            "month": g["month"],
            "category": g["ServiceName"].map(lambda s: "server" if s in SERVER_SERVICES else "cloud"),
            "source": SOURCE,
            "resource_id": g["resource_id"],
            "tool": master["tool"].fillna(g["ServiceName"]),
            "department": master["department"],
            "cost_center": master["cost_center"],
            "location": g["ResourceLocation"].map(REGION_TO_LOCATION),
            "usage_kind": g["UnitOfMeasure"].map(UNIT_TO_USAGE_KIND),
            "usage_qty": g["usage_qty"],
            "cost_chf": g["cost_chf"],
            "note": notes,
        }
    )


def _credit_facts(credits: pd.DataFrame) -> pd.DataFrame:
    master = lookup(credits["resource_id"])
    return pd.DataFrame(
        {
            "month": credits["month"],
            "category": credits["ServiceName"].map(
                lambda s: "server" if s in SERVER_SERVICES else "cloud"
            ),
            "source": SOURCE,
            "resource_id": credits["resource_id"],
            "tool": master["tool"].fillna(credits["ServiceName"]),
            "department": master["department"],
            "cost_center": master["cost_center"],
            "location": credits["ResourceLocation"].map(REGION_TO_LOCATION),
            "usage_kind": "none",
            "usage_qty": 0.0,
            "cost_chf": credits["cost_chf"],
            "note": "SLA credit",
        }
    )


def load_azure() -> pd.DataFrame:
    """All Azure costs as validated fact rows (one per month x resource, plus credits)."""
    df = _read()
    facts = pd.concat(
        [
            _usage_facts(df[df["ChargeType"] == "Usage"]),
            _credit_facts(df[df["ChargeType"] == "Credit"]),
        ],
        ignore_index=True,
    )
    facts = facts.sort_values(["month", "resource_id", "usage_kind"], ignore_index=True)
    return validate(facts, SOURCE)
