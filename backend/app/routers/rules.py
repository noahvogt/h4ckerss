"""/api/rules: protection windows, exceptions and measure checks (issue #7). Read-only."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.limits.rules import CHANGES, check_measure, load_rules, protected_days, rules_for

router = APIRouter(prefix="/api/rules", tags=["rules"])


class Rule(BaseModel):
    rule_id: str
    resource_id: str
    kind: str
    schedule: str
    start_date: date | None
    end_date: date | None
    until_time: str | None
    blocks: list[str]
    needs_human: list[str]
    allows: list[str]
    decided_by: str | None
    source: list[str]  # ticket ids
    summary: str


class Reason(BaseModel):
    rule_id: str
    kind: str
    source: str
    summary: str


class CheckResult(BaseModel):
    resource_id: str
    change: str
    status: str  # allowed | allowed_outside_windows | needs_human | blocked
    decided_by: str | None
    reasons: list[Reason]


class ProtectedDays(BaseModel):
    rule_id: str
    until_time: str | None
    days: list[date]


def _to_model(row: dict) -> Rule:
    blank_to_none = {k: (v or None) for k, v in row.items() if isinstance(v, str)}
    return Rule(**{**row, **blank_to_none, "source": row["source"].split(";"), "summary": row["summary"]})


@router.get("")
def list_rules(resource_id: str | None = None, kind: str | None = None) -> list[Rule]:
    """All rules, optionally filtered by resource or kind (e.g. ?kind=window)."""
    return [_to_model(r) for r in rules_for(resource_id, kind).to_dict("records")]


@router.get("/check")
def check(
    resource_id: str,
    change: str = Query(description=f"one of {sorted(CHANGES)}"),
) -> CheckResult:
    """May this change be made to this resource? With reasons and who decides."""
    if change not in CHANGES:
        raise HTTPException(422, f"unknown change {change!r}, expected one of {sorted(CHANGES)}")
    result = check_measure(resource_id, change)
    return CheckResult(**result.__dict__)


@router.get("/{rule_id}/days")
def days(rule_id: str, start: date, end: date) -> ProtectedDays:
    """Concrete protected days of a rule in a period, e.g. finance closing days."""
    rules = load_rules().set_index("rule_id")
    if rule_id not in rules.index:
        raise HTTPException(404, f"unknown rule {rule_id}")
    if end < start or (end - start).days > 3 * 366:
        raise HTTPException(422, "end must be after start and within 3 years")
    return ProtectedDays(
        rule_id=rule_id,
        until_time=rules.loc[rule_id, "until_time"] or None,
        days=protected_days(rule_id, start, end),
    )
