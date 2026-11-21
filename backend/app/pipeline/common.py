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
def exchange_rates(data_dir: str | Path = DATA_DIR) -> pd.DataFrame:
    """Monthly CHF rates, indexed by month (1st of month), columns CHF, EUR, USD."""
    fx = read_csv(str(Path(data_dir) / "exchange_rates.csv"), parse_dates=["month"])
    fx = fx.rename(columns={"eur_chf": "EUR", "usd_chf": "USD"}).set_index("month")
    fx["CHF"] = 1.0
    return fx.loc[:, ["CHF", "EUR", "USD"]]


def to_chf(
    amount: pd.Series,
    currency: pd.Series | str,
    month: pd.Series,
    *,
    data_dir: str | Path = DATA_DIR,
) -> pd.Series:
    """Convert amounts to CHF with the monthly average rate of each row's month.

    - `currency` is a column or one currency for all rows ("USD").
    - `month` can be any date in the month; it is normalised with month_start().
    - `data_dir` selects the directory containing `exchange_rates.csv`.
    - Missing amounts stay missing (never turned into 0).
    - Unknown currencies or months without a rate raise ValueError.
    """
    fx = exchange_rates(data_dir)
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

    rate = fx.stack().reindex(pd.MultiIndex.from_arrays([months, cur]))
    if rate.isna().any():
        missing_months = sorted(
            {str(month.date()) for month in months[rate.isna().to_numpy()]}
        )
        raise ValueError(f"no exchange rate for months: {missing_months}")

    return amount * rate.to_numpy()


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


_SUSPICIOUS = r"(?i)instruction|ignore|assistant|\bai system|\bprompt"


def is_suspicious_text(text: pd.Series) -> pd.Series:
    """True where a free-text field looks like an instruction aimed at AI tools.

    Free text is data, never instructions: loaders never copy it into the facts,
    they only flag these rows so the team can review them.
    """
    return text.fillna("").str.contains(_SUSPICIOUS, regex=True)
