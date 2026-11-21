"""Loader for aws_costs.csv -> fact rows (issue #1).

AWS-specific decisions (shared rules: billing.py, docs/data_decisions.md):
- Exact duplicate rows are dropped (re-export of 2025-12-03).
- All costs are USD -> CHF with the month's rate.
- The support fee is a monthly charge: cost only (usage_kind "none"), no day count.
- The sandbox (test account, cost center 9100) is kept as department "Test account".
  Rows the source marks for exclusion are noted; excluding them is a baseline decision (#4).
- Free text in line_item_description is never copied; instruction-like text is flagged.
"""

import pandas as pd

from app.pipeline.billing import check_known, finish, join_notes, monthly_facts, resource_ids
from app.pipeline.common import is_suspicious_text, month_start, read_csv, to_chf
from app.pipeline.schema import REGION_TO_LOCATION, validate

SOURCE = "aws_costs.csv"

UNIT_TO_USAGE_KIND = {
    "vCPU-hour": "vcpu_h",
    "GB-day": "gb_day",
    "GB": "gb_transfer",
    "runner-minute": "runner_min",
    "month": "none",  # support fee
}

# Every service needs a rule: "Compute instances" are VMs (server), the rest is cloud.
# A new name (e.g. "AmazonEC2" in a real export) stops the load instead of
# silently landing in "cloud".
KNOWN_SERVICES = {"Compute instances", "Storage", "Network", "Build service", "Support"}

_EXCLUSION_REMARK = r"(?i)\bexclude"


def daily_rows() -> pd.DataFrame:
    """aws_costs.csv in the standard daily frame (billing.DAILY_COLUMNS) + charge_type."""
    df = read_csv(SOURCE).drop_duplicates()
    check_known(
        df,
        SOURCE,
        pricing_unit=set(UNIT_TO_USAGE_KIND),
        line_item_line_item_type={"Usage", "Fee"},
        product_region=set(REGION_TO_LOCATION),
        line_item_currency_code={"USD"},
        product_servicecode=KNOWN_SERVICES,
    )
    description = df["line_item_description"].fillna("")
    row_note = join_notes(
        is_suspicious_text(description).map({True: "suspicious free text in source ignored", False: ""}),
        description.str.contains(_EXCLUSION_REMARK, regex=True).map(
            {True: "source marks rows for exclusion (kept)", False: ""}
        ),
    )
    return pd.DataFrame(
        {
            "day": pd.to_datetime(df["line_item_usage_start_date"], format="ISO8601"),
            "month": month_start(df["line_item_usage_start_date"]),
            "resource_id": resource_ids(df["line_item_resource_id"], r"[:/]", SOURCE),
            "service": df["product_servicecode"],
            "unit": df["pricing_unit"],
            "region": df["product_region"],
            "quantity": df["line_item_usage_amount"],
            "cost_chf": to_chf(
                df["line_item_unblended_cost"],
                df["line_item_currency_code"],
                df["line_item_usage_start_date"],
            ),
            "tag_department": df["resource_tags_user_department"],
            "row_note": row_note,
            "charge_type": df["line_item_line_item_type"],
        }
    )


def load_aws() -> pd.DataFrame:
    """All AWS costs as validated fact rows (one per month x resource)."""
    daily = daily_rows()
    usage = daily[daily["charge_type"] == "Usage"]
    fees = daily[daily["charge_type"] == "Fee"]
    facts = finish(
        [
            monthly_facts(usage, SOURCE, UNIT_TO_USAGE_KIND),
            monthly_facts(fees, SOURCE, UNIT_TO_USAGE_KIND, count_days=False),
        ]
    )
    return validate(facts, SOURCE)
