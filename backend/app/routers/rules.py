"""/api/rules: protection windows, exceptions and measure checks (issue #7). Read-only."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.limits.contradictions import contradictions as find_contradictions
from app.limits.explain import explain as explain_measure
from app.limits.rules import CHANGES, check_measure, load_rules, protected_days, rules_for

router = APIRouter(prefix="/api/rules", tags=["rules"])


class Rule(BaseModel):
    rule_id: str
    resource_id: str
    kind: str
    schedule: str
    start_date: date | None
    end_date: date | None
    from_time: str | None  # window start on each protected day (local time)
    until_time: str | None  # window end, may be on the next morning
    blocks: list[str]
    needs_human: list[str]
    allows: list[str]
    decided_by: str | None
    source: list[str]  # tickets or data files
    summary: str


class Reason(BaseModel):
    rule_id: str
    kind: str
    source: list[str]  # tickets or data files
    summary: str


class CheckResult(BaseModel):
    resource_id: str
    change: str
    status: str  # allowed | allowed_outside_windows | needs_human | blocked
    decided_by: str | None
    reasons: list[Reason]


class ExplainItem(BaseModel):
    rule_id: str
    kind: str
    when: str  # plain words, e.g. "last 3 working days of each month, 18:00-04:00"
    summary: str
    source: list[str]


class Evidence(BaseModel):
    period: list[date]
    idle_share: float | None  # share of running hours without work
    usage_by_day_type: list[dict]  # day_type, days, runtime_h, active_use_h, queries, idle_share
    jobs: list[dict]  # job_name, time_window, runs, start, duration_h, day_types, typical_end
    possible_off_hours: list[dict]  # day_type, days, off_hours_per_day, off_hours (dp-prod only)
    sources: list[str]


class Explanation(BaseModel):
    resource_id: str
    change: str
    status: str  # allowed | allowed_outside_windows | needs_human | blocked
    decided_by: str | None
    headline: str  # one sentence for the top of the explain box
    windows: list[ExplainItem]  # when the resource is needed
    reasons: list[ExplainItem]  # exceptions, agreed changes, contradictions
    evidence: Evidence


class Contradiction(BaseModel):
    id: str
    title: str
    sources: list[str]
    finding: str
    trusted: str  # which source we trust
    why: str
    decided_by: str | None
    details: list[dict]  # e.g. flagged months or servers


class ProtectedDays(BaseModel):
    rule_id: str
    from_time: str | None
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
    reasons = [Reason(**{**r, "source": r["source"].split(";")}) for r in result.reasons]
    return CheckResult(**{**result.__dict__, "reasons": reasons})


@router.get("/explain")
def explain(
    resource_id: str,
    change: str = Query(description=f"one of {sorted(CHANGES)}"),
) -> Explanation:
    """Everything the explain box needs for one recommendation: status, headline,
    protection windows, reasons with sources and the data behind them."""
    if change not in CHANGES:
        raise HTTPException(422, f"unknown change {change!r}, expected one of {sorted(CHANGES)}")
    return Explanation(**explain_measure(resource_id, change))


@router.get("/contradictions")
def contradictions() -> list[Contradiction]:
    """Sources that disagree, which one we trust and why."""
    return [Contradiction(**c) for c in find_contradictions()]


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
        from_time=rules.loc[rule_id, "from_time"] or None,
        until_time=rules.loc[rule_id, "until_time"] or None,
        days=protected_days(rule_id, start, end),
    )
