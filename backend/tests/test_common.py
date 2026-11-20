import math

import pandas as pd
import pytest

from app.pipeline.common import department_for, lookup, month_start, to_chf


def test_month_start_iso_and_custom_format():
    assert month_start(pd.Series(["2025-09-17", "2025-09-01 13:00:00"])).tolist() == [
        pd.Timestamp("2025-09-01")
    ] * 2
    assert month_start(pd.Series(["17.09.2025"]), format="%d.%m.%Y")[0] == pd.Timestamp("2025-09-01")


def test_to_chf_uses_rate_of_the_month():
    # exchange_rates.csv: 2024-11 EUR 0.9355, USD 0.8801
    out = to_chf(
        pd.Series([100.0, 100.0, 100.0]),
        pd.Series(["EUR", "usd", "CHF"]),
        pd.Series(["2024-11-15", "2024-11-01", "2024-11-30"]),
    )
    assert out.round(2).tolist() == [93.55, 88.01, 100.0]


def test_to_chf_single_currency_and_missing_amount_stays_missing():
    out = to_chf(pd.Series([10.0, None]), "USD", pd.Series(["2024-11-01", "2024-11-01"]))
    assert out[0] == pytest.approx(8.801)
    assert math.isnan(out[1])


@pytest.mark.parametrize(
    "currency, month, message",
    [("GBP", "2025-01-01", "unknown or missing currency"), ("CHF", "2030-01-01", "no exchange rate")],
)
def test_to_chf_rejects_bad_input(currency, month, message):
    with pytest.raises(ValueError, match=message):
        to_chf(pd.Series([1.0]), pd.Series([currency]), pd.Series([month]))


def test_department_for():
    assert department_for(pd.Series(["4500", 4000, None, "1234"])).tolist() == [
        "IT", "Consulting", "Unallocated", "Unallocated",
    ]


def test_lookup_known_unknown_and_derived_department():
    out = lookup(pd.Series(["gpu-ml", "sandbox", "does-not-exist"], index=[10, 11, 12]))
    assert out.index.tolist() == [10, 11, 12]
    assert out.loc[10].tolist() == ["AI compute server (GPU)", "Consulting", "4000"]
    assert out.loc[11, "department"] == "Test account"  # empty in file, derived from 9100
    assert out.loc[12, "department"] == "Unallocated"
    assert pd.isna(out.loc[12, "tool"])
