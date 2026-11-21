"""Explanation of one recommendation for the frontend's explain box (issue #7).

Everything here is deterministic and built from the rules and the data: no AI text,
no copied ticket text. The package (#6) can add savings (CHF, kWh, CO2) on top.
"""

from datetime import date

import pandas as pd

from app.limits import evidence
from app.limits.rules import check_measure, describe_schedule, load_rules


def _headline(status: str, windows: list[dict], others: list[dict], decided_by: str | None) -> str:
    if status == "blocked":
        text = f"Blocked: {others[0]['summary'] if others else windows[0]['summary']}"
    elif status == "needs_human":
        text = f"Needs a human decision: {others[0]['summary']}"
    elif status == "allowed_outside_windows":
        text = (
            "Allowed only outside protection windows, the schedule must avoid: "
            + "; ".join(w["when"] for w in windows) + "."
        )
    elif others:
        text = f"Allowed and already agreed ({', '.join(others[0]['source'])})."
    else:
        text = "Allowed. No protection window or exception is known for this resource."
    return f"{text} Decided by: {decided_by}." if decided_by else text


def _records(df: pd.DataFrame | None) -> list[dict]:
    if df is None or df.empty:
        return []
    if not isinstance(df.index, pd.RangeIndex):  # named index (e.g. day_type) becomes a column
        df = df.reset_index()
    return df.round(2).to_dict("records")


def explain(resource_id: str, change: str, as_of: date = date(2026, 9, 6)) -> dict:
    check = check_measure(resource_id, change, as_of)
    rules = load_rules().set_index("rule_id")

    windows, others = [], []
    for reason in check.reasons:
        rule = rules.loc[reason["rule_id"]]
        item = {
            "rule_id": reason["rule_id"],
            "kind": reason["kind"],
            "when": describe_schedule(rule),
            "summary": reason["summary"],
            "source": reason["source"].split(";"),
        }
        (windows if reason["kind"] == "window" else others).append(item)

    usage = evidence.usage_by_day_type(resource_id)
    usage = usage.dropna(how="all")
    jobs = evidence.job_schedule(resource_id)
    return {
        "resource_id": resource_id,
        "change": change,
        "status": check.status,
        "decided_by": check.decided_by,
        "headline": _headline(check.status, windows, others, check.decided_by),
        "windows": windows,
        "reasons": others,
        "evidence": {
            "period": [d.isoformat() for d in evidence.BASELINE],
            "idle_share": round(evidence.idle_share(resource_id), 3) if not usage.empty else None,
            "usage_by_day_type": _records(usage),
            "jobs": _records(jobs),
            "possible_off_hours": _records(evidence.possible_off_hours()) if resource_id == "dp-prod" else [],
            "sources": [s for s, used in [("data_platform_usage.csv", not usage.empty),
                                          ("extra/data_platform_jobs.csv", not jobs.empty)] if used],
        },
    }
