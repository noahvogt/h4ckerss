"""Load AI and SaaS billing sources into monthly facts and detail tables."""

from pathlib import Path

import pandas as pd

from app.pipeline import common
from app.pipeline.schema import DEPARTMENTS, empty, validate

DATA_DIR = common.DATA_DIR
AI_USAGE_KEYS = [
    "month",
    "resource_id",
    "tool",
    "department",
    "task_type",
    "model_class",
    "provider",
    "model",
]
DETAIL_COLUMNS = [
    "month",
    "product",
    "provider",
    "cost_center",
    "department",
    "licences_purchased",
    "licences_active_30d",
    "messages_30d",
    "price_per_seat",
    "price_per_licence",
    "currency",
    "amount",
    "amount_chf",
    "contract_status",
    "contract_end",
    "notice_period_days",
    "billing",
    "note",
]

AI_SUBSCRIPTION_RESOURCES = {
    "ChatGPT Team": ("sub-chatgpt", "ChatGPT Team (subscription)"),
    "Claude Team": ("sub-claude", "Claude Team (subscription)"),
    "Microsoft Copilot": ("sub-copilot", "Microsoft Copilot (subscription)"),
}
SAAS_SUBSCRIPTION_RESOURCES = {
    "Microsoft 365": ("saas-m365", "Microsoft 365 (licences)"),
}
OTHER_SAAS_RESOURCE = ("saas-other", "Other SaaS contracts")


def _notes(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def _strict_sum(values: pd.Series) -> float:
    """Return a total only when every component is present."""
    return values.sum(min_count=len(values))


def _known_sum(values: pd.Series) -> float:
    """Sum known values without turning an entirely missing group into zero."""
    return values.sum(min_count=1)


def _token_note(missing_input: int, missing_output: int, rows: int) -> str:
    if not (missing_input or missing_output):
        return ""
    if missing_input == rows and missing_output == rows:
        return (
            "incomplete token usage: all input and output token values missing; "
            "usage unavailable"
        )
    return (
        f"incomplete token usage: {missing_input} missing input values, "
        f"{missing_output} missing output values; known tokens only"
    )


def _load_ai_usage(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = common.read_csv(str(data_dir / "ai_usage.csv")).drop_duplicates().copy()
    raw["month"] = common.month_start(raw["date"])
    for column in ("tokens_in", "tokens_in_cache", "tokens_out", "cost_chf"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    known_departments = raw["department"].isin(DEPARTMENTS)
    raw["department_note"] = ""
    raw.loc[~known_departments, "department_note"] = "unknown department; set to Unallocated"
    raw["department"] = raw["department"].where(known_departments, "Unallocated")

    details = (
        raw.groupby(AI_USAGE_KEYS, dropna=False, sort=False)
        .agg(
            tokens_in=("tokens_in", _known_sum),
            tokens_in_cache=("tokens_in_cache", _known_sum),
            tokens_out=("tokens_out", _known_sum),
            missing_tokens_in=("tokens_in", lambda values: values.isna().sum()),
            missing_tokens_in_cache=("tokens_in_cache", lambda values: values.isna().sum()),
            missing_tokens_out=("tokens_out", lambda values: values.isna().sum()),
            rows=("tokens_in", "size"),
            department_note=("department_note", lambda values: _notes(*values)),
        )
        .reset_index()
    )
    for column in (
        "missing_tokens_in",
        "missing_tokens_in_cache",
        "missing_tokens_out",
        "rows",
    ):
        details[column] = details[column].astype("int64")
    details["note"] = [
        _notes(
            department_note,
            _token_note(missing_input, missing_output, rows),
            (
                f"missing cached input tokens in {missing_cache} row(s)"
                if missing_cache
                else ""
            ),
        )
        for department_note, missing_input, missing_cache, missing_output, rows in zip(
            details["department_note"],
            details["missing_tokens_in"],
            details["missing_tokens_in_cache"],
            details["missing_tokens_out"],
            details["rows"],
            strict=True,
        )
    ]

    fact_keys = ["month", "resource_id", "tool", "department"]
    facts = (
        raw.groupby(fact_keys, dropna=False, sort=False)
        .agg(
            tokens_in=("tokens_in", _known_sum),
            tokens_out=("tokens_out", _known_sum),
            cost_chf=("cost_chf", _strict_sum),
            missing_input=("tokens_in", lambda values: values.isna().sum()),
            missing_output=("tokens_out", lambda values: values.isna().sum()),
            rows=("tokens_in", "size"),
            missing_cost=("cost_chf", lambda values: values.isna().any()),
            department_note=("department_note", lambda values: _notes(*values)),
        )
        .reset_index()
    )
    facts["usage_qty"] = facts[["tokens_in", "tokens_out"]].sum(
        axis=1, min_count=1
    )
    facts["note"] = [
        _notes(
            department_note,
            _token_note(missing_input, missing_output, rows),
            "incomplete AI cost: missing cost_chf" if missing_cost else "",
        )
        for department_note, missing_input, missing_output, rows, missing_cost in zip(
            facts["department_note"],
            facts["missing_input"],
            facts["missing_output"],
            facts["rows"],
            facts["missing_cost"],
            strict=True,
        )
    ]
    facts["category"] = "ai"
    facts["source"] = "ai_usage.csv"
    facts["location"] = "EU"
    facts["usage_kind"] = "tokens"
    facts["cost_center"] = pd.NA
    facts = facts.drop(
        columns=[
            "tokens_in",
            "tokens_out",
            "missing_input",
            "missing_output",
            "rows",
            "missing_cost",
            "department_note",
        ]
    )
    return facts, details.drop(columns="department_note")


def _subscription_details(
    data_dir: Path,
    filename: str,
    product_column: str,
) -> pd.DataFrame:
    raw = common.read_csv(
        str(data_dir / filename), dtype={"cost_center": "string"}
    )
    raw["month"] = common.month_start(raw["month"])
    for column in (
        "licences_purchased",
        "licences_active_30d",
        "messages_30d",
        "price_per_seat",
        "price_per_licence",
        "amount",
    ):
        if column in raw:
            raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw["department"] = common.department_for(raw["cost_center"])
    raw["amount_chf"] = common.to_chf(
        raw["amount"],
        raw["currency"],
        raw["month"],
        data_dir=data_dir,
    )
    unknown_cost_centers = raw["department"].eq("Unallocated")
    cost_center_notes = [
        (
            "unmapped cost center "
            + (
                str(cost_center).strip()
                if pd.notna(cost_center) and str(cost_center).strip()
                else "(missing)"
            )
            if unknown
            else ""
        )
        for cost_center, unknown in zip(
            raw["cost_center"], unknown_cost_centers, strict=True
        )
    ]
    raw["note"] = [
        _notes(
            "Draft; excluded from billed totals" if status == "Draft" else "",
            "unknown contract status; excluded from billed totals"
            if status not in {"Final", "Draft"}
            else "",
            cost_center_note,
            "missing amount" if pd.isna(amount) else "",
            "missing purchased licences" if pd.isna(purchased) else "",
            "missing active licences" if pd.isna(active) else "",
        )
        for status, cost_center_note, amount, purchased, active in zip(
            raw["contract_status"],
            cost_center_notes,
            raw["amount"],
            raw["licences_purchased"],
            raw["licences_active_30d"],
            strict=True,
        )
    ]
    raw["product"] = raw[product_column]
    for optional in ("messages_30d", "price_per_seat", "price_per_licence"):
        if optional not in raw:
            raw[optional] = pd.NA
    return raw.loc[:, DETAIL_COLUMNS]


def _subscription_facts(
    details: pd.DataFrame,
    filename: str,
    category: str,
) -> pd.DataFrame:
    billed = details.loc[details["contract_status"].eq("Final")].copy()
    if billed.empty:
        return empty()

    if category == "ai":
        unknown_products = sorted(
            set(billed["product"].dropna()) - set(AI_SUBSCRIPTION_RESOURCES)
        )
        if unknown_products or billed["product"].isna().any():
            raise ValueError(
                "unknown or missing AI subscription product: "
                f"{unknown_products or 'empty values'}"
            )
        resources = billed["product"].map(AI_SUBSCRIPTION_RESOURCES)
    else:
        resources = billed["product"].map(SAAS_SUBSCRIPTION_RESOURCES)
        resources = resources.apply(
            lambda resource: resource
            if isinstance(resource, tuple)
            else OTHER_SAAS_RESOURCE
        )
    billed[["resource_id", "tool"]] = pd.DataFrame(
        resources.tolist(), index=billed.index
    )
    keys = ["month", "resource_id", "tool", "department", "cost_center"]
    is_ai = category == "ai"
    usage_column = "messages_30d" if is_ai else "licences_purchased"
    usage_aggregation = _known_sum if is_ai else _strict_sum
    grouped = (
        billed.groupby(keys, dropna=False, sort=False)
        .agg(
            usage_qty=(usage_column, usage_aggregation),
            cost_chf=("amount_chf", _strict_sum),
            missing_usage_count=(usage_column, lambda values: values.isna().sum()),
            usage_rows=(usage_column, "size"),
            missing_cost=("amount_chf", lambda values: values.isna().any()),
            notes=("note", lambda values: _notes(*values)),
        )
        .reset_index()
    )
    if is_ai:
        grouped["usage_note"] = [
            (
                "incomplete message usage: all message values missing; usage unavailable"
                if missing == rows
                else (
                    f"incomplete message usage: {missing} missing message values; "
                    "known messages only"
                )
                if missing
                else ""
            )
            for missing, rows in zip(
                grouped["missing_usage_count"], grouped["usage_rows"], strict=True
            )
        ]
        grouped["usage_kind"] = "messages"
    else:
        grouped["usage_note"] = grouped["missing_usage_count"].map(
            lambda missing: "incomplete purchased-seat count" if missing else ""
        )
        grouped["usage_kind"] = "seat_month"
    grouped["note"] = [
        _notes(
            note,
            usage_note,
            "incomplete subscription cost" if missing_cost else "",
        )
        for note, usage_note, missing_cost in zip(
            grouped["notes"],
            grouped["usage_note"],
            grouped["missing_cost"],
            strict=True,
        )
    ]
    grouped["category"] = category
    grouped["source"] = filename
    grouped["location"] = "EU"
    return grouped.drop(
        columns=[
            "missing_usage_count",
            "usage_rows",
            "missing_cost",
            "notes",
            "usage_note",
        ]
    )


def load_ai_usage_details(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Return monthly AI token details, including model, provider, and department."""
    _, details = _load_ai_usage(Path(data_dir))
    return details


def load_ai_subscription_details(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Return AI licence counts and contract details, including Draft rows."""
    return _subscription_details(Path(data_dir), "ai_subscriptions.csv", "product")


def load_saas_subscription_details(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Return SaaS licence counts and contract details, including Draft rows."""
    return _subscription_details(Path(data_dir), "saas_contracts.csv", "contract")


def load_ai_saas(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Load validated monthly AI and SaaS facts without double-counting costs."""
    path = Path(data_dir)
    ai_facts, _ = _load_ai_usage(path)
    ai_subscriptions = _subscription_details(path, "ai_subscriptions.csv", "product")
    saas_subscriptions = _subscription_details(path, "saas_contracts.csv", "contract")
    facts = pd.concat(
        [
            ai_facts,
            _subscription_facts(ai_subscriptions, "ai_subscriptions.csv", "ai"),
            _subscription_facts(saas_subscriptions, "saas_contracts.csv", "saas"),
        ],
        ignore_index=True,
    )
    if facts.empty:
        facts = empty()
    return validate(facts, name="AI and SaaS facts")


def calculate_unused_ai_seats(
    data_dir: str | Path = DATA_DIR,
    month: str | pd.Timestamp = "2026-08-01",
) -> pd.DataFrame:
    """Calculate Final AI seats unused in a month and their allocated monthly CHF cost."""
    details = load_ai_subscription_details(data_dir)
    selected_month = pd.Timestamp(month).to_period("M").to_timestamp()
    billed = details.loc[
        details["month"].eq(selected_month) & details["contract_status"].eq("Final")
    ].copy()
    columns = [
        "month",
        "product",
        "provider",
        "licences_purchased",
        "licences_active_30d",
        "licences_unused",
        "cost_chf",
        "unused_cost_chf",
        "note",
    ]
    if billed.empty:
        return pd.DataFrame(columns=columns)

    billed["licences_unused"] = billed["licences_purchased"] - billed["licences_active_30d"]
    missing_seats = billed["licences_purchased"].isna() | billed["licences_active_30d"].isna()
    over_active = billed["licences_unused"].lt(0).fillna(False)
    billed.loc[over_active | missing_seats, "licences_unused"] = pd.NA
    per_seat_fraction = billed["licences_unused"] / billed["licences_purchased"].where(
        billed["licences_purchased"].gt(0)
    )
    billed["unused_cost_chf"] = billed["amount_chf"] * per_seat_fraction
    no_seats = billed["licences_purchased"].eq(0).fillna(False)
    billed.loc[no_seats, "unused_cost_chf"] = pd.NA
    billed["note"] = [
        _notes(
            note,
            "active licences exceed purchased licences" if exceeds else "",
            "missing or zero licence count" if missing else "",
        )
        for note, exceeds, missing in zip(
            billed["note"], over_active, missing_seats | no_seats, strict=True
        )
    ]
    grouped = (
        billed.groupby(["month", "product", "provider"], dropna=False, sort=False)
        .agg(
            licences_purchased=("licences_purchased", _strict_sum),
            licences_active_30d=("licences_active_30d", _strict_sum),
            licences_unused=("licences_unused", _strict_sum),
            cost_chf=("amount_chf", _strict_sum),
            unused_cost_chf=("unused_cost_chf", _strict_sum),
            notes=("note", lambda values: _notes(*values)),
            incomplete=("unused_cost_chf", lambda values: values.isna().any()),
        )
        .reset_index()
    )
    grouped["note"] = [
        _notes(note, "incomplete unused-seat cost" if incomplete else "")
        for note, incomplete in zip(grouped["notes"], grouped["incomplete"], strict=True)
    ]
    return grouped.loc[:, columns]
