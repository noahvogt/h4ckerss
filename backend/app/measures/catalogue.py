"""Measures catalogue (issue #5): candidate measures with effort and CHF savings.

Every measure names one resource and one change, so the rules (#7) can check it and
the explain box can show why. It also states how the energy-driving usage changes
(usage_factor = usage after / before, location_after), so the energy and CO2 savings
can be added from the calculation (#4) without touching this file. cost_factor is the
same for cost (cost after / before); it differs from usage_factor e.g. for a relocation
(same usage, other price) or for seats (fewer licences, same messages).

Conventions:
- CHF savings are per year. Usage-based measures use the baseline-year cost of the
  resource (Sep 2025 - Aug 2026, data/derived/facts.csv). Seat-based measures use the
  latest full month (August 2026) x 12, the current run rate.
- Effort is in person-days; 1 person-day = CHF 1,100 (case rules).
- Each measure is valid on its own against the baseline. Measures on the same resource
  interact (e.g. pause + relocate): the package (#6) combines them, it must not add
  their savings blindly.
"""

from datetime import date, timedelta
from math import ceil

import pandas as pd

from app.limits.evidence import possible_off_hours
from app.limits.rules import check_measure, is_workday, protected_days
from app.pipeline.build import BASELINE, read_facts
from app.pipeline.common import DATA_DIR, read_csv, to_chf

PERSON_DAY_CHF = 1_100
RUN_RATE_MONTH = pd.Timestamp("2026-08-01")
SEAT_HEADROOM = 0.10  # keep 10 % more seats than active users
HOURS_PER_YEAR = 8_760

# Effort in person-days, with the reason. Estimates for an SME IT team without a
# specialist department; the package can be recalculated if they change.
EFFORT = {
    "dp-prod schedule": (3.0, "scheduler with automatic start, test against finance close and nightly jobs, monitoring"),
    "cluster pause": (1.5, "auto-stop/auto-start policy for the cluster, keep quarterly training"),
    "dp-dev relocate": (4.0, "migrate cluster and data from Frankfurt to Zurich, test, switch over"),
    "gpu pause": (2.0, "start/stop on demand with a schedule, keep quarterly training"),
    "vm-test downsize": (1.0, "resize test environments 64 -> 16 vCPU after go-live, regression test"),
    "saas licences": (2.0, "licence review with 16 vendors, reduce seats at each renewal or notice date"),
    "ai seats": (0.5, "remove unused seats in the admin portal, inform users"),
    "chatgpt consolidation": (1.0, "move the remaining users to Claude/Copilot, cancel ChatGPT Team"),
    "ai model routing": (2.0, "route simple tasks to small models in the AI gateway, quality check on samples"),
}

SIMPLE_AI_TASKS = ["Classify", "Summarise", "Translate"]  # small models are enough


def _baseline() -> pd.DataFrame:
    facts = read_facts()
    return facts[facts["month"].between(*BASELINE)]


def _resource_cost(baseline: pd.DataFrame, resource_id: str) -> tuple[float, float, str, str]:
    """(cost_chf, usage_qty, usage_kind, location) of a resource's usage in the baseline year.

    Cost-only rows (SLA credits, fees) are left out: a measure changes usage, not credits.
    """
    rows = baseline[(baseline["resource_id"] == resource_id) & (baseline["usage_kind"] != "none")]
    return (
        float(rows["cost_chf"].sum()),
        float(rows["usage_qty"].sum()),
        rows["usage_kind"].mode().iat[0],
        rows["location"].mode().iat[0],
    )


def kept_hours_on_demand(training_rule: str, workday_hours: int = 10) -> float:
    """Running hours per baseline year when a resource runs only on working days
    (08:00-18:00) and around the clock on the quarterly training days of `training_rule`."""
    start, end = (d.date() for d in BASELINE)
    end = date(end.year, end.month, 1) + timedelta(days=31)
    end = date(end.year, end.month, 1) - timedelta(days=1)  # last day of the baseline year
    training = set(protected_days(training_rule, start, end))
    hours = 0.0
    day = start
    while day <= end:
        hours += 24 if day in training else (workday_hours if is_workday(day) else 0)
        day += timedelta(days=1)
    return hours


def _usage_measure(baseline, measure_id, title, resource_id, change, usage_factor, effort_key,
                   assumptions, sources, risks, location_after=None, cost_factor=None):
    cost, qty, kind, location = _resource_cost(baseline, resource_id)
    effort_pd, effort_why = EFFORT[effort_key]
    cost_factor = usage_factor if cost_factor is None else cost_factor
    return {
        "measure_id": measure_id, "title": title, "resource_id": resource_id, "change": change,
        "usage_kind": kind, "location": location, "location_after": location_after or location,
        "baseline_qty": qty, "usage_factor": usage_factor, "cost_factor": cost_factor, "baseline_cost_chf": cost,
        "savings_cost_chf_per_year": cost * (1 - cost_factor),
        "effort_person_days": effort_pd, "effort_why": effort_why,
        "assumptions": assumptions, "sources": sources, "risks": risks,
    }


def _seat_measures() -> list[dict]:
    """Unused AI seats and SaaS licences, at the August 2026 run rate."""
    out = []

    ai = read_csv("ai_subscriptions.csv", parse_dates=["month"], dtype={"cost_center": str})
    saas = read_csv("saas_contracts.csv", parse_dates=["month"], dtype={"cost_center": str})
    ai = ai.rename(columns={"product": "item", "price_per_seat": "price"})
    saas = saas.rename(columns={"contract": "item", "price_per_licence": "price"})

    def run_rate(df: pd.DataFrame) -> pd.DataFrame:
        df = df[(df["month"] == RUN_RATE_MONTH) & (df["contract_status"] == "Final")].copy()
        df["price_chf"] = to_chf(df["price"], df["currency"], df["month"])
        g = df.groupby("item").agg(
            bought=("licences_purchased", "sum"), active=("licences_active_30d", "sum"),
            price_chf=("price_chf", "median"), contract_end=("contract_end", "max"),
            notice_days=("notice_period_days", "max"), billing=("billing", "first"),
        )
        g["keep"] = [min(b, ceil(a * (1 + SEAT_HEADROOM))) for a, b in zip(g["active"], g["bought"])]
        g["cut"] = g["bought"] - g["keep"]
        g["savings"] = g["cut"] * g["price_chf"] * 12
        g["year_cost"] = g["bought"] * g["price_chf"] * 12
        return g

    a = run_rate(ai)
    for resource_id, product in [("sub-copilot", "Microsoft Copilot"), ("sub-claude", "Claude Team")]:
        r = a.loc[product]
        effort_pd, effort_why = EFFORT["ai seats"]
        out.append({
            "measure_id": f"M-{resource_id}", "title": f"Cancel unused {product} seats",
            "resource_id": resource_id, "change": "cancel_seats", "usage_kind": "messages",
            "location": "EU", "location_after": "EU", "baseline_qty": float(r["bought"]),
            "usage_factor": 1.0,  # messages of active users stay the same
            "cost_factor": r["keep"] / r["bought"],
            "baseline_cost_chf": r["year_cost"], "savings_cost_chf_per_year": r["savings"],
            "effort_person_days": effort_pd, "effort_why": effort_why,
            "assumptions": f"August 2026: {int(r['bought'])} seats bought, {int(r['active'])} active in 30 days; "
                           f"keep {int(r['keep'])} (active + {SEAT_HEADROOM:.0%} headroom), cancel {int(r['cut'])} "
                           f"at CHF {r['price_chf']:.2f}/seat/month. Monthly billing, effective next month.",
            "sources": "ai_subscriptions.csv, exchange_rates.csv",
            "risks": "Seats are ordered per department (T-1128): agree the cut with each department head.",
        })

    chat = a.loc["ChatGPT Team"]
    claude_price = a.loc["Claude Team", "price_chf"]
    moved = int(chat["active"])
    effort_pd, effort_why = EFFORT["chatgpt consolidation"]
    out.append({
        "measure_id": "M-sub-chatgpt", "title": "Consolidate ChatGPT Team into the existing Claude/Copilot subscriptions",
        "resource_id": "sub-chatgpt", "change": "cancel_seats", "usage_kind": "messages",
        "location": "EU", "location_after": "EU", "baseline_qty": float(chat["bought"]),
        "usage_factor": 1.0,  # the active users keep working, on another tool
        "cost_factor": moved * claude_price / (chat["bought"] * chat["price_chf"]),
        "baseline_cost_chf": chat["year_cost"],
        "savings_cost_chf_per_year": chat["year_cost"] - moved * claude_price * 12,
        "effort_person_days": effort_pd, "effort_why": effort_why,
        "assumptions": f"August 2026: {int(chat['bought'])} ChatGPT seats, {moved} active. Cancel all; the {moved} "
                       f"active users get a Claude Team seat (CHF {claude_price:.2f}/month).",
        "sources": "ai_subscriptions.csv, it_tickets.csv (T-1090 and others: 'same benefit already exists')",
        "risks": "Contradicting decisions in the tickets (rule R15): management decides.",
    })

    s = run_rate(saas)
    for resource_id, items in [("saas-m365", ["Microsoft 365"]), ("saas-other", [i for i in s.index if i != "Microsoft 365"])]:
        rows = s.loc[items]
        effort_pd, effort_why = EFFORT["saas licences"] if resource_id == "saas-other" else (0.5, "reduce Microsoft 365 seats at renewal")
        latest = rows["contract_end"].max()
        out.append({
            "measure_id": f"M-{resource_id}", "title": "Cancel unused SaaS licences at renewal" if resource_id == "saas-other"
            else "Reduce unused Microsoft 365 licences at renewal",
            "resource_id": resource_id, "change": "cancel_seats", "usage_kind": "seat_month",
            "location": "EU", "location_after": "EU", "baseline_qty": float(rows["bought"].sum() * 12),
            "usage_factor": float(rows["keep"].sum() / rows["bought"].sum()),
            "cost_factor": float(1 - rows["savings"].sum() / rows["year_cost"].sum()),
            "baseline_cost_chf": float(rows["year_cost"].sum()), "savings_cost_chf_per_year": float(rows["savings"].sum()),
            "effort_person_days": effort_pd, "effort_why": effort_why,
            "assumptions": f"August 2026: {int(rows['bought'].sum())} licences bought, {int(rows['active'].sum())} active "
                           f"in 30 days across {len(rows)} contract(s); keep active + {SEAT_HEADROOM:.0%}, cancel "
                           f"{int(rows['cut'].sum())}. Full effect once every contract has renewed (latest {latest}).",
            "sources": "saas_contracts.csv, exchange_rates.csv",
            "risks": "Annual contracts can only shrink at renewal; notice periods 30-90 days must be met.",
        })
    return out


def _ai_model_routing(baseline: pd.DataFrame) -> list[dict]:
    """Simple AI tasks on large models -> small models, priced per provider."""
    ai = read_csv("ai_usage.csv", parse_dates=["date"]).drop_duplicates()
    ai = ai[ai["date"].between(*BASELINE[0:1] + (pd.Timestamp("2026-08-31"),))]
    tokens = ai["tokens_in"] + ai["tokens_out"].fillna(0)
    ai = ai.assign(tokens=tokens)
    price = ai.groupby(["provider", "model_class"]).apply(
        lambda x: x["cost_chf"].sum() / x["tokens"].sum(), include_groups=False
    ).unstack()
    ratio = (price["small"] / price["large"]).dropna()  # providers that offer both
    simple = ai[ai["task_type"].isin(SIMPLE_AI_TASKS) & (ai["model_class"] == "large") & ai["provider"].isin(ratio.index)]
    simple = simple.assign(savings=simple["cost_chf"] * (1 - simple["provider"].map(ratio)))
    out = []
    for resource_id, rows in simple.groupby("resource_id"):
        if rows["savings"].sum() < 1_000:  # not worth a separate change
            continue
        cost, qty, kind, location = _resource_cost(baseline, resource_id)
        effort_pd, effort_why = EFFORT["ai model routing"]
        out.append({
            "measure_id": f"M-{resource_id}-model", "title": f"Route simple tasks of {resource_id} to small models",
            "resource_id": resource_id, "change": "downsize", "usage_kind": kind, "location": location,
            "location_after": location, "baseline_qty": qty,
            "usage_factor": 1.0,  # same tokens, smaller model: energy per token differs (see #4)
            "cost_factor": 1 - float(rows["savings"].sum()) / cost,
            "baseline_cost_chf": cost, "savings_cost_chf_per_year": float(rows["savings"].sum()),
            "effort_person_days": effort_pd, "effort_why": effort_why,
            "assumptions": f"Tasks {', '.join(sorted(rows['task_type'].unique()))} on large models "
                           f"(CHF {rows['cost_chf'].sum():,.0f} in the baseline year) move to the provider's small "
                           f"model; price ratio small/large from the gateway: "
                           + ", ".join(f"{p} {r:.2f}" for p, r in ratio.items()) + ".",
            "sources": "ai_usage.csv",
            "risks": "Quality must be checked on samples per task before switching.",
        })
    return out


def build_catalogue() -> pd.DataFrame:
    """All candidate measures with effort, CHF savings and the rule check."""
    b = _baseline()
    dev_kept = kept_hours_on_demand("R02") / HOURS_PER_YEAR
    gpu_kept = kept_hours_on_demand("R04") / HOURS_PER_YEAR
    off = possible_off_hours()["off_hours"].sum()

    dev_price = _resource_cost(b, "dp-dev")
    prod_price = _resource_cost(b, "dp-prod")
    price_ratio = (prod_price[0] / prod_price[1]) / (dev_price[0] / dev_price[1])  # CHF/node-h CH vs DE

    rows = [
        _usage_measure(
            b, "M-dp-prod-schedule", "Switch the production platform off at nights and weekends, outside protection windows",
            "dp-prod", "schedule_off", 1 - off / HOURS_PER_YEAR, "dp-prod schedule",
            f"Off weekends 08:00-02:00 and working days 20:00-02:00; never on closing days or January working "
            f"days: {off:,.0f} of {HOURS_PER_YEAR:,} h per year. Node-hours fall in proportion.",
            "data_platform_usage.csv, extra/data_platform_jobs.csv, it_tickets.csv (T-1029); docs/answers/q3_production_platform_off_hours.md",
            "Upper estimate: assumes no business use after 20:00. Automatic start before 02:00 and before office hours.",
        ),
        _usage_measure(
            b, "M-dp-dev-pause", "Run the development cluster only on working days 08:00-18:00 and during quarterly training",
            "dp-dev", "pause", dev_kept, "cluster pause",
            f"Running {dev_kept * HOURS_PER_YEAR:,.0f} of {HOURS_PER_YEAR:,} h: working days 08:00-18:00 plus 24 h on "
            f"training days. The cluster is idle 91 % today and its jobs may run between 08:00 and 18:00.",
            "data_platform_usage.csv, extra/data_platform_jobs.csv, it_tickets.csv (T-1053)",
            "Training must start automatically on days 1-3 of each quarter (rule R02).",
        ),
        _usage_measure(
            b, "M-dp-dev-relocate", "Move the development cluster from Frankfurt to Zurich",
            "dp-dev", "relocate", 1.0, "dp-dev relocate",
            f"Same node-hours at the Zurich price of the production cluster: CHF {prod_price[0] / prod_price[1]:.3f} "
            f"vs. CHF {dev_price[0] / dev_price[1]:.3f} per node-hour in Frankfurt. The CHF effect is small or "
            f"negative; the measure is about CO2 (Swiss vs. German grid).",
            "azure_costs.csv, it_tickets.csv (T-1074: moving is technically possible)",
            "Data transfer and a short downtime during migration.",
            location_after="CH", cost_factor=price_ratio,
        ),
        _usage_measure(
            b, "M-gpu-ml-pause", "Start the GPU server only when needed: working days 08:00-18:00 and quarterly training",
            "gpu-ml", "pause", gpu_kept, "gpu pause",
            f"Running {gpu_kept * HOURS_PER_YEAR:,.0f} of {HOURS_PER_YEAR:,} h. Average GPU load is 6 % outside "
            f"the four training weeks (about 43 % in them).",
            "server_metrics_weekly.csv, azure_costs.csv, it_tickets.csv (T-1035, T-1101)",
            "Training days 1-3 of each quarter stay protected (rule R04).",
        ),
        _usage_measure(
            b, "M-vm-test-downsize", "Scale the test environments back from 64 to 16 vCPU",
            "vm-test", "downsize", 16 / 64, "vm-test downsize",
            "Enlarged from 16 to 64 vCPU for the customer portal project with scale-back planned after go-live "
            "(T-1058). CPU load of the test servers is 2-7 %.",
            "aws_costs.csv, server_inventory.csv, it_tickets.csv (T-1058)",
            "Confirm the go-live has happened; keep the acceptance-test freeze rule (R09) in mind for new releases.",
        ),
        *_seat_measures(),
        *_ai_model_routing(b),
    ]

    cat = pd.DataFrame(rows)
    cat["effort_chf"] = cat["effort_person_days"] * PERSON_DAY_CHF
    checks = [check_measure(r, c) for r, c in zip(cat["resource_id"], cat["change"])]
    cat["status"] = [c.status for c in checks]
    cat["decided_by"] = [c.decided_by for c in checks]
    cat["conditions"] = ["; ".join(f"{x['rule_id']} {x['when']}" for x in c.conditions) for c in checks]
    return cat.round({"usage_factor": 4, "cost_factor": 4, "baseline_cost_chf": 2, "savings_cost_chf_per_year": 2})


OUTPUT = DATA_DIR.parent / "derived" / "measures.csv"


def write_catalogue(cat: pd.DataFrame, path=OUTPUT):
    path.parent.mkdir(parents=True, exist_ok=True)
    cat.sort_values("savings_cost_chf_per_year", ascending=False).to_csv(path, index=False)
    return path


def main() -> None:
    cat = build_catalogue()
    path = write_catalogue(cat)
    view = cat.sort_values("savings_cost_chf_per_year", ascending=False)
    print(view[["measure_id", "status", "effort_person_days", "savings_cost_chf_per_year"]].to_string(index=False))
    print(f"\n{len(cat)} measures, CHF {cat['savings_cost_chf_per_year'].sum():,.0f}/year if all were done, "
          f"{cat['effort_person_days'].sum():g} person-days")
    print(f"written: {path}")


if __name__ == "__main__":
    main()
