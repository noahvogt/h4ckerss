"""/api/baseline: cost, energy and CO2 of the baseline year (issue #4). Read-only."""

from functools import cache
from typing import Any

from fastapi import APIRouter

from app.pipeline.baseline_export import build_baseline_payload, load_calculated_baseline

router = APIRouter(prefix="/api/baseline", tags=["baseline"])


@cache
def _payload() -> dict[str, Any]:
    facts, _ = load_calculated_baseline()
    return build_baseline_payload(facts)


def warm_up() -> None:
    _payload()


@router.get("")
def baseline() -> dict[str, Any]:
    """The baseline year as documented in docs/baseline_calculation.md ("JSON contract").

    annual / monthly totals, breakdowns by location, department, tool and category, top
    drivers per metric, and `rows` for the map overview. Energy and CO2 come in low, mid
    and high scenarios with explicit coverage; missing numbers are null (unknown), not 0.
    Same numbers as submission/template_baseline_and_assumptions.csv."""
    return _payload()
