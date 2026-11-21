import pandas as pd
import pytest

from app.pipeline.baseline import select_baseline_facts
from app.pipeline.build import read_facts
from app.pipeline.emissions import calculate_emissions
from app.pipeline.energy import calculate_energy
from app.pipeline.factors import load_factors
from app.pipeline.summary import rank_drivers, summarize_baseline

METRICS = [
    "cost_chf",
    "energy_kwh_low",
    "energy_kwh_mid",
    "energy_kwh_high",
    "co2e_kg_low",
    "co2e_kg_mid",
    "co2e_kg_high",
]


@pytest.fixture
def facts():
    return pd.DataFrame(
        [
            ("2025-09", "CH", "Finance", "AI", "ai", "tokens", 100, 1, 2, 3, 1, 2, 3,
             "calculated", "calculated", "incomplete token usage; known tokens only"),
            ("2025-10", "CH", "Finance", "AI", "ai", "tokens", -10, None, None, None,
             None, None, None, "cost_only", "cost_only", "credit"),
            ("2025-09", "DE", "IT", "Compute", "server", "compute", 20, 4, 8, 12, 0.5, 1, 1.5,
             "calculated", "calculated", ""),
            ("2025-10", "EU", "Sales", "CRM", "saas", "saas", 5, None, None, None,
             None, None, None, "unknown", "unknown", ""),
            ("2025-10", "unknown", "IT", "Compute", "server", "unlocated", 0, 2, 4, 6,
             None, None, None, "calculated", "unknown", ""),
            ("2025-10", "CH", "Overhead", "Fees", "cloud", "fees", -5, None, None, None,
             None, None, None, "cost_only", "cost_only", "credit"),
        ],
        columns=[
            "month", "location", "department", "tool", "category", "resource_id",
            *METRICS, "energy_status", "emissions_status", "note",
        ],
        index=[7, 2, 7, 3, 4, 5],
    ).assign(month=lambda frame: pd.to_datetime(frame["month"]))


def test_monthly_and_annual_subtotals_reconcile_without_losing_credits(facts):
    monthly = summarize_baseline(facts, by="month")
    annual = summarize_baseline(facts).iloc[0]

    assert monthly["cost_chf"].tolist() == [120, -10]
    assert monthly["fact_count"].tolist() == [2, 4]
    assert monthly.loc[1, "energy_kwh_mid"] == 4
    assert pd.isna(monthly.loc[1, "co2e_kg_mid"])
    assert monthly[METRICS].sum(min_count=1).tolist() == annual[METRICS].tolist()
    assert annual[METRICS].tolist() == [110, 7, 14, 21, 1.5, 3, 4.5]
    assert annual["fact_count"] == 6


@pytest.mark.parametrize(
    "by", ["location", "department", "tool", "category", ("month", "location", "tool")]
)
def test_grouped_subtotals_and_counts_reconcile_to_company(facts, by):
    grouped = summarize_baseline(facts, by=by)
    company = summarize_baseline(facts).iloc[0]

    assert grouped[METRICS].sum(min_count=1).tolist() == company[METRICS].tolist()
    assert grouped["fact_count"].sum() == company["fact_count"]


def test_keeps_missing_group_label_in_reconciliation(facts):
    facts = facts.copy()
    facts.iloc[0, facts.columns.get_loc("tool")] = None

    grouped = summarize_baseline(facts, by="tool")

    assert grouped.loc[grouped["tool"].isna(), "cost_chf"].tolist() == [100]
    assert grouped["fact_count"].sum() == len(facts)


def test_all_null_metrics_remain_unavailable(facts):
    row = summarize_baseline(facts.iloc[[3]].assign(cost_chf=float("nan"))).iloc[0]

    assert row[METRICS].isna().all()
    assert row[["cost_coverage", "energy_coverage", "emissions_coverage"]].tolist() == [
        "unavailable", "unavailable", "unavailable"
    ]


def test_energy_and_emissions_coverage_are_independent(facts):
    company = summarize_baseline(facts).iloc[0]

    assert company["cost_known_count"] == 6
    assert company["cost_unknown_count"] == 0
    assert company["cost_coverage"] == "complete"
    assert company["energy_calculated_count"] == 3
    assert company["energy_unknown_count"] == 1
    assert company["energy_cost_only_count"] == 2
    assert company["emissions_calculated_count"] == 2
    assert company["emissions_unknown_count"] == 2
    assert company["emissions_cost_only_count"] == 2
    assert company["energy_coverage"] == company["emissions_coverage"] == "partial"

    unlocated = summarize_baseline(facts.iloc[[4]]).iloc[0]
    assert unlocated["energy_coverage"] == "complete"
    assert unlocated["emissions_coverage"] == "unavailable"


def test_cost_only_rows_do_not_reduce_coverage(facts):
    combined = summarize_baseline(facts.iloc[:2].assign(note="")).iloc[0]
    assert combined["cost_chf"] == 90
    assert combined["energy_coverage"] == combined["emissions_coverage"] == "complete"
    assert combined["energy_cost_only_count"] == combined["emissions_cost_only_count"] == 1

    only_credit = summarize_baseline(facts.iloc[[1]]).iloc[0]
    assert only_credit["cost_chf"] == -10
    assert only_credit["energy_coverage"] == only_credit["emissions_coverage"] == "inapplicable"
    assert only_credit[METRICS[1:]].isna().all()


def test_partial_token_notes_reduce_coverage_even_with_numeric_estimates(facts):
    row = summarize_baseline(facts.iloc[:2]).iloc[0]

    assert row["partial_token_fact_count"] == 1
    assert row["energy_partial_usage_count"] == row["emissions_partial_usage_count"] == 1
    assert row["energy_unknown_count"] == row["emissions_unknown_count"] == 0
    assert row["energy_kwh_mid"] == row["co2e_kg_mid"] == 2
    assert row["energy_coverage"] == row["emissions_coverage"] == "partial"


@pytest.mark.parametrize("note", ["data for 29 of 31 days", "incomplete message usage; known messages only"])
def test_other_known_usage_gaps_are_reported_separately_from_tokens(facts, note):
    row = summarize_baseline(facts.iloc[[2]].assign(note=note)).iloc[0]
    assert row["partial_token_fact_count"] == 0
    assert row["energy_partial_usage_count"] == row["emissions_partial_usage_count"] == 1
    assert row["energy_coverage"] == row["emissions_coverage"] == "partial"


def test_partial_cost_note_and_missing_amount_keep_known_subtotal(facts):
    inputs = facts.iloc[:2].assign(cost_chf=[100.0, float("nan")], note="cost incomplete: missing days")
    row = summarize_baseline(inputs).iloc[0]
    assert row["cost_chf"] == 100
    assert row["cost_known_count"] == row["cost_unknown_count"] == row["cost_partial_count"] == 1
    assert row["cost_coverage"] == "partial"


@pytest.mark.parametrize(
    ("metric", "resources"),
    [
        ("cost_chf", ["tokens", "compute", "saas", "unlocated", "fees"]),
        ("energy_kwh", ["compute", "unlocated", "tokens"]),
        ("co2e_kg", ["tokens", "compute"]),
    ],
)
def test_ranks_each_metric_independently_and_preserves_coverage(facts, metric, resources):
    result = rank_drivers(facts, by="resource_id", metric=metric)
    assert result["resource_id"].tolist() == resources
    assert result["rank"].tolist() == list(range(1, len(resources) + 1))
    assert result.loc[result["resource_id"].eq("tokens"), "energy_coverage"].item() == "partial"


def test_rankings_keep_known_zero_and_exclude_unavailable_values(facts):
    zero_and_unknown = facts.iloc[[2, 3]].assign(
        energy_kwh_low=[0.0, None],
        energy_kwh_mid=[0.0, None],
        energy_kwh_high=[0.0, None],
    )
    ranked = rank_drivers(zero_and_unknown, by="resource_id", metric="energy_kwh")

    assert ranked["resource_id"].tolist() == ["compute"]
    assert ranked["energy_kwh_mid"].tolist() == [0.0]


@pytest.mark.parametrize(
    ("by", "labels"),
    [("department", ["Finance", "IT"]), ("tool", ["AI", "Compute"]), ("location", ["CH", "DE"])],
)
def test_ties_sort_by_group_label_even_when_input_order_changes(facts, by, labels):
    tied = facts.iloc[[2, 0]].assign(cost_chf=10)
    result = rank_drivers(tied, by=by, metric="cost_chf")

    assert result[by].tolist() == labels
    pd.testing.assert_frame_equal(result, rank_drivers(tied.iloc[::-1], by=by, metric="cost_chf"))
    assert rank_drivers(tied, by=by, metric="cost_chf", limit=1)[by].tolist() == labels[:1]


def test_empty_outputs_keep_schema(facts):
    empty = facts.iloc[:0]

    for by in ((), "month", ("location", "category")):
        result = summarize_baseline(empty, by=by)
        assert result.empty
        assert result.columns.tolist() == summarize_baseline(facts, by=by).columns.tolist()
    ranked = rank_drivers(empty, by="resource_id", metric="energy_kwh")
    assert ranked.empty
    assert ranked.columns.tolist() == rank_drivers(
        facts, by="resource_id", metric="energy_kwh"
    ).columns.tolist()


def test_input_immutability(facts):
    original = facts.copy()
    summarize_baseline(facts, by=("month", "location"))
    rank_drivers(facts, by="department", metric="co2e_kg")
    pd.testing.assert_frame_equal(facts, original)


def test_real_baseline_reconciles_and_preserves_ordered_scenarios():
    factors = load_factors()
    baseline = select_baseline_facts(read_facts())
    facts = calculate_emissions(calculate_energy(baseline, factors), factors)
    annual = summarize_baseline(facts).iloc[0]
    monthly = summarize_baseline(facts, by="month")

    assert annual["fact_count"] == 698
    assert len(monthly) == 12
    assert annual["cost_chf"] == pytest.approx(470300.4703, rel=0, abs=1e-8)
    assert annual["partial_token_fact_count"] == 134
    for metric in ("energy", "emissions"):
        assert annual[f"{metric}_calculated_count"] == 468
        assert annual[f"{metric}_unknown_count"] == 216
        assert annual[f"{metric}_cost_only_count"] == 14
        assert annual[f"{metric}_partial_usage_count"] == 183
        assert annual[f"{metric}_coverage"] == "partial"

    groupings = [monthly] + [
        summarize_baseline(facts, by=by) for by in ("location", "department", "tool", "category")
    ]
    for groups in groupings:
        assert groups["fact_count"].sum() == 698
        assert groups[METRICS].sum(min_count=1).tolist() == pytest.approx(annual[METRICS].tolist())
        for prefix in ("energy_kwh", "co2e_kg"):
            known = groups.loc[groups[f"{prefix}_mid"].notna()]
            assert known[f"{prefix}_low"].le(known[f"{prefix}_mid"]).all()
            assert known[f"{prefix}_mid"].le(known[f"{prefix}_high"]).all()
