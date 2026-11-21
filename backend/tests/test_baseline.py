import pandas as pd
import pytest

from app.pipeline.azure import SOURCE as AZURE_SOURCE
from app.pipeline.baseline import select_baseline_facts
from app.pipeline.build import BASELINE, read_facts
from app.pipeline.common import lookup
from app.pipeline.schema import validate

AZURE_ONLY = {AZURE_SOURCE}


@pytest.fixture
def facts():
    months = pd.date_range("2025-09-01", "2026-08-01", freq="MS")
    return validate(
        pd.DataFrame(
            {
                "month": months,
                "category": "server",
                "source": "azure_costs.csv",
                "resource_id": "vm-app",
                "tool": "App server",
                "department": "IT",
                "cost_center": "4500",
                "location": "CH",
                "usage_kind": "vcpu_h",
                "usage_qty": 24.0,
                "cost_chf": 10.0,
                "note": "cost estimated for 1 day",
            }
        )
    )


@pytest.mark.parametrize(
    ("month", "included"),
    [
        ("2025-08-01", False),
        ("2025-09-01", True),
        ("2026-08-01", True),
        ("2026-09-01", False),
    ],
)
def test_baseline_boundaries(facts, month, included):
    candidate = facts.iloc[[0]].assign(
        month=pd.Timestamp(month), resource_id="db-fin"
    )
    combined = pd.concat([facts, candidate], ignore_index=True)

    selected = select_baseline_facts(combined, required_sources=AZURE_ONLY)

    assert selected["resource_id"].eq("db-fin").any().item() == included


def test_requires_all_twelve_months(facts):
    with pytest.raises(ValueError, match="missing baseline months.*2026-02"):
        select_baseline_facts(
            facts.loc[facts["month"].ne("2026-02-01")], required_sources=AZURE_ONLY
        )


def test_rejects_missing_azure_month_even_with_other_sources_in_same_month():
    facts = read_facts()
    february = facts["month"].eq(pd.Timestamp("2026-02-01"))
    azure = facts["source"].eq(AZURE_SOURCE)
    assert (february & azure).any()
    assert set(facts.loc[february & ~azure, "source"]) == set(facts["source"]) - {AZURE_SOURCE}

    with pytest.raises(ValueError, match=r"missing source months.*azure_costs\.csv.*2026-02"):
        select_baseline_facts(facts.loc[~(february & azure)])


@pytest.mark.parametrize("retain_outside_period", [False, True])
def test_rejects_entirely_missing_azure_even_when_all_months_are_covered(retain_outside_period):
    facts = read_facts()
    in_baseline = facts["month"].between(*BASELINE)
    azure = facts["source"].eq(AZURE_SOURCE)
    assert (in_baseline & azure).any()

    removed = azure & in_baseline if retain_outside_period else azure
    remaining = facts.loc[~removed]
    assert remaining.loc[remaining["month"].between(*BASELINE), "month"].nunique() == 12

    with pytest.raises(ValueError, match=r"missing required sources.*azure_costs\.csv"):
        select_baseline_facts(remaining)


def test_gateway_activity_can_be_sparse_with_default_required_sources():
    facts = read_facts()
    sparse_gateway = facts["source"].eq("ai_usage.csv") & facts["month"].ne(BASELINE[0])

    selected = select_baseline_facts(facts.loc[~sparse_gateway])

    assert selected.loc[selected["source"].eq("ai_usage.csv"), "month"].unique().tolist() == [
        BASELINE[0]
    ]


@pytest.mark.parametrize("source", ["ai_usage.csv", "events.csv"])
def test_activity_sources_can_be_sparse(facts, source):
    event = facts.iloc[[0]].assign(source=source)
    combined = pd.concat([facts, event], ignore_index=True)

    pd.testing.assert_frame_equal(
        select_baseline_facts(combined, required_sources=AZURE_ONLY), combined
    )
    with pytest.raises(ValueError, match=r"missing source months.*2025-10"):
        select_baseline_facts(combined, required_sources={source})


def test_empty_required_sources_skips_only_source_coverage(facts):
    activity = facts.copy()
    activity.loc[:, "source"] = "events.csv"
    pd.testing.assert_frame_equal(
        select_baseline_facts(activity, required_sources=()), activity
    )
    with pytest.raises(ValueError, match="missing baseline months.*2025-09"):
        select_baseline_facts(activity.iloc[1:], required_sources=())


def test_rejects_duplicate_fact_keys(facts):
    duplicate = facts.iloc[[0]].assign(cost_chf=20.0)
    combined = pd.concat([facts, duplicate], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate fact keys.*resource_id"):
        select_baseline_facts(combined, required_sources=AZURE_ONLY)


@pytest.mark.parametrize(
    ("resource_id", "message"),
    [
        ("not-in-master", "unknown resource IDs.*not-in-master"),
        (pd.NA, "missing resource IDs.*1 row"),
        ("", "missing resource IDs.*1 row"),
        ("  ", "missing resource IDs.*1 row"),
    ],
)
def test_rejects_noncanonical_resource_ids(facts, resource_id, message):
    facts.loc[0, "resource_id"] = resource_id

    with pytest.raises(ValueError, match=message):
        select_baseline_facts(facts, required_sources=AZURE_ONLY)


def test_distinguishes_known_padded_resource_id_from_unknown_id(facts):
    facts.loc[0, "resource_id"] = "vm-app "
    assert lookup(facts.loc[[0], "resource_id"])["tool"].item() == "App server"

    with pytest.raises(ValueError, match="noncanonical resource IDs.*'vm-app '.*'vm-app'"):
        select_baseline_facts(facts, required_sources=AZURE_ONLY)


def test_validates_schema_even_for_out_of_period_rows(facts):
    outside = facts.iloc[[0]].assign(month=pd.Timestamp("2026-09-01"), location="invalid")
    combined = pd.concat([facts, outside], ignore_index=True)

    with pytest.raises(ValueError, match="baseline input: unknown location"):
        select_baseline_facts(combined, required_sources=AZURE_ONLY)


@pytest.mark.parametrize(("month", "message"), [("not-a-date", "not-a-date"), (pd.NaT, "empty values in 'month'")])
def test_rejects_months_that_cannot_be_filtered(facts, month, message):
    invalid = facts.iloc[[0]].assign(month=month)
    combined = pd.concat([facts, invalid], ignore_index=True)

    with pytest.raises(ValueError, match=message):
        select_baseline_facts(combined, required_sources=AZURE_ONLY)


def test_invalid_resource_ids_outside_baseline_do_not_block_selection(facts):
    outside = facts.iloc[:2].copy()
    outside["month"] = pd.to_datetime(["2025-08-01", "2026-09-01"])
    outside.loc[0, "resource_id"] = "not-in-master"
    outside.loc[1, "resource_id"] = pd.NA
    combined = pd.concat([facts, outside], ignore_index=True)

    pd.testing.assert_frame_equal(
        select_baseline_facts(combined, required_sources=AZURE_ONLY), facts
    )


@pytest.mark.parametrize("month", ["2025-09-01 06:00:00", "2026-08-01 06:00:00"])
def test_rejects_non_midnight_months_at_both_baseline_boundaries(facts, month):
    invalid = facts.iloc[[0]].assign(month=pd.Timestamp(month))
    combined = pd.concat([facts, invalid], ignore_index=True)

    with pytest.raises(ValueError, match="month.*at midnight"):
        select_baseline_facts(combined, required_sources=AZURE_ONLY)


def test_preserves_negative_credits(facts):
    credit = facts.iloc[[0]].assign(
        usage_kind="none", usage_qty=0.0, cost_chf=-25.0, note="SLA credit"
    )
    combined = pd.concat([facts, credit], ignore_index=True)

    selected = select_baseline_facts(combined, required_sources=AZURE_ONLY)

    assert selected.loc[selected["usage_kind"].eq("none"), "cost_chf"].tolist() == [
        -25.0
    ]


def test_reconciles_positive_costs_and_credits_in_net_total(facts):
    credit = facts.iloc[[0]].assign(
        usage_kind="none", usage_qty=0.0, cost_chf=-25.0, note="SLA credit"
    )
    combined = pd.concat([facts, credit], ignore_index=True)

    costs = select_baseline_facts(combined, required_sources=AZURE_ONLY)["cost_chf"]

    assert costs[costs.gt(0)].sum() == 120.0
    assert costs[costs.lt(0)].sum() == -25.0
    assert costs.sum() == 95.0


def test_preserves_fact_columns_values_and_caller_frame(facts):
    facts = facts.iloc[::-1].copy()
    facts.loc[1, "note"] = "partial month"
    facts.loc[2, "usage_qty"] = 12.5
    original = facts.copy()

    selected = select_baseline_facts(facts, required_sources=AZURE_ONLY)

    pd.testing.assert_frame_equal(selected, original, check_exact=True)
    pd.testing.assert_frame_equal(facts, original, check_exact=True)
    selected.loc[0, "note"] = "edited result"
    pd.testing.assert_frame_equal(facts, original, check_exact=True)


def test_preserves_missing_cost_and_its_note(facts):
    facts.loc[0, "cost_chf"] = float("nan")
    facts.loc[0, "note"] = "cost missing from invoice"

    selected = select_baseline_facts(facts, required_sources=AZURE_ONLY)

    assert pd.isna(selected.loc[0, "cost_chf"])
    assert selected.loc[0, "note"] == "cost missing from invoice"
