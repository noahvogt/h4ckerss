import pandas as pd
import pytest

from app.pipeline.schema import empty, validate


def row(**overrides):
    base = {
        "month": pd.Timestamp("2025-09-01"),
        "category": "server",
        "source": "azure_costs.csv",
        "resource_id": "vm-app",
        "tool": "App server",
        "department": "IT",
        "cost_center": "4500",
        "location": "CH",
        "usage_kind": "vcpu_h",
        "usage_qty": 720.0,
        "cost_chf": 100.0,
        "note": "",
    }
    return pd.DataFrame([base | overrides])


def test_valid_row_passes():
    assert len(validate(row())) == 1


def test_empty_table_passes():
    assert len(validate(empty())) == 0


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"location": "Zurich"}, "unknown location"),
        ({"usage_kind": "vCPU-hour"}, "unknown usage_kind"),
        ({"department": None}, "empty values in 'department'"),
        ({"month": pd.Timestamp("2025-09-15")}, "not on the 1st"),
        ({"cost_chf": None}, "without cost_chf and without a note"),
    ],
)
def test_invalid_rows_fail(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate(row(**overrides))


def test_missing_cost_with_note_passes():
    assert len(validate(row(cost_chf=None, note="cost missing"))) == 1
