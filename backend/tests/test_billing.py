"""Synthetic tests with known prices, so the shared billing logic itself is checked."""

import pandas as pd
import pytest

from app.pipeline.billing import estimate_missing_costs, monthly_facts

UNITS = {"GPU-hour": "gpu_h", "GB-day": "gb_day", "vCPU-hour": "vcpu_h", "month": "none"}
SERVICES = {"GPU-hour": "GPU instances", "GB-day": "Storage", "vCPU-hour": "Compute instances", "month": "Support"}


def daily(rows, row_note=""):
    """rows: (resource_id, unit, date, quantity, cost_chf)."""
    df = pd.DataFrame(rows, columns=["resource_id", "unit", "day", "quantity", "cost_chf"])
    df["day"] = pd.to_datetime(df["day"])
    df["month"] = df["day"].dt.to_period("M").dt.to_timestamp()
    df["service"] = df["unit"].map(SERVICES)
    df["region"] = "Germany (Frankfurt)"
    df["tag_department"] = None
    df["row_note"] = row_note
    return df


def test_estimate_uses_median_unit_price_of_the_month():
    df = daily([
        ("gpu-ml", "GPU-hour", "2025-09-01", 24, 48.0),  # 2.00 / h
        ("gpu-ml", "GPU-hour", "2025-09-02", 24, 50.4),  # 2.10 / h
        ("gpu-ml", "GPU-hour", "2025-09-03", 24, 52.8),  # 2.20 / h -> median 2.10
        ("gpu-ml", "GPU-hour", "2025-09-04", 10, None),
    ])
    out = estimate_missing_costs(df)
    assert out["cost_chf"].iloc[3] == pytest.approx(21.0)
    assert out["estimated"].tolist() == [False, False, False, True]


def test_estimate_falls_back_to_other_months():
    df = daily([
        ("gpu-ml", "GPU-hour", "2025-08-31", 24, 72.0),  # 3.00 / h, previous month
        ("gpu-ml", "GPU-hour", "2025-09-01", 24, None),  # no price in September
    ])
    assert estimate_missing_costs(df)["cost_chf"].iloc[1] == pytest.approx(72.0)


def test_estimate_never_mixes_units_of_one_resource():
    df = daily([
        ("gpu-ml", "GPU-hour", "2025-09-01", 24, 48.0),  # 2.00 / GPU-hour
        ("gpu-ml", "GB-day", "2025-09-01", 1000, 1.0),  # 0.001 / GB-day
        ("gpu-ml", "GB-day", "2025-09-02", 1000, None),
    ])
    assert estimate_missing_costs(df)["cost_chf"].iloc[2] == pytest.approx(1.0)


def test_partial_total_is_marked_incomplete():
    df = daily([
        ("vm-app", "vCPU-hour", "2025-09-01", 0, 10.0),  # quantity 0 -> no unit price
        ("vm-app", "vCPU-hour", "2025-09-02", 0, None),  # nothing to estimate from
    ])
    fact = monthly_facts(df, "test.csv", UNITS).iloc[0]
    assert fact["cost_chf"] == pytest.approx(10.0)
    assert "cost incomplete: missing for 1 day, total too low" in fact["note"]


def test_master_data_and_notes():
    df = daily([("gpu-ml", "GPU-hour", "2025-09-01", 24, 48.0)], row_note="some flag")
    df["tag_department"] = "Sales"  # mapping says Consulting
    fact = monthly_facts(df, "test.csv", UNITS).iloc[0]
    assert (fact["category"], fact["department"], fact["location"]) == ("server", "Consulting", "DE")
    assert fact["note"] == "data for 1 of 30 days; tag department Sales differs from mapping; some flag"


def test_monthly_fee_has_no_usage_and_no_day_count():
    df = daily([("support", "month", "2025-09-01", 1, 900.0)])
    fact = monthly_facts(df, "test.csv", UNITS, count_days=False).iloc[0]
    assert (fact["usage_kind"], fact["usage_qty"], fact["note"]) == ("none", 0.0, "")


def test_short_id_collision_raises():
    from app.pipeline.billing import resource_ids

    full = pd.Series(["arn:aws:compute:eu:0000:vm-1", "arn:aws:storage:eu:0000:vm-1"])
    with pytest.raises(ValueError, match="vm-1"):
        resource_ids(full, r"[:/]", "test.csv")


def test_monthly_fee_estimate_is_labelled_as_fee():
    df = daily([
        ("support", "month", "2025-08-01", 1, 900.0),
        ("support", "month", "2025-09-01", 1, None),
    ])
    facts = monthly_facts(df, "test.csv", UNITS, count_days=False).set_index("month")
    assert facts.loc[pd.Timestamp("2025-09-01"), "note"] == "monthly fee estimated from other months"
    assert facts.loc[pd.Timestamp("2025-09-01"), "cost_chf"] == pytest.approx(900.0)
