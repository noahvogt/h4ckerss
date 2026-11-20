"""Load AI and SaaS billing sources into monthly facts and detail tables."""

from pathlib import Path

import pandas as pd

from app.pipeline.schema import COST_CENTER_TO_DEPARTMENT, DEPARTMENTS, empty, validate

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "provided"
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


def _read_exchange_rates(data_dir: Path) -> pd.DataFrame:
    rates = pd.read_csv(data_dir / "exchange_rates.csv")
    rates["month"] = pd.to_datetime(rates["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    for column in ("eur_chf", "usd_chf"):
        rates[column] = pd.to_numeric(rates[column], errors="coerce")
    return rates.drop_duplicates("month", keep="last").set_index("month")


def _notes(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def _department(cost_center: object) -> tuple[str, str]:
    cost_center_value = "" if pd.isna(cost_center) else str(cost_center).strip()
    mapping = COST_CENTER_TO_DEPARTMENT | {"4000": "Consulting"}
    department = mapping.get(cost_center_value)
    if department:
        return department, ""
    return "Unallocated", f"unmapped cost center {cost_center_value or '(missing)'}"


def _strict_sum(values: pd.Series) -> float:
    """Return a total only when every component is present."""
    return values.sum(min_count=len(values))


def _currency_to_chf(
    amounts: pd.Series,
    currencies: pd.Series,
    months: pd.Series,
    rates: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    amount_values = pd.to_numeric(amounts, errors="coerce")
    month_values = pd.to_datetime(months, errors="coerce").dt.to_period("M").dt.to_timestamp()
    currency_values = currencies.astype("string").str.upper().str.strip()
    factors = pd.Series(float("nan"), index=amount_values.index, dtype="float64")
    factors.loc[currency_values.eq("CHF").fillna(False)] = 1.0
    for currency, rate_column in (("USD", "usd_chf"), ("EUR", "eur_chf")):
        matching = currency_values.eq(currency).fillna(False)
        factors.loc[matching] = month_values.loc[matching].map(rates[rate_column])

    cost_chf = amount_values * factors
    reasons = pd.Series("", index=amount_values.index, dtype="string")
    reasons.loc[amount_values.isna()] = "missing amount"
    missing_currency = currency_values.isna() | currency_values.eq("").fillna(False)
    reasons.loc[missing_currency] = "missing currency"
    unsupported = currency_values.notna() & ~currency_values.isin(["CHF", "USD", "EUR"])
    reasons.loc[unsupported] = "unsupported currency"
    missing_rate = currency_values.isin(["USD", "EUR"]) & factors.isna() & amount_values.notna()
    reasons.loc[missing_rate] = "missing monthly exchange rate"
    return cost_chf, reasons


def _load_ai_usage(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(data_dir / "ai_usage.csv")
    raw["month"] = pd.to_datetime(raw["date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    for column in ("tokens_in", "tokens_in_cache", "tokens_out", "cost_chf"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    known_departments = raw["department"].isin(DEPARTMENTS)
    raw["department_note"] = ""
    raw.loc[~known_departments, "department_note"] = "unknown department; set to Unallocated"
    raw["department"] = raw["department"].where(known_departments, "Unallocated")

    raw["row_tokens"] = raw["tokens_in"] + raw["tokens_out"]
    details = (
        raw.groupby(AI_USAGE_KEYS, dropna=False, sort=False)
        .agg(
            tokens_in=("tokens_in", _strict_sum),
            tokens_in_cache=("tokens_in_cache", _strict_sum),
            tokens_out=("tokens_out", _strict_sum),
            missing_tokens_in=("tokens_in", lambda values: values.isna().sum()),
            missing_tokens_in_cache=("tokens_in_cache", lambda values: values.isna().sum()),
            missing_tokens_out=("tokens_out", lambda values: values.isna().sum()),
            rows=("tokens_out", "size"),
            department_note=("department_note", lambda values: _notes(*values)),
        )
        .reset_index()
    )
    for column in ("missing_tokens_in", "missing_tokens_in_cache", "missing_tokens_out"):
        details[column] = details[column].astype("int64")
    details["note"] = [
        _notes(
            department_note,
            f"missing input tokens in {missing_input} row(s)" if missing_input else "",
            f"missing cached input tokens in {missing_cache} row(s)" if missing_cache else "",
            f"missing output tokens in {missing_output} row(s)" if missing_output else "",
        )
        for department_note, missing_input, missing_cache, missing_output in zip(
            details["department_note"],
            details["missing_tokens_in"],
            details["missing_tokens_in_cache"],
            details["missing_tokens_out"],
            strict=True,
        )
    ]

    fact_keys = ["month", "resource_id", "tool", "department"]
    facts = (
        raw.groupby(fact_keys, dropna=False, sort=False)
        .agg(
            usage_qty=("row_tokens", _strict_sum),
            cost_chf=("cost_chf", _strict_sum),
            missing_input=("tokens_in", lambda values: values.isna().any()),
            missing_output=("tokens_out", lambda values: values.isna().any()),
            missing_cost=("cost_chf", lambda values: values.isna().any()),
            department_note=("department_note", lambda values: _notes(*values)),
        )
        .reset_index()
    )
    notes = []
    for row in facts.itertuples(index=False):
        issues = []
        if row.missing_input:
            issues.append("incomplete token usage: missing input tokens")
        if row.missing_output:
            issues.append("incomplete token usage: missing output tokens")
        if row.missing_cost:
            issues.append("incomplete AI cost: missing cost_chf")
        notes.append(_notes(row.department_note, *issues))
    facts["note"] = notes
    facts["category"] = "ai"
    facts["source"] = "ai_usage.csv"
    facts["location"] = "EU"
    facts["usage_kind"] = "tokens"
    facts["cost_center"] = pd.NA
    details["department"] = details["department"].fillna("Unallocated")
    facts = facts.drop(
        columns=["missing_input", "missing_output", "missing_cost", "department_note"]
    )
    return facts, details


def _subscription_details(
    data_dir: Path,
    filename: str,
    product_column: str,
    rates: pd.DataFrame,
) -> pd.DataFrame:
    raw = pd.read_csv(data_dir / filename)
    raw["month"] = pd.to_datetime(raw["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    raw["cost_center"] = raw["cost_center"].astype("string")
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
    raw["department"] = raw["cost_center"].map(
        lambda value: _department(value)[0] if pd.notna(value) else "Unallocated"
    )
    amount_chf, fx_notes = _currency_to_chf(raw["amount"], raw["currency"], raw["month"], rates)
    raw["amount_chf"] = amount_chf
    raw["note"] = [
        _notes(
            "Draft; excluded from billed totals" if status == "Draft" else "",
            "unknown contract status; excluded from billed totals"
            if status not in {"Final", "Draft"}
            else "",
            _department(cost_center)[1],
            reason,
            "missing purchased licences" if pd.isna(purchased) else "",
            "missing active licences" if pd.isna(active) else "",
        )
        for status, cost_center, reason, purchased, active in zip(
            raw["contract_status"],
            raw["cost_center"],
            fx_notes,
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

    billed["resource_id"] = (
        f"{category}-subscription:"
        + billed["product"].astype("string")
        + ":"
        + billed["provider"].astype("string")
    )
    billed["tool"] = billed["product"]
    keys = ["month", "resource_id", "tool", "department", "cost_center"]
    grouped = (
        billed.groupby(keys, dropna=False, sort=False)
        .agg(
            usage_qty=("licences_purchased", _strict_sum),
            cost_chf=("amount_chf", _strict_sum),
            missing_seats=("licences_purchased", lambda values: values.isna().any()),
            missing_cost=("amount_chf", lambda values: values.isna().any()),
            notes=("note", lambda values: _notes(*values)),
        )
        .reset_index()
    )
    grouped["note"] = [
        _notes(
            note,
            "incomplete purchased-seat count" if missing_seats else "",
            "incomplete subscription cost" if missing_cost else "",
        )
        for note, missing_seats, missing_cost in zip(
            grouped["notes"], grouped["missing_seats"], grouped["missing_cost"], strict=True
        )
    ]
    grouped["category"] = category
    grouped["source"] = filename
    grouped["location"] = "EU"
    grouped["usage_kind"] = "seat_month"
    return grouped.drop(columns=["missing_seats", "missing_cost", "notes"])


def load_ai_usage_details(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Return monthly AI token details, including model, provider, and department."""
    _, details = _load_ai_usage(Path(data_dir))
    return details


def load_ai_subscription_details(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Return AI licence counts and contract details, including Draft rows."""
    path = Path(data_dir)
    return _subscription_details(path, "ai_subscriptions.csv", "product", _read_exchange_rates(path))


def load_saas_subscription_details(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Return SaaS licence counts and contract details, including Draft rows."""
    path = Path(data_dir)
    return _subscription_details(path, "saas_contracts.csv", "contract", _read_exchange_rates(path))


def load_ai_saas(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Load validated monthly AI and SaaS facts without double-counting costs."""
    path = Path(data_dir)
    ai_facts, _ = _load_ai_usage(path)
    rates = _read_exchange_rates(path)
    ai_subscriptions = _subscription_details(path, "ai_subscriptions.csv", "product", rates)
    saas_subscriptions = _subscription_details(path, "saas_contracts.csv", "contract", rates)
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
