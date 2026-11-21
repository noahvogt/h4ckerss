"""Shared fact table: the shape every loader (cloud, servers, AI, SaaS) must return.

One row = one month x source x resource (x department, where a source splits by it).
Loaders deliver usage + cost only. Energy and CO2 are added later (#4) from the
researched factors, so a factor change never touches a loader.

Rules:
- Costs come from billing sources only (invoices, gateway, licences). Monitoring files
  (server_metrics_weekly, data_platform_usage, server_inventory) describe resources that
  are already billed -> use them for waste analysis, never as extra rows.
- Credits stay in, as negative cost_chf.
- Unknown department -> "Unallocated" (not empty), so sums by department keep every franc.
- Data-quality decisions go into `note` (e.g. "draft dropped; cost estimated").
"""

import pandas as pd

COLUMNS: dict[str, str] = {
    "month": "datetime64[ns]",  # first day of the month at midnight
    "category": "string",  # see CATEGORIES
    "source": "string",  # file name, e.g. "azure_costs.csv"
    "resource_id": "string",  # as in mapping_departments_tools.csv, e.g. "dp-prod"
    "tool": "string",  # as in mapping_departments_tools.csv
    "department": "string",  # see DEPARTMENTS
    "cost_center": "string",  # e.g. "4500"
    "location": "string",  # see LOCATIONS
    "usage_kind": "string",  # see USAGE_KINDS
    "usage_qty": "float64",  # amount in the unit of usage_kind
    "cost_chf": "float64",  # converted to CHF with the month's rate
    "note": "string",  # data-quality flags, ";"-separated, may be empty
}

CATEGORIES = {
    "server",  # virtual machines incl. GPU server (vCPU-hour, GPU-hour)
    "cloud",  # all other cloud/hoster services: data platform, DB, storage, network, build, web
    "ai",  # AI API usage (tokens) and AI subscriptions
    "saas",  # SaaS licences
}

LOCATIONS = {"CH", "DE", "IE", "EU", "unknown"}  # EU = AI providers / SaaS (mixed EU)

# Raw region strings in the data -> location code
REGION_TO_LOCATION = {
    "Switzerland (Zurich)": "CH",
    "Germany (Frankfurt)": "DE",
    "Ireland (Dublin)": "IE",
}

DEPARTMENTS = {
    "Consulting", "Sales", "Finance", "Marketing", "HR", "IT", "Management",
    "Overhead", "Test account", "Unallocated",
}

COST_CENTER_TO_DEPARTMENT = {
    "4000": "Consulting", "4100": "Sales", "4200": "Finance", "4300": "Marketing",
    "4400": "HR", "4500": "IT", "4900": "Management", "9000": "Overhead",
    "9100": "Test account",
}

# Normalised units. The energy driver of the row; #4 maps each to a factor.
USAGE_KINDS = {
    "vcpu_h",  # vCPU-hour and vCore-hour
    "node_h",  # data platform node-hour (16 vCPU, 64 GB)
    "gpu_h",  # GPU-hour (300 W class)
    "gb_day",  # stored GB per day
    "gb_transfer",  # transferred GB (network, CDN)
    "capacity_day",  # reporting capacity-day
    "runner_min",  # build runner minute
    "tokens",  # AI tokens (input + output), raw count, not thousands
    "messages",  # AI subscription messages
    "seat_month",  # licence seats per month (SaaS)
    "none",  # cost only, no usage (fees, support)
}

REQUIRED = ["month", "category", "source", "location", "usage_kind", "department"]


def empty() -> pd.DataFrame:
    """An empty fact table with the right columns and types."""
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLUMNS.items()})


def validate(df: pd.DataFrame, name: str = "facts") -> pd.DataFrame:
    """Check a loader's output. Returns it with canonical column order and types.

    Raises ValueError listing every problem found.
    """
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")
    extra = [c for c in df.columns if c not in COLUMNS]
    if extra:
        raise ValueError(f"{name}: unexpected columns {extra}")

    out = df.loc[:, list(COLUMNS)].astype(COLUMNS)
    problems: list[str] = []

    for col in REQUIRED:
        n = int(out[col].isna().sum())
        if n:
            problems.append(f"{n} empty values in '{col}'")

    for col, allowed in [
        ("category", CATEGORIES),
        ("location", LOCATIONS),
        ("usage_kind", USAGE_KINDS),
        ("department", DEPARTMENTS),
    ]:
        bad = sorted(set(out[col].dropna()) - allowed)
        if bad:
            problems.append(f"unknown {col} values {bad}")

    months = out["month"].dropna()
    not_month_start = (months.dt.day.ne(1) | months.ne(months.dt.normalize())).sum()
    if not_month_start:
        problems.append(f"{not_month_start} 'month' values not on the 1st of the month at midnight")

    no_cost_no_note = out["cost_chf"].isna() & out["note"].fillna("").eq("")
    if no_cost_no_note.any():
        problems.append(f"{int(no_cost_no_note.sum())} rows without cost_chf and without a note")

    if problems:
        raise ValueError(f"{name}: " + "; ".join(problems))
    return out
