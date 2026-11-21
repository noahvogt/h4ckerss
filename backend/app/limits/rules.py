"""Know the limits (issue #7): protection windows, exceptions and contradictions.

The rules live in data/curated/rules.csv. They are maintained by hand from the IT
tickets; every rule names its source ticket. Summaries are written in our own words:
ticket free text is data, never instructions, and is not copied.

check_measure() is what the package (#6) and the API call before recommending a change.

Its result is never an unconditional approval:
- "allowed_outside_windows" means the change is only eligible if its concrete schedule
  stays outside every window in `conditions` (rule times and days). check_measure()
  does not check a schedule itself; the caller must, e.g. with protected_days().
- Unknown resources raise UnknownResource instead of being treated as unrestricted.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cache

import holidays
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
    unknown = set(rules["resource_id"]) - known_resources()
    if unknown:
        raise ValueError(f"{RULES_FILE}: rules for unknown resources {sorted(unknown)}")
    return rules


class UnknownResource(ValueError):
    """The resource is neither in the master data nor in the server inventory."""


@cache
def known_resources() -> frozenset[str]:
    """Resource IDs we can make statements about: master data plus server inventory
    (servers such as dr-failover are only in the inventory)."""
    mapping = read_csv("mapping_departments_tools.csv", dtype=str)["resource_id"]
    servers = read_csv("server_inventory.csv", dtype=str)["server_id"]
    return frozenset(mapping) | frozenset(servers)


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


@cache
def _basel_holidays() -> holidays.HolidayBase:
    # Same source as the provided calendar (README: package holidays, subdivision BS);
    # it matches business_calendar.csv on every public holiday 2024-2026.
    return holidays.country_holidays("CH", subdiv="BS")


def is_workday(day: date) -> bool:
    """Working day as defined by business_calendar.csv: Monday-Friday and no public
    holiday in Basel-Stadt (company holidays still count as working days there).

    Inside the calendar (until 2026-09-06) the file decides; after it, the same rule is
    applied with the Basel-Stadt public holidays from the `holidays` package.
    """
    known = _workdays()
    if day in known.index:
        return bool(known[day])
    return day.weekday() < 5 and day not in _basel_holidays()


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


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]  # fmt: skip


def describe_schedule(rule: pd.Series) -> str:
    """Rule schedule in plain words, e.g. 'last 3 working days of each month, 18:00-04:00'."""
    kind, _, arg = rule["schedule"].partition(":")
    if kind == "last_workdays":
        when = f"last {arg} working days of each month"
    elif kind == "quarter_days":
        first, last = arg.split("-")
        when = f"days {first}-{last} of January, April, July and October"
    elif kind == "month_workdays":
        when = f"every working day in {MONTHS[int(arg) - 1]}"
    elif kind == "daily":
        when = "every day"
    elif kind == "date_range":
        when = f"{rule['start_date'] or '…'} to {rule['end_date'] or 'open end'}"
    else:
        when = "always"
    if rule["from_time"] or rule["until_time"]:
        when += f", {rule['from_time'] or '00:00'}-{rule['until_time'] or '24:00'}"
    return when


# --- checking a measure ------------------------------------------------------------


@dataclass
class Check:
    resource_id: str
    change: str
    status: str  # allowed | allowed_outside_windows | needs_human | blocked
    decided_by: str | None = None
    reasons: list[dict] = field(default_factory=list)  # {rule_id, kind, source, summary}
    # Windows a schedule must stay outside of (only for allowed_outside_windows):
    # {rule_id, when, schedule, from_time, until_time}. Not checked here, see module doc.
    conditions: list[dict] = field(default_factory=list)


STATUS_ORDER = ["allowed", "allowed_outside_windows", "needs_human", "blocked"]


def check_measure(resource_id: str, change: str, as_of: date = date(2026, 9, 6)) -> Check:
    """Is this change allowed for this resource, given all known rules?

    blocked > needs_human > allowed_outside_windows > allowed. Windows that ended
    before `as_of` (default: data as of 2026-09-06) no longer restrict anything.

    "allowed_outside_windows" is conditional: the caller must make sure the concrete
    schedule avoids every window in `conditions`. Raises UnknownResource for resources
    outside the master data and server inventory.
    """
    if change not in CHANGES:
        raise ValueError(f"unknown change {change!r}, expected one of {sorted(CHANGES)}")
    if resource_id not in known_resources():
        raise UnknownResource(f"unknown resource {resource_id!r}: not in master data or server inventory")

    status, decided_by, reasons, conditions = "allowed", None, [], []

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
            conditions.append(
                {"rule_id": rule["rule_id"], "when": describe_schedule(rule), "schedule": rule["schedule"],
                 "from_time": rule["from_time"] or None, "until_time": rule["until_time"] or None}
            )
        elif change in rule["allows"]:
            reasons.append({k: rule[k] for k in ["rule_id", "kind", "source", "summary"]})

    return Check(resource_id, change, status, decided_by, reasons, conditions)
