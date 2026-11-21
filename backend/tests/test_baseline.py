import pandas as pd
import pytest

from app.pipeline.baseline import select_baseline_facts
from app.pipeline.schema import validate


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

    selected = select_baseline_facts(combined)

    assert selected["resource_id"].eq("db-fin").any().item() == included


def test_requires_all_twelve_months(facts):
    with pytest.raises(ValueError, match="missing baseline months.*2026-02"):
        select_baseline_facts(facts.loc[facts["month"].ne("2026-02-01")])


def test_rejects_duplicate_fact_keys(facts):
    duplicate = facts.iloc[[0]].assign(cost_chf=20.0)
    combined = pd.concat([facts, duplicate], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate fact keys.*resource_id"):
        select_baseline_facts(combined)


@pytest.mark.parametrize("resource_id", ["not-in-master", pd.NA])
def test_rejects_noncanonical_resource_ids(facts, resource_id):
    facts.loc[0, "resource_id"] = resource_id

    with pytest.raises(ValueError, match=f"unknown resource IDs.*{resource_id}"):
        select_baseline_facts(facts)


def test_preserves_negative_credits(facts):
    credit = facts.iloc[[0]].assign(
        usage_kind="none", usage_qty=0.0, cost_chf=-25.0, note="SLA credit"
    )
    combined = pd.concat([facts, credit], ignore_index=True)

    selected = select_baseline_facts(combined)

    assert selected.loc[selected["usage_kind"].eq("none"), "cost_chf"].tolist() == [
        -25.0
    ]


def test_preserves_fact_columns_values_and_caller_frame(facts):
    facts = facts.iloc[::-1].copy()
    original = facts.copy()

    selected = select_baseline_facts(facts)

    pd.testing.assert_frame_equal(selected, original)
    selected.loc[0, "note"] = "edited result"
    pd.testing.assert_frame_equal(facts, original)


def test_preserves_missing_cost_and_its_note(facts):
    facts.loc[0, "cost_chf"] = float("nan")
    facts.loc[0, "note"] = "cost missing from invoice"

    selected = select_baseline_facts(facts)

    assert pd.isna(selected.loc[0, "cost_chf"])
    assert selected.loc[0, "note"] == "cost missing from invoice"
