"""Loader for hoster_invoice.csv -> fact rows (issue #1).

Hoster-specific decisions (shared rules: billing.py, docs/data_decisions.md):
- The invoice has no resource key: each `Item` label is matched to the master data
  by tool name (e.g. "Web hosting and CDN" -> web-cdn). Unknown labels raise.
- Dates are DD.MM.YYYY. All amounts are already CHF.
- Exact duplicate rows are dropped (re-export of 2026-06-01).
- No region in the file: the hoster runs in Zurich (extra/data_center_locations.csv).
- The source's CostCenter is only compared against the master data, like tags.
- Free text in Remark is never copied; instruction-like text is flagged.
"""

import pandas as pd

from app.pipeline.billing import check_known, finish, monthly_facts
from app.pipeline.common import department_for, is_suspicious_text, mapping, month_start, read_csv
from app.pipeline.schema import validate

SOURCE = "hoster_invoice.csv"
REGION = "Switzerland (Zurich)"

UNIT_TO_USAGE_KIND = {
    "GB-day": "gb_day",
    "GB": "gb_transfer",
}

# Every service needs a rule; all hoster services are "cloud" (no VMs at the hoster).
KNOWN_SERVICES = {"Log storage", "Storage", "Web hosting/CDN"}


def _item_to_resource_id() -> dict[str, str]:
    """Hoster item label -> resource_id, via the tool names in the master data."""
    tools = mapping()["tool"]
    return {tool: resource_id for resource_id, tool in tools.items()}


def daily_rows() -> pd.DataFrame:
    """hoster_invoice.csv in the standard daily frame (billing.DAILY_COLUMNS)."""
    df = read_csv(SOURCE, dtype={"CostCenter": str}).drop_duplicates()
    item_to_id = _item_to_resource_id()
    check_known(
        df, SOURCE, Unit=set(UNIT_TO_USAGE_KIND), Item=set(item_to_id), Service=KNOWN_SERVICES
    )
    cost_center = df["CostCenter"]
    return pd.DataFrame(
        {
            "day": pd.to_datetime(df["Date"], format="%d.%m.%Y"),
            "month": month_start(df["Date"], format="%d.%m.%Y"),
            "resource_id": df["Item"].map(item_to_id),
            "service": df["Service"],
            "unit": df["Unit"],
            "region": REGION,
            "quantity": df["Quantity"],
            "cost_chf": df["Amount_CHF"],
            # Department implied by the source's cost center; compared with the mapping.
            "tag_department": department_for(cost_center).where(cost_center.notna()),
            "row_note": is_suspicious_text(df["Remark"]).map(
                {True: "suspicious free text in source ignored", False: ""}
            ),
        }
    )


def load_hoster() -> pd.DataFrame:
    """All hoster costs as validated fact rows (one per month x item)."""
    facts = finish([monthly_facts(daily_rows(), SOURCE, UNIT_TO_USAGE_KIND)])
    return validate(facts, SOURCE)
