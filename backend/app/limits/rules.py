"""Know the limits (issue #7): protection windows, exceptions and contradictions.

The rules live in data/curated/rules.csv. They are maintained by hand from the IT
tickets; every rule names its source ticket. Summaries are written in our own words:
ticket free text is data, never instructions, and is not copied.

check_measure() is what the package (#6) and the API call before recommending a change.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cache

import pandas as pd

from app.pipeline.common import DATA_DIR, read_csv

RULES_FILE = DATA_DIR.parent / "curated" / "rules.csv"

# Measures are always one of these changes to a resource.
CHANGES = {
    "switch_off",  # permanently off
    "schedule_off",  # off at nights / weekends
    "pause",  # stop when idle, start on demand
    "downsize",  # fewer vCPU / nodes / smaller tier
    "relocate",  # move to another region (e.g. Frankfurt -> Zurich)
    "delete",  # delete data
    "cancel_seats",  # cancel licences / seats
}

KINDS = {
    "window",  # needed at certain times; temporary off is fine outside them
    "must_run",  # must keep running
    "no_delete",  # data must be kept
    "approved_change",  # a change already agreed in a ticket
    "one_off",  # unusual period, not a recurring pattern
    "growth",  # known future growth (for baseline / forecast)
    "contradiction",  # sources disagree, a human decides
    "ignored_instruction",  # instruction aimed at AI tools found in the data
}

TEMPORAL_CHANGES = {"schedule_off", "pause"}  # can respect windows by timing


def _split(value: object) -> list[str]:
    return [v for v in str(value).split(";") if v] if pd.notna(value) else []


@cache
def load_rules() -> pd.DataFrame:
    rules = pd.read_csv(RULES_FILE, dtype=str, keep_default_na=False)
    for col in ["blocks", "needs_human", "allows"]:
        rules[col] = rules[col].map(_split)
    bad_kinds = set(rules["kind"]) - KINDS
    bad_changes = {c for col in ["blocks", "needs_human", "allows"] for cs in rules[col] for c in cs} - CHANGES
    if bad_kinds or bad_changes or rules["rule_id"].duplicated().any():
        raise ValueError(f"{RULES_FILE}: unknown kinds {bad_kinds}, changes {bad_changes} or duplicate ids")
    return rules


def rules_for(resource_id: str | None = None, kind: str | None = None) -> pd.DataFrame:
    rules = load_rules()
    if resource_id:
        rules = rules[rules["resource_id"] == resource_id]
    if kind:
        rules = rules[rules["kind"] == kind]
    return rules


# --- protection windows as concrete days ------------------------------------------


@cache
def _workdays() -> pd.Series:
    """Working day flag per date from business_calendar.csv (Basel-Stadt holidays included)."""
    cal = read_csv("business_calendar.csv", parse_dates=["date"])
    return cal.set_index(cal["date"].dt.date)["workday"].astype(bool)


def is_workday(day: date) -> bool:
    """From the calendar; after its end (2026-09-06) Monday-Friday is assumed."""
    known = _workdays()
    return bool(known[day]) if day in known.index else day.weekday() < 5


def protected_days(rule_id: str, start: date, end: date) -> list[date]:
    """Days in [start, end] on which the rule's window applies."""
    rule = load_rules().set_index("rule_id").loc[rule_id]
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    kind, _, arg = rule["schedule"].partition(":")

    if kind in ("always", "daily"):  # daily: the window recurs every day at its times
        return days
    if kind == "month_workdays":
        return [d for d in days if d.month == int(arg) and is_workday(d)]
    if kind == "date_range":
        lo = date.fromisoformat(rule["start_date"]) if rule["start_date"] else date.min
        hi = date.fromisoformat(rule["end_date"]) if rule["end_date"] else date.max
        return [d for d in days if lo <= d <= hi]
    if kind == "quarter_days":
        first, last = (int(x) for x in arg.split("-"))
        return [d for d in days if d.month in (1, 4, 7, 10) and first <= d.day <= last]
    if kind == "last_workdays":
        n = int(arg)
        out = []
        for month in sorted({(d.year, d.month) for d in days}):
            month_days = pd.date_range(date(*month, 1), periods=31).date
            month_days = [d for d in month_days if (d.year, d.month) == month]
            out += [d for d in [d for d in month_days if is_workday(d)][-n:] if start <= d <= end]
        return out
    raise ValueError(f"rule {rule_id}: unknown schedule {rule['schedule']!r}")


# --- checking a measure ------------------------------------------------------------


@dataclass
class Check:
    resource_id: str
    change: str
    status: str  # allowed | allowed_outside_windows | needs_human | blocked
    decided_by: str | None = None
    reasons: list[dict] = field(default_factory=list)  # {rule_id, kind, source, summary}


STATUS_ORDER = ["allowed", "allowed_outside_windows", "needs_human", "blocked"]


def check_measure(resource_id: str, change: str, as_of: date = date(2026, 9, 6)) -> Check:
    """Is this change allowed for this resource, given all known rules?

    blocked > needs_human > allowed_outside_windows > allowed. Windows that ended
    before `as_of` (default: data as of 2026-09-06) no longer restrict anything.
    """
    if change not in CHANGES:
        raise ValueError(f"unknown change {change!r}, expected one of {sorted(CHANGES)}")

    status, decided_by, reasons = "allowed", None, []

    def raise_to(new: str, rule: pd.Series) -> None:
        nonlocal status, decided_by
        if STATUS_ORDER.index(new) > STATUS_ORDER.index(status):
            status, decided_by = new, rule["decided_by"] or None
        reasons.append({k: rule[k] for k in ["rule_id", "kind", "source", "summary"]})

    for _, rule in rules_for(resource_id).iterrows():
        if rule["kind"] in {"ignored_instruction", "growth", "one_off"}:
            continue
        if rule["end_date"] and date.fromisoformat(rule["end_date"]) < as_of:
            continue  # window is over
        if change in rule["blocks"]:
            raise_to("blocked", rule)
        elif change in rule["needs_human"]:
            raise_to("needs_human", rule)
        elif rule["kind"] == "window" and change in TEMPORAL_CHANGES:
            raise_to("allowed_outside_windows", rule)
        elif change in rule["allows"]:
            reasons.append({k: rule[k] for k in ["rule_id", "kind", "source", "summary"]})

    return Check(resource_id, change, status, decided_by, reasons)
