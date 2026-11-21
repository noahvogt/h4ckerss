import pandas as pd
import pytest

from app.pipeline.build import DECIMALS, KEY, OUTPUT, build_facts, read_facts, write_facts


@pytest.fixture(scope="module")
def facts():
    return build_facts()


def test_all_sources_combined(facts):
    assert facts.groupby("source").size().to_dict() == {
        "azure_costs.csv": 164,
        "aws_costs.csv": 161,
        "hoster_invoice.csv": 69,
        "ai_usage.csv": 322,
        "ai_subscriptions.csv": 237,
        "saas_contracts.csv": 308,
    }
    assert set(facts["category"]) == {"server", "cloud", "ai", "saas"}


def test_one_row_per_key(facts):
    assert not facts.duplicated(KEY).any()


def test_csv_round_trip(facts, tmp_path):
    back = read_facts(write_facts(facts, tmp_path / "facts.csv"))
    pd.testing.assert_frame_equal(
        back, facts.round({"usage_qty": DECIMALS, "cost_chf": DECIMALS}), check_dtype=False
    )


def test_committed_csv_is_up_to_date(facts):
    """Fails when a loader changed but data/derived/facts.csv was not rebuilt.

    Fix: cd backend && uv run python -m app.pipeline.build
    """
    committed = read_facts(OUTPUT)
    pd.testing.assert_frame_equal(
        committed, facts.round({"usage_qty": DECIMALS, "cost_chf": DECIMALS}), check_dtype=False
    )
