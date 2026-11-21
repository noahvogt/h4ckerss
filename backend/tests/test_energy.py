from sys import float_info

import pandas as pd
import pytest

from app.pipeline.baseline import select_baseline_facts
from app.pipeline.build import read_facts
from app.pipeline.energy import calculate_energy
from app.pipeline.factors import ResearchFactors, load_factors
from app.pipeline.schema import validate

ENERGY_COLUMNS = ["energy_kwh_low", "energy_kwh_mid", "energy_kwh_high"]


@pytest.fixture
def factors():
    energy = pd.DataFrame(
        [
            ("energy_per_vcpu_hour", 1, "kWh/vCPU-hour", True, 0.5, 1.0, 2.0),
            ("energy_per_1000_tokens", 1000, "kWh/1,000 tokens", False, 0.25, 0.5, 1.0),
            ("energy_per_subscription_message", 1, "kWh/message", False, 0.125, 0.25, 0.5),
        ],
        index=pd.Index(["vcpu_h", "tokens", "messages"], name="usage_kind"),
        columns=[
            "parameter",
            "usage_divisor",
            "factor_unit",
            "apply_pue",
            "value_low",
            "value_mid",
            "value_high",
        ],
    )
    pue = pd.Series({"value_low": 1.5, "value_mid": 2.0, "value_high": 3.0})
    return ResearchFactors(energy=energy, grid=pd.DataFrame(), pue=pue)


@pytest.fixture
def baseline():
    return validate(
        pd.DataFrame(
            {
                "month": pd.Timestamp("2025-09-01"),
                "category": ["server", "ai", "ai", "saas", "server"],
                "source": [
                    "azure_costs.csv",
                    "ai_usage.csv",
                    "ai_subscriptions.csv",
                    "saas_contracts.csv",
                    "azure_costs.csv",
                ],
                "resource_id": ["vm-app", "ai-assistant", "sub-chatgpt", "saas-other", "vm-app"],
                "tool": ["App server", "AI assistant", "ChatGPT Team", "Other SaaS", "App server"],
                "department": "IT",
                "cost_center": "4500",
                "location": ["CH", "EU", "EU", "EU", "CH"],
                "usage_kind": ["vcpu_h", "tokens", "messages", "seat_month", "none"],
                "usage_qty": [4.0, 2500.0, 4.0, 8.0, 0.0],
                "cost_chf": [100.0, 80.0, 175.0, 16.0, -25.0],
                "note": ["", "known tokens only", "", "", "SLA credit"],
            },
            index=[31, 8, 20, 4, 2],
        )
    )


@pytest.mark.parametrize(
    ("usage_kind", "expected", "parameter", "unit", "apply_pue"),
    [
        ("vcpu_h", [3.0, 8.0, 24.0], "energy_per_vcpu_hour", "kWh/vCPU-hour", True),
        ("tokens", [0.625, 1.25, 2.5], "energy_per_1000_tokens", "kWh/1,000 tokens", False),
        ("messages", [0.5, 1.0, 2.0], "energy_per_subscription_message", "kWh/message", False),
    ],
)
def test_calculates_scenario_energy_and_trace(
    baseline, factors, usage_kind, expected, parameter, unit, apply_pue
):
    fact = baseline.loc[baseline["usage_kind"].eq(usage_kind)]
    row = calculate_energy(fact, factors).iloc[0]

    assert row[ENERGY_COLUMNS].tolist() == expected
    assert row["energy_status"] == "calculated"
    assert row["energy_factor_parameter"] == parameter
    assert row["energy_factor_unit"] == unit
    assert row["energy_apply_pue"] == apply_pue


@pytest.mark.parametrize("usage_kind", ["gb_transfer", "capacity_day", "runner_min", "seat_month"])
def test_unsupported_energy_is_unknown(baseline, factors, usage_kind):
    fact = baseline.iloc[[3]].assign(usage_kind=usage_kind)
    row = calculate_energy(fact, factors).iloc[0]

    assert row["energy_status"] == "unknown"
    assert row[ENERGY_COLUMNS].isna().all()
    assert pd.isna(row["energy_factor_parameter"])
    assert pd.isna(row["energy_factor_unit"])
    assert pd.isna(row["energy_apply_pue"])


def test_cost_only_credit_has_missing_energy(baseline, factors):
    fact = baseline.iloc[[4]]
    row = calculate_energy(fact, factors).iloc[0]

    assert row["energy_status"] == "cost_only"
    assert row["cost_chf"] == -25.0
    assert row[ENERGY_COLUMNS].isna().all()


@pytest.mark.parametrize("usage_qty", [pd.NA, float("nan"), -1, float("inf"), float("-inf"), "bad"])
def test_invalid_usage_leaves_energy_unknown(baseline, factors, usage_qty):
    fact = baseline.iloc[[0]].assign(usage_qty=usage_qty)
    row = calculate_energy(fact, factors).iloc[0]

    assert row["energy_status"] == "unknown"
    assert row[ENERGY_COLUMNS].isna().all()
    assert row["energy_factor_parameter"] == "energy_per_vcpu_hour"


def test_valid_zero_usage_has_zero_energy(baseline, factors):
    fact = baseline.iloc[[0]].assign(usage_qty=0.0)
    row = calculate_energy(fact, factors).iloc[0]

    assert row["energy_status"] == "calculated"
    assert row[ENERGY_COLUMNS].tolist() == [0.0, 0.0, 0.0]


def test_rejects_overflow_from_finite_inputs(baseline, factors):
    fact = baseline.iloc[[0]].assign(usage_qty=float_info.max)
    # The vCPU midpoint factor and divisor are both 1, so PUE causes the overflow.
    assert float_info.max * float(factors.pue["value_mid"]) == float("inf")

    with pytest.raises(ValueError, match="energy_kwh_mid.*finite and nonnegative"):
        calculate_energy(fact, factors)


def test_preserves_original_fact_columns_order_and_caller(baseline, factors):
    original = baseline.copy()

    result = calculate_energy(baseline, factors)

    pd.testing.assert_frame_equal(result.iloc[:, : len(original.columns)], original)
    result.loc[31, "cost_chf"] = 0.0
    pd.testing.assert_frame_equal(baseline, original)


def test_duplicate_nonmonotonic_index_preserves_row_alignment(baseline, factors):
    baseline = baseline.set_axis(pd.Index([7, 2, 7, 2, 7], name="fact_index"))

    result = calculate_energy(baseline, factors)

    pd.testing.assert_frame_equal(result[baseline.columns], baseline)
    assert result["energy_status"].tolist() == [
        "calculated", "calculated", "calculated", "unknown", "cost_only"
    ]
    assert result["energy_kwh_mid"].iloc[:3].tolist() == [8.0, 1.25, 1.0]
    assert result["energy_kwh_mid"].iloc[3:].isna().all()


def test_real_baseline_reconciles_and_has_ordered_energy_scenarios():
    baseline = select_baseline_facts(read_facts())
    result = calculate_energy(baseline, load_factors())

    pd.testing.assert_frame_equal(result[baseline.columns], baseline)
    assert len(result) == 698
    assert result["month"].nunique() == 12
    assert result["cost_chf"].sum() == pytest.approx(470300.4703, rel=0, abs=1e-8)
    assert result["energy_status"].value_counts().to_dict() == {
        "calculated": 468,
        "unknown": 216,
        "cost_only": 14,
    }
    calculated = result["energy_status"].eq("calculated")
    values = result.loc[calculated, ENERGY_COLUMNS]
    assert values.ge(0).all().all()
    assert values.lt(float("inf")).all().all()
    low, mid, high = (values[column] for column in ENERGY_COLUMNS)
    assert low.le(mid).all()
    assert mid.le(high).all()
    assert result.loc[~calculated, ENERGY_COLUMNS].isna().all().all()
