"""Loader for azure_costs.csv -> fact rows (issue #1).

Azure-specific decisions (shared rules: billing.py, docs/data_decisions.md):
- Exact duplicate rows are dropped (re-export of 2026-01-15).
- Credits (SLA) stay in as their own row: negative cost, usage_kind "none".
- The Tags JSON only supplies a department to compare against the mapping.
- Free text in Notes is never copied; instruction-like text is flagged.
"""

import json

import pandas as pd

from app.pipeline.billing import check_known, finish, monthly_facts, resource_ids, single_facts
from app.pipeline.common import is_suspicious_text, month_start, read_csv, to_chf
from app.pipeline.schema import REGION_TO_LOCATION, validate

SOURCE = "azure_costs.csv"

UNIT_TO_USAGE_KIND = {
    "vCPU-hour": "vcpu_h",
    "vCore-hour": "vcpu_h",
    "node-hour": "node_h",
    "GPU-hour": "gpu_h",
    "GB-day": "gb_day",
    "capacity-day": "capacity_day",
}

# Every service needs a rule (server vs. cloud, see billing.SERVER_SERVICES).
KNOWN_SERVICES = {
    "Compute instances", "GPU instances", "Data platform", "Database", "Storage", "Reporting",
}


def daily_rows() -> pd.DataFrame:
    """azure_costs.csv in the standard daily frame (billing.DAILY_COLUMNS) + charge_type."""
    df = read_csv(SOURCE).drop_duplicates()
    check_known(
        df,
        SOURCE,
        UnitOfMeasure=set(UNIT_TO_USAGE_KIND),
        ChargeType={"Usage", "Credit"},
        ResourceLocation=set(REGION_TO_LOCATION),
        ServiceName=KNOWN_SERVICES,
    )
    tags = df["Tags"].fillna("{}").map(json.loads)
    return pd.DataFrame(
        {
            "day": pd.to_datetime(df["Date"], format="ISO8601"),
            "month": month_start(df["Date"]),
            "resource_id": resource_ids(df["ResourceId"], "/", SOURCE),
            "service": df["ServiceName"],
            "unit": df["UnitOfMeasure"],
            "region": df["ResourceLocation"],
            "quantity": df["Quantity"],
            "cost_chf": to_chf(df["CostInBillingCurrency"], df["BillingCurrency"], df["Date"]),
            "tag_department": tags.map(lambda t: t.get("department") or None),
            "row_note": is_suspicious_text(df["Notes"]).map(
                {True: "suspicious free text in source ignored", False: ""}
            ),
            "charge_type": df["ChargeType"],
        }
    )


def load_azure() -> pd.DataFrame:
    """All Azure costs as validated fact rows (one per month x resource, plus credits)."""
    daily = daily_rows()
    usage = daily[daily["charge_type"] == "Usage"]
    credits = daily[daily["charge_type"] == "Credit"]
    facts = finish(
        [
            monthly_facts(usage, SOURCE, UNIT_TO_USAGE_KIND),
            single_facts(credits, SOURCE, note="SLA credit"),
        ]
    )
    return validate(facts, SOURCE)
