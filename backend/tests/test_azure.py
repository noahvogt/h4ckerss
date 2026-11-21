import pandas as pd
import pytest

from app.pipeline.azure import SOURCE, _estimate_missing_costs, _usage_facts, load_azure
from app.pipeline.common import read_csv, to_chf


@pytest.fixture(scope="module")
def facts():
    return load_azure()


@pytest.fixture(scope="module")
def raw():
    df = read_csv(SOURCE).drop_duplicates()
    df["resource_id"] = df["ResourceId"].str.split("/").str[-1]
    df["month"] = pd.to_datetime(df["Date"]).dt.to_period("M").dt.to_timestamp()
    df["cost_chf"] = to_chf(df["CostInBillingCurrency"], df["BillingCurrency"], df["Date"])
    return df


def test_one_row_per_month_resource_and_kind(facts):
    assert not facts.duplicated(["month", "resource_id", "usage_kind"]).any()
    assert len(facts) == 7 * 23 + 3  # 7 resources x 23 months + 3 credits


def test_no_cost_left_missing(facts):
    assert facts["cost_chf"].notna().all()


def test_costs_reconcile_with_raw_where_nothing_estimated(facts, raw):
    usage = raw[raw["ChargeType"] == "Usage"]
    raw_sum = usage.groupby(["month", "resource_id"])["cost_chf"].sum()
    clean = facts[(facts["usage_kind"] != "none") & ~facts["note"].str.contains("estimated")]
    got = clean.set_index(["month", "resource_id"])["cost_chf"]
    pd.testing.assert_series_equal(got.sort_index(), raw_sum.loc[got.index].sort_index(), check_names=False, check_index_type=False)


def test_estimates_only_add_cost(facts, raw):
    raw_total = raw.loc[raw["ChargeType"] == "Usage", "cost_chf"].sum()
    fact_total = facts.loc[facts["usage_kind"] != "none", "cost_chf"].sum()
    assert fact_total > raw_total


def test_credits_kept_negative(facts):
    credits = facts[facts["note"] == "SLA credit"]
    assert credits["cost_chf"].sum() == pytest.approx(-3900.0)
    assert (credits["usage_kind"] == "none").all()


def test_gpu_server_runs_around_the_clock_in_sep_2025(facts):
    gpu = facts[(facts["resource_id"] == "gpu-ml") & (facts["month"] == "2025-09-01")].iloc[0]
    assert (gpu["category"], gpu["location"], gpu["usage_kind"], gpu["usage_qty"]) == (
        "server", "DE", "gpu_h", 720.0,
    )


def test_injected_instruction_is_flagged_not_followed(facts, raw):
    flagged = facts[facts["note"].str.contains("suspicious free text")]
    assert flagged[["resource_id", "month"]].values.tolist() == [["vm-app", pd.Timestamp("2026-04-01")]]
    assert not facts["note"].str.contains("INSTRUCTION", case=False).any()


# --- synthetic tests: known prices, so the estimate itself is checked ---------------


def synthetic(rows):
    """rows: (resource_id, unit, date, quantity, cost_chf)."""
    df = pd.DataFrame(rows, columns=["resource_id", "UnitOfMeasure", "Date", "Quantity", "cost_chf"])
    df["ServiceName"] = df["UnitOfMeasure"].map(
        {"GPU-hour": "GPU instances", "GB-day": "Storage", "vCPU-hour": "Compute instances"}
    )
    df["ResourceLocation"] = "Germany (Frankfurt)"
    df["day"] = pd.to_datetime(df["Date"])
    df["month"] = df["day"].dt.to_period("M").dt.to_timestamp()
    df["suspicious"] = False
    df["tag_department"] = None
    return df


def test_estimate_uses_median_unit_price_of_the_month():
    df = synthetic([
        ("gpu-ml", "GPU-hour", "2025-09-01", 24, 48.0),  # 2.00 / h
        ("gpu-ml", "GPU-hour", "2025-09-02", 24, 50.4),  # 2.10 / h
        ("gpu-ml", "GPU-hour", "2025-09-03", 24, 52.8),  # 2.20 / h -> median 2.10
        ("gpu-ml", "GPU-hour", "2025-09-04", 10, None),
    ])
    out = _estimate_missing_costs(df)
    assert out["cost_chf"].iloc[3] == pytest.approx(21.0)
    assert out["estimated"].tolist() == [False, False, False, True]


def test_estimate_falls_back_to_other_months():
    df = synthetic([
        ("gpu-ml", "GPU-hour", "2025-08-31", 24, 72.0),  # 3.00 / h, previous month
        ("gpu-ml", "GPU-hour", "2025-09-01", 24, None),  # no price in September
    ])
    assert _estimate_missing_costs(df)["cost_chf"].iloc[1] == pytest.approx(72.0)


def test_estimate_never_mixes_units_of_one_resource():
    df = synthetic([
        ("gpu-ml", "GPU-hour", "2025-09-01", 24, 48.0),  # 2.00 / GPU-hour
        ("gpu-ml", "GB-day", "2025-09-01", 1000, 1.0),  # 0.001 / GB-day
        ("gpu-ml", "GB-day", "2025-09-02", 1000, None),
    ])
    assert _estimate_missing_costs(df)["cost_chf"].iloc[2] == pytest.approx(1.0)


def test_partial_total_is_marked_incomplete():
    df = synthetic([
        ("vm-app", "vCPU-hour", "2025-09-01", 0, 10.0),  # quantity 0 -> no unit price
        ("vm-app", "vCPU-hour", "2025-09-02", 0, None),  # nothing to estimate from
    ])
    fact = _usage_facts(df).iloc[0]
    assert fact["cost_chf"] == pytest.approx(10.0)
    assert "cost incomplete: missing for 1 day, total too low" in fact["note"]
