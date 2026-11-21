import pandas as pd
import pytest

from app.pipeline.azure import SOURCE, load_azure
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
