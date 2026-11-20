"""Shared helpers for all loaders: reading raw files, months, currency, master data."""

from functools import cache
from pathlib import Path

import pandas as pd

from app.pipeline.schema import COST_CENTER_TO_DEPARTMENT

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "provided"


def read_csv(name: str, **kwargs) -> pd.DataFrame:
    """Read a provided CSV (UTF-8 with BOM). `name` is relative to data/provided,
    e.g. "azure_costs.csv" or "extra/headcount.csv"."""
    return pd.read_csv(DATA_DIR / name, encoding="utf-8-sig", **kwargs)


def month_start(dates: pd.Series, format: str | None = None) -> pd.Series:
    """Normalise dates (strings or datetimes) to the first day of their month.

    Default accepts ISO dates with or without time ("2025-09-01", "2025-09-01 00:00:00").
    Pass `format` for other dates, e.g. format="%d.%m.%Y" for the hoster.
    Unparseable values raise instead of silently becoming NaT.
    """
    parsed = pd.to_datetime(dates, format=format or "ISO8601")
    return parsed.dt.to_period("M").dt.to_timestamp()


@cache
def exchange_rates() -> pd.DataFrame:
    """Monthly CHF rates, indexed by month (1st of month), columns CHF, EUR, USD."""
    fx = read_csv("exchange_rates.csv", parse_dates=["month"])
    fx = fx.rename(columns={"eur_chf": "EUR", "usd_chf": "USD"}).set_index("month")
    fx["CHF"] = 1.0
    return fx.loc[:, ["CHF", "EUR", "USD"]]


def to_chf(amount: pd.Series, currency: pd.Series | str, month: pd.Series) -> pd.Series:
    """Convert amounts to CHF with the monthly average rate of each row's month.

    - `currency` is a column or one currency for all rows ("USD").
    - `month` can be any date in the month; it is normalised with month_start().
    - Missing amounts stay missing (never turned into 0).
    - Unknown currencies or months without a rate raise ValueError.
    """
    fx = exchange_rates()
    cur = (
        pd.Series(currency, index=amount.index)
        if isinstance(currency, str)
        else currency
    )
    cur = cur.str.strip().str.upper()
    unknown = sorted(set(cur.dropna()) - set(fx.columns))
    if unknown or cur.isna().any():
        raise ValueError(f"unknown or missing currency: {unknown or 'empty values'}")

    months = month_start(month)
    no_rate = sorted(set(months.dropna()) - set(fx.index))
    if no_rate or months.isna().any():
        raise ValueError(
            f"no exchange rate for months: {[str(m.date()) for m in no_rate] or 'empty values'}"
        )

    rate = fx.stack().reindex(pd.MultiIndex.from_arrays([months, cur])).to_numpy()
    return amount * rate


def department_for(cost_center: pd.Series) -> pd.Series:
    """Cost center -> department; unknown or empty -> "Unallocated"."""
    cc = cost_center.astype("string").str.strip().str.removesuffix(".0")
    return cc.map(COST_CENTER_TO_DEPARTMENT).fillna("Unallocated").astype("string")


@cache
def mapping() -> pd.DataFrame:
    """Master data from mapping_departments_tools.csv, indexed by resource_id.

    An empty department is derived from the cost center (e.g. sandbox -> Test account).
    """
    m = read_csv("mapping_departments_tools.csv", dtype=str).set_index("resource_id")
    m["department"] = m["department"].fillna(
        department_for(pd.Series(m["cost_center"]))
    )
    return m


def lookup(resource_id: pd.Series) -> pd.DataFrame:
    """Resource IDs -> columns tool, department, cost_center (same index as input).

    Unknown IDs get department "Unallocated" and empty tool / cost_center,
    so the caller can fill them from the source itself and note it.
    """
    m = mapping()[["tool", "department", "cost_center"]]
    out = (
        m.reindex(resource_id.str.strip()).set_index(resource_id.index).astype("string")
    )
    out["department"] = out["department"].fillna("Unallocated")
    return out
