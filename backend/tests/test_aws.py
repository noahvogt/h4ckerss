import pandas as pd
import pytest

from app.pipeline.aws import SOURCE, load_aws
from app.pipeline.common import read_csv, to_chf


@pytest.fixture(scope="module")
def facts():
    return load_aws()


@pytest.fixture(scope="module")
def raw():
    df = read_csv(SOURCE).drop_duplicates()
    df["resource_id"] = df["line_item_resource_id"].str.split(r"[:/]", regex=True).str[-1]
    df["month"] = pd.to_datetime(df["line_item_usage_start_date"]).dt.to_period("M").dt.to_timestamp()
    df["cost_chf"] = to_chf(df["line_item_unblended_cost"], "USD", df["line_item_usage_start_date"])
    return df


def test_one_row_per_month_and_resource(facts):
    assert not facts.duplicated(["month", "resource_id", "usage_kind"]).any()
    assert len(facts) == 7 * 23  # 7 resources x 23 months


def test_no_cost_left_missing(facts):
    assert facts["cost_chf"].notna().all()


def test_costs_reconcile_with_raw_where_nothing_estimated(facts, raw):
    raw_sum = raw.groupby(["month", "resource_id"])["cost_chf"].sum()
    clean = facts[~facts["note"].str.contains("estimated")]
    got = clean.set_index(["month", "resource_id"])["cost_chf"]
    pd.testing.assert_series_equal(
        got.sort_index(), raw_sum.loc[got.index].sort_index(), check_names=False, check_index_type=False
    )


def test_support_fee_is_cost_only_and_estimated_when_missing(facts):
    support = facts[facts["resource_id"] == "support"].set_index("month")
    assert (support["usage_kind"] == "none").all() and (support["usage_qty"] == 0).all()
    assert not support["note"].str.contains("data for").any()
    sep = support.loc[pd.Timestamp("2025-09-01")]  # fee missing in the source
    assert sep["note"] == "monthly fee estimated from other months"
    assert sep["cost_chf"] == pytest.approx(900.0, rel=0.05)


def test_sandbox_kept_as_test_account_and_exclusion_noted(facts):
    sandbox = facts[facts["resource_id"] == "sandbox"]
    assert (sandbox[["department", "cost_center", "category"]] == ["Test account", "9100", "server"]).all().all()
    assert sandbox["note"].str.contains("source marks rows for exclusion").any()
    assert not facts["note"].str.contains("please", case=False).any()  # free text never copied


def test_locations(facts):
    loc = facts.groupby("resource_id")["location"].first().to_dict()
    assert loc["vm-test"] == "IE" and loc["st-archive"] == "CH"


def test_category_per_resource(facts):
    category = facts.groupby("resource_id")["category"].unique().map(list).to_dict()
    assert category == {
        "vm-test": ["server"], "sandbox": ["server"],  # Compute instances = VMs
        "cicd": ["cloud"], "net-egress": ["cloud"], "st-archive": ["cloud"],
        "st-backup": ["cloud"], "support": ["cloud"],
    }


def test_every_short_id_is_unique_and_in_the_master_data(raw):
    from app.pipeline.common import mapping

    pairs = raw[["line_item_resource_id", "resource_id"]].drop_duplicates()
    assert pairs["resource_id"].is_unique  # one ARN per short ID
    assert set(pairs["resource_id"]) <= set(mapping().index)


def test_unknown_service_stops_the_load(monkeypatch):
    import app.pipeline.aws as aws

    real = aws.read_csv
    monkeypatch.setattr(
        aws, "read_csv",
        lambda name, **kw: real(name, **kw).replace({"product_servicecode": {"Compute instances": "AmazonEC2"}}),
    )
    with pytest.raises(ValueError, match="AmazonEC2"):
        aws.load_aws()
