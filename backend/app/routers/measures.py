"""/api/measures and /api/package: the measures catalogue and the recommended package
(issues #5, #6). Read-only: evaluating a selection does not change anything.

Numbers are the same as in submission/measures_package.csv. CO2 is location-based, mid
scenario, unless stated otherwise; unknown values are null, never 0.
"""

from functools import cache
from urllib.parse import urlencode

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.measures import package as pkg

router = APIRouter(prefix="/api", tags=["measures"])


class Measure(BaseModel):
    measure_id: str
    title: str
    resource_id: str
    change: str
    location: str
    location_after: str  # differs from location for a relocation
    energy_effect: str  # usage | location | none (e.g. seats: no energy change)
    status: str  # allowed | allowed_outside_windows | needs_human | blocked
    decided_by: str | None
    conditions: list[str]  # protection windows the schedule must avoid
    interacts_with: list[str]  # measures on the same resource (combined, not added)
    effort_person_days: float
    effort_chf: float
    savings_chf: float  # per year
    savings_kwh: float | None  # per year; null = unknown
    savings_co2_kg: float | None  # per year, location-based; null = unknown
    effort_why: str
    assumptions: str
    sources: str
    risks: str
    explain_url: str  # GET this for the explain box (/api/rules/explain)


class Targets(BaseModel):
    cost_reduction: float  # 0.25 = -25 %
    co2_reduction: float  # 0.40 = -40 %, location-based
    budget_chf: float
    person_day_chf: float
    baseline_cost_chf: float
    baseline_co2_kg: float  # known subtotal (mid)
    co2_baseline_complete: bool  # false: the CO2 target is proven on the known part only


class Summary(BaseModel):
    measures: list[str]
    effort_person_days: float
    effort_chf: float
    within_budget: bool
    savings_chf: float
    cost_reduction: float
    meets_cost_target: bool
    savings_co2_kg: float | None
    co2_reduction: float | None
    meets_co2_target: bool | None  # null = not decidable
    co2_unknown: list[str]  # measures whose CO2 saving is unknown (total is a lower bound)
    # met | met_known_baseline (CO2 target reached on the known part of the baseline) | pending | not_met
    targets: str
    needs_approval: list[str]  # measures that need a human decision


class Scenario(BaseModel):
    baseline_co2_kg: float
    savings_co2_kg: float | None
    co2_reduction: float | None
    targets: str


class Package(BaseModel):
    targets: Targets
    summary: Summary
    measures: list[Measure]  # savings attributed per measure; they add up to the summary
    sensitivity: dict[str, Scenario]  # low | mid | high
    alternatives: list[Summary]  # next best packages, best first (trade-offs)


class Selection(BaseModel):
    measure_ids: list[str] = Field(min_length=1, examples=[["M-dp-prod-schedule", "M-vm-test-downsize"]])


def _num(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _split(value, sep: str) -> list[str]:
    return [] if not isinstance(value, str) or not value else value.split(sep)


def _measures(rows: pd.DataFrame) -> list[Measure]:
    out = []
    for r in rows.to_dict("records"):
        query = urlencode({"resource_id": r["resource_id"], "change": r["change"]})
        out.append(Measure(
            **{k: r[k] for k in ["measure_id", "title", "resource_id", "change", "location", "location_after",
                                 "energy_effect", "status", "effort_why", "assumptions", "sources", "risks"]},
            decided_by=r["decided_by"] if isinstance(r["decided_by"], str) else None,
            conditions=_split(r["conditions"], "; "),
            interacts_with=_split(r["interacts_with"], ", "),
            effort_person_days=r["effort_person_days"],
            effort_chf=r["effort_person_days"] * pkg.PERSON_DAY_CHF,
            savings_chf=r["savings_chf"],
            savings_kwh=_num(r["savings_kwh"]),
            savings_co2_kg=_num(r["savings_co2_kg"]),
            explain_url=f"/api/rules/explain?{query}",
        ))
    return out


def _summary(result: dict) -> Summary:
    """From evaluate() or a row of search() (numpy types, NaN for unknown)."""
    co2_met = result["meets_co2_target"]
    return Summary(
        measures=list(result["measures"]),
        effort_person_days=float(result["effort_person_days"]),
        effort_chf=float(result["effort_chf"]),
        within_budget=bool(result["within_budget"]),
        savings_chf=float(result["savings_chf"]),
        cost_reduction=float(result["cost_reduction"]),
        meets_cost_target=bool(result["meets_cost_target"]),
        savings_co2_kg=_num(result["savings_co2_kg"]),
        co2_reduction=_num(result["co2_reduction"]),
        meets_co2_target=None if co2_met is None or pd.isna(co2_met) else bool(co2_met),
        co2_unknown=list(result["co2_unknown"]),
        targets=str(result["targets"]),
        needs_approval=list(result["needs_approval"]),
    )


def _targets() -> Targets:
    co2 = pkg.co2_inputs()
    return Targets(
        cost_reduction=pkg.COST_TARGET, co2_reduction=pkg.CO2_TARGET, budget_chf=pkg.BUDGET_CHF,
        person_day_chf=pkg.PERSON_DAY_CHF, baseline_cost_chf=pkg.baseline_cost_chf(),
        baseline_co2_kg=co2.total_kg, co2_baseline_complete=co2.complete(),
    )


def _sensitivity(measures: list[str]) -> dict[str, Scenario]:
    return {
        s: Scenario(baseline_co2_kg=pkg.co2_inputs(s).total_kg, savings_co2_kg=_num(r["savings_co2_kg"]),
                    co2_reduction=_num(r["co2_reduction"]), targets=r["targets"])
        for s, r in pkg.sensitivity(measures).items()
    }


@cache
def _package(include_needs_human: bool, alternatives: int) -> "Package":
    rows, best, ranked = pkg.recommend(include_needs_human=include_needs_human)
    return Package(
        targets=_targets(),
        summary=_summary(best),
        measures=_measures(rows),
        sensitivity=_sensitivity(best["measures"]),
        alternatives=[_summary(r) for r in ranked.iloc[1:alternatives + 1].to_dict("records")],
    )


@cache
def _standalone() -> pd.DataFrame:
    """Each measure evaluated on its own (no other measure on the same resource)."""
    cat, co2 = pkg.catalogue(), pkg.co2_inputs()
    return pd.concat([pkg.attribute(cat.iloc[[i]], co2) for i in range(len(cat))], ignore_index=True)


def warm_up() -> None:
    """Fill the caches for the default requests (see main.lifespan)."""
    _standalone()
    for approvals in (False, True):
        _package(approvals, 5)


@router.get("/measures")
def measures() -> list[Measure]:
    """Every measure in the catalogue, blocked ones included, each with its savings on its own
    (CHF, kWh, CO2 mid). In a package, measures on the same resource are combined."""
    return _measures(_standalone())


@router.get("/package")
def package(
    approvals: bool = Query(False, description="also consider measures that need a human decision"),
    alternatives: int = Query(5, ge=0, le=50, description="how many next best packages to return"),
) -> Package:
    """The recommended package: the best combination of allowed measures within the budget,
    ranked by target status, then CO2, CHF and effort. Same as submission/measures_package.csv
    (approvals=false). With approvals=true, measures that need a human decision may be included."""
    return _package(approvals, alternatives)


@router.post("/package/evaluate")
def evaluate(selection: Selection) -> Package:
    """Evaluate a selection of measures, e.g. after a measure was rejected in the approvals.

    Blocked measures cannot be part of a package (422). The result says whether the
    selection is within budget and meets the targets; it is not saved anywhere."""
    cat = pkg.catalogue()
    ids = list(dict.fromkeys(selection.measure_ids))
    unknown = sorted(set(ids) - set(cat["measure_id"]))
    if unknown:
        raise HTTPException(404, f"unknown measures: {unknown}")
    selected = cat[cat["measure_id"].isin(ids)]
    blocked = selected.loc[selected["status"] == "blocked", "measure_id"].tolist()
    if blocked:
        raise HTTPException(422, f"blocked measures cannot be part of a package: {blocked}")
    co2 = pkg.co2_inputs()
    result = pkg.evaluate(selected, pkg.baseline_cost_chf(), co2)
    return Package(
        targets=_targets(),
        summary=_summary(result),
        measures=_measures(pkg.attribute(selected, co2)),
        sensitivity=_sensitivity(result["measures"]),
        alternatives=[],
    )
