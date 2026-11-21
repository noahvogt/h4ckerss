"""Example question 2: what does it bring to start the GPU server only when needed?

Backs docs/answers/q2_gpu_on_demand.md; tests/test_gpu.py pins the numbers. The savings are
the ones of measure M-gpu-ml-pause in the catalogue and the package (same calculation).

Two ways to count the energy saved:
- per running hour (used in the catalogue and package): the energy per GPU-hour of the
  research factors is the average power of a running server, so energy falls with the
  running hours. Consistent with the baseline, which counts energy the same way.
- idle only (lower bound): if the work done today just moves into the remaining hours,
  only the idle power of the off hours is saved (46 W board idle, the low factor = 0 % load).
"""

from datetime import timedelta

import pandas as pd

from app.limits.rules import check_measure, is_workday, protected_days
from app.measures import package as pkg
from app.measures.catalogue import HOURS_PER_YEAR, PERSON_DAY_CHF
from app.pipeline.build import BASELINE, read_facts
from app.pipeline.common import read_csv
from app.pipeline.factors import load_factors

RESOURCE = "gpu-ml"
SERVER = "gpu-ml-01"
MEASURE = "M-gpu-ml-pause"
TRAINING_RULE = "R04"
WORKDAY_HOURS = 10  # 08:00-18:00


def _period() -> tuple:
    start = BASELINE[0].date()
    end = (BASELINE[1] + pd.offsets.MonthEnd(0)).date()
    return start, end


def server() -> dict:
    """The server today (server_inventory.csv)."""
    inv = read_csv("server_inventory.csv").set_index("server_id").loc[SERVER]
    return {
        "server_id": SERVER, "region": inv["region"], "vcpu": int(inv["vcpu"]), "ram_gb": int(inv["ram_gb"]),
        "environment": inv["environment"], "cpu_utilisation_30d_pct": float(inv["cpu_utilisation_30d_pct"]),
        "runtime_h_30d": int(inv["runtime_h_30d"]),
    }


def utilisation() -> dict:
    """Weekly GPU load in the baseline year (server_metrics_weekly.csv), split into the weeks
    with quarterly training (rule R04) and all other weeks. Averages are uptime-weighted."""
    start, end = _period()
    m = read_csv("server_metrics_weekly.csv", parse_dates=["week_start"])
    m = m[(m["server_id"] == SERVER) & m["week_start"].dt.date.between(start, end)].copy()
    training = protected_days(TRAINING_RULE, start - timedelta(days=6), end)
    m["training_week"] = m["week_start"].dt.date.map(
        lambda w: any(w <= d < w + timedelta(days=7) for d in training))

    def avg(rows):
        return float((rows["gpu_avg_pct"] * rows["uptime_h"]).sum() / rows["uptime_h"].sum())

    return {
        "weeks": len(m),
        "uptime_h_per_week": float(m["uptime_h"].median()),
        "always_on": bool((m["uptime_h"] == 168).all()),
        "gpu_avg_pct": avg(m),
        "gpu_avg_pct_training_weeks": avg(m[m["training_week"]]),
        "gpu_avg_pct_other_weeks": avg(m[~m["training_week"]]),
        "training_weeks": int(m["training_week"].sum()),
        "gpu_max_week_pct": float(m["gpu_avg_pct"].max()),
        "cpu_avg_pct": float(m["cpu_avg_pct"].mean()),
    }


def schedule() -> dict:
    """Running hours when the server runs on working days 08:00-18:00 and around the clock
    on the training days (same rule as the catalogue's kept_hours_on_demand)."""
    start, end = _period()
    training = set(protected_days(TRAINING_RULE, start, end))
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    workdays = [d for d in days if is_workday(d) and d not in training]
    kept = len(workdays) * WORKDAY_HOURS + len(training) * 24
    return {
        "workdays": len(workdays), "training_days": len(training), "training_dates": sorted(training),
        "kept_h": kept, "hours_per_year": HOURS_PER_YEAR, "kept_share": kept / HOURS_PER_YEAR,
    }


def billing() -> dict:
    """GPU-hours and cost in the baseline year (azure_costs.csv, converted to CHF)."""
    f = read_facts()
    rows = f[(f["resource_id"] == RESOURCE) & f["month"].between(*BASELINE) & (f["usage_kind"] == "gpu_h")]
    gpu_h, cost = float(rows["usage_qty"].sum()), float(rows["cost_chf"].sum())
    return {"gpu_h": gpu_h, "cost_chf": cost, "chf_per_gpu_h": cost / gpu_h,
            "location": rows["location"].mode().iat[0]}


def savings() -> dict:
    """CHF, kWh and CO2 per year, per scenario, both ways of counting the energy."""
    cat = pkg.catalogue()
    measure = cat[cat["measure_id"] == MEASURE]
    m = measure.iloc[0]
    factors = load_factors()
    bill = billing()
    off_gpu_h = bill["gpu_h"] * (1 - float(m["usage_factor"]))
    idle_kw = float(factors.energy.loc["gpu_h", "value_low"])  # low factor = board at 0 % load
    scenarios = {}
    for s in pkg.SCENARIOS:
        co2 = pkg.co2_inputs(s)
        row = pkg.attribute(measure, co2).iloc[0]
        kwh_per_h = float(factors.energy.loc["gpu_h", f"value_{s}"])
        pue = float(factors.pue[f"value_{s}"])
        grid = co2.grid[bill["location"]]
        idle_kwh = off_gpu_h * idle_kw * pue
        scenarios[s] = {
            "kwh_per_gpu_h": kwh_per_h, "pue": pue, "grid_kg_per_kwh": grid,
            "baseline_kwh": co2.resource_kwh[RESOURCE], "baseline_co2_kg": co2.resource_kg[RESOURCE],
            "saved_kwh": float(row["savings_kwh"]), "saved_co2_kg": float(row["savings_co2_kg"]),
            "idle_only_kwh": idle_kwh, "idle_only_co2_kg": idle_kwh * grid,
        }
    effort_chf = float(m["effort_person_days"]) * PERSON_DAY_CHF
    saved_chf = float(m["savings_cost_chf_per_year"])
    return {
        "usage_factor": float(m["usage_factor"]), "off_gpu_h": off_gpu_h, "idle_kw": idle_kw,
        "saved_chf": saved_chf, "effort_person_days": float(m["effort_person_days"]), "effort_chf": effort_chf,
        "effort_why": m["effort_why"], "payback_months": effort_chf / saved_chf * 12, "scenarios": scenarios,
    }


def decision() -> dict:
    check = check_measure(RESOURCE, "pause")
    return {"status": check.status, "decided_by": check.decided_by,
            "conditions": [c["when"] for c in check.conditions],
            "switch_off": check_measure(RESOURCE, "switch_off").status}


def answer() -> dict:
    return {"server": server(), "utilisation": utilisation(), "schedule": schedule(), "billing": billing(),
            "savings": savings(), "decision": decision()}


if __name__ == "__main__":
    from pprint import pprint

    pprint(answer(), sort_dicts=False)
