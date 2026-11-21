"""Evidence for protection windows from the data (example question 3, issue #7).

Backs docs/answers/q3_production_platform_off_hours.md. The numbers there are pinned
by tests/test_evidence.py, so the document cannot silently drift from the data.
"""

from datetime import date

import pandas as pd

from app.limits.rules import protected_days
from app.pipeline.common import read_csv

BASELINE = (date(2025, 9, 1), date(2026, 8, 31))


def _day_types(days: pd.Series, closing_rule: str = "R01") -> pd.Series:
    """closing day (rule R01) | workday | weekend/holiday, per date."""
    if days.empty:
        return pd.Series(dtype="string", index=days.index)
    cal = read_csv("business_calendar.csv", parse_dates=["date"]).set_index("date")["workday"]
    closing = set(protected_days(closing_rule, days.min().date(), days.max().date()))
    return pd.Series(
        [
            "closing day" if d.date() in closing else ("workday" if cal.get(d, 0) == 1 else "weekend/holiday")
            for d in days
        ],
        index=days.index,
    )


def usage_by_day_type(resource_id: str = "dp-prod", period: tuple[date, date] = BASELINE) -> pd.DataFrame:
    """Average daily runtime, active hours and queries per day type (data_platform_usage.csv)."""
    u = read_csv("data_platform_usage.csv", parse_dates=["date"]).drop_duplicates()
    u = u[(u["resource_id"] == resource_id) & u["date"].between(*map(pd.Timestamp, period))].copy()
    if u.empty:  # no platform usage data for this resource
        return pd.DataFrame()
    u["day_type"] = _day_types(u["date"])
    out = u.groupby("day_type").agg(
        days=("date", "nunique"),
        runtime_h=("runtime_h", "mean"),
        active_use_h=("active_use_h", "mean"),
        queries=("query_count", "mean"),
    )
    out["idle_share"] = 1 - out["active_use_h"] / out["runtime_h"]
    return out.reindex(["closing day", "workday", "weekend/holiday"])


def idle_share(resource_id: str = "dp-prod", period: tuple[date, date] = BASELINE) -> float:
    u = read_csv("data_platform_usage.csv", parse_dates=["date"]).drop_duplicates()
    u = u[(u["resource_id"] == resource_id) & u["date"].between(*map(pd.Timestamp, period))]
    return float(1 - u["active_use_h"].sum() / u["runtime_h"].sum())


def job_schedule(resource_id: str = "dp-prod", period: tuple[date, date] = BASELINE) -> pd.DataFrame:
    """Scheduled jobs: typical start, duration, end and on which day types they run
    (extra/data_platform_jobs.csv)."""
    j = read_csv("extra/data_platform_jobs.csv", parse_dates=["date"]).drop_duplicates()
    j = j[(j["resource_id"] == resource_id) & j["date"].between(*map(pd.Timestamp, period))].copy()
    if j.empty:  # no scheduled jobs for this resource
        return pd.DataFrame()
    j["day_type"] = _day_types(j["date"])
    out = j.groupby(["job_name", "time_window"]).agg(
        runs=("date", "size"),
        start=("start_time", lambda s: s.mode().iat[0]),
        duration_h=("duration_h", "median"),
        day_types=("day_type", lambda s: ", ".join(sorted(set(s)))),
    )
    start = pd.to_datetime(out["start"], format="%H:%M")
    out["typical_end"] = (start + pd.to_timedelta(out["duration_h"], unit="h")).dt.strftime("%H:%M")
    return out.reset_index().sort_values("start", ignore_index=True)


def closing_jobs_on_rule_days(resource_id: str = "dp-prod", job: str = "Month-end close") -> tuple[int, int]:
    """(runs of the job, of which on a day computed by rule R01) over the whole data period."""
    j = read_csv("extra/data_platform_jobs.csv", parse_dates=["date"]).drop_duplicates()
    runs = j[(j["resource_id"] == resource_id) & (j["job_name"] == job)]["date"].dt.date
    days = set(protected_days("R01", runs.min(), runs.max()))
    return len(runs), int(runs.isin(days).sum())


# Off windows that respect R01, R18 and R19 (see the answer document, section 3).
OFF_HOURS_PER_DAY = {"weekend/holiday": 18, "working day": 6, "closing day": 0, "January working day": 0}


def possible_off_hours(period: tuple[date, date] = BASELINE) -> pd.DataFrame:
    """Days and off hours per day type: weekends 08:00-02:00, working days 20:00-02:00,
    none on closing days (R01) and January working days (R19)."""
    from app.limits.rules import is_workday

    days = pd.date_range(*period).date
    closing = set(protected_days("R01", *period))

    def day_type(d: date) -> str:
        if d in closing:
            return "closing day"
        if not is_workday(d):
            return "weekend/holiday"
        return "January working day" if d.month == 1 else "working day"

    counts = pd.Series([day_type(d) for d in days]).value_counts()
    out = pd.DataFrame({"days": counts, "off_hours_per_day": pd.Series(OFF_HOURS_PER_DAY)})
    out["off_hours"] = out["days"] * out["off_hours_per_day"]
    return out.reindex(list(OFF_HOURS_PER_DAY)).rename_axis("day_type")
