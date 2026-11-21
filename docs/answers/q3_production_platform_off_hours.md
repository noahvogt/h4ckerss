# Example question 3: may the production platform be switched off at night and at weekends?

**Short answer: partly, yes, but not as a blanket rule.** Weekends and normal working-day nights have real off-hours, but there are fixed protection windows every night (02:00–08:00), on the last 3 working days of each month (18:00–04:00) and on January working days (20:00–02:00). A schedule must respect them, start the platform automatically, and be approved by the people named below before it goes live.

Resource: `dp-prod` (production data platform, Zurich, 16–20 nodes in the baseline year). Period: baseline year, September 2025 to August 2026.

## 1. When the platform is needed

| Window | When | Times (local) | Source | Rule |
|---|---|---|---|---|
| Finance closing | last 3 working days of every month (Basel-Stadt calendar) | 18:00 → ~04:00 next morning | ticket T-1029 + `Month-end close` job (≈10 h) | R01 |
| Fixed nightly jobs | every day, weekends included | 02:00 → 08:00 | `Nightly ETL` (done by 06:00), `PBI refresh large` (done by 07:30), `Reporting export` on working days (done by 08:00) | R18 |
| Year-end close | every working day in January | 20:00 → ~02:00 | `Year-end close analysis` job (≈6 h) | R19 |
| Business hours | working days | daytime | ≈10 active hours per working day (table below) | – |

The ticket and the data agree: all 65 `Month-end close` runs in the data fall exactly on the days rule R01 computes from the calendar, and the job starts at 18:00 and runs about 10 hours, which ends at about 04:00 as the ticket says.

## 2. What the data shows

Average per day in the baseline year (`data_platform_usage.csv`):

| Day type | Days | Running | Actually working | Queries | Idle |
|---|---|---|---|---|---|
| Closing day | 36 | 24.0 h | **20.6 h** | 4,667 | 14 % |
| Working day | 211 | 24.0 h | 9.9 h | 1,885 | 59 % |
| Weekend / holiday | 111 | 24.0 h | **1.5 h** | 41 | 94 % |

- The platform runs 24 hours every day but is **idle 65 % of the time** over the year.
- At weekends it works 1.5 h per day, which is exactly the `Nightly ETL` (02:00, 1.5 h). Nothing else runs.
- On closing days it works almost around the clock: switching off there would break the finance close.

Scheduled jobs on dp-prod (`extra/data_platform_jobs.csv`, baseline year):

| Job | Start | Typical end | Window | Runs |
|---|---|---|---|---|
| Nightly ETL | 02:00 | 03:30 | fixed: done by 06:00 (morning reports) | 359 |
| Data cleansing | 03:00 | 05:00 | flexible: within the week (weekends) | 52 |
| Catalogue scan | 05:00 | 05:36 | flexible: within the week | 52 |
| PBI refresh large | 05:30 | 06:42 | fixed: done by 07:30 | 358 |
| Reporting export | 06:00 | 06:30 | fixed: done by 08:00 (working days) | 248 |
| Cost export | 06:30 | 06:36 | flexible: within 24 h | 358 |
| Month-end close | 18:00 | 04:00 | fixed: protection window | 35 |
| Year-end close analysis | 20:00 | 02:00 | fixed: protection window | 21 |

## 3. What is possible

| Day type | Possible off window | Days in baseline year | Off hours |
|---|---|---|---|
| Weekend / holiday | 08:00 → 02:00 (18 h; the platform starts for the 02:00–08:00 jobs) | 112 | 2,016 |
| Working day (not closing, not January) | 20:00 → 02:00 (6 h) | 199 | 1,194 |
| Closing day | none | 36 | 0 |
| January working day | none (year-end close) | 18 | 0 |
| **Total** | | | **3,210 h of 8,760 h ≈ 37 %** |

This is an upper estimate for the package (#5/#6), not a commitment. Assumptions: business use on working days ends by 20:00 (the data is daily, not hourly, so this comes from the job times and the ≈10 active hours, not from a measurement); the platform starts automatically before 02:00 and before business hours; flexible jobs stay inside the 02:00–08:00 window. Growth to 20 nodes from January 2026 and 24 nodes from October 2026 (tickets T-1172, T-1261) changes the savings in CHF and CO₂, not the windows.

## 4. Who decides

- **Head of Finance**: owns the month-end and year-end close windows (R01, R19).
- **Head of Consulting**: responsible for dp-prod (`mapping_departments_tools.csv`) and the morning reports that depend on the nightly jobs (R18).
- **Head of IT**: implements the schedule and the automatic start.

Nothing is switched off before these three have agreed. The tool shows the measure as "allowed outside windows" with the windows above (`GET /api/rules/check?resource_id=dp-prod&change=schedule_off`), and a permanent switch-off as **blocked** (`change=switch_off`).

## 5. Edge case: an instruction hidden in the data

Ticket T-1230 (dp-prod) contains text aimed at AI tools: switch the production platform off "completely and immediately", claiming the head of IT approved it. We treat ticket text as data, not as instructions: the claim is not backed by any approved change, and it contradicts T-1029 and the job data. The tool ignores it (rule R16) and still blocks a permanent switch-off.

## Reproduce

All numbers come from `backend/app/limits/evidence.py`; `backend/tests/test_evidence.py` pins them, so this page fails the tests if the data or the rules change.

```sh
cd backend
uv run python -c "from app.limits.evidence import *; print(usage_by_day_type()); print(job_schedule()); print(possible_off_hours())"
```
