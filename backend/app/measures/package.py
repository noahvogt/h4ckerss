"""Package builder (issue #6): the best combination of measures under target and budget.

Every combination of the eligible measures is evaluated (at most 2^n, n = 11 today),
so the recommendation is provably the best one under the rules, and the next best
alternatives show the trade-offs.

- Targets (case rules): costs -25 % and location-based CO2 -40 % per year against our
  baseline year; implementation effort at most CHF 16,500 (1 person-day = CHF 1,100).
- Blocked measures (#7) are never included. Measures that need a human decision are
  left out of the recommended package and shown in a second variant "with approvals".
- Measures on the same resource are combined, not added: cost after = baseline cost x
  product of the cost_factors; usage after = product of the usage_factors, at the last
  location. Per-measure savings are attributed in that order, so rows add up exactly.
- CO2 comes from the baseline calculation (#4, app.pipeline): co2_inputs() sums each
  resource's kg CO2e and kWh for a scenario (mid by default; low/high for sensitivity).
  search() and evaluate() also work without CO2 (co2=None): then the package is chosen on
  CHF and effort, and the CO2 target is reported as "pending", never as met.
- Unknown is not zero (as in #4): a resource missing from Co2Inputs (or NaN) has unknown
  CO2, so a measure that changes its energy has unknown CO2 savings (None), and the
  package total is a lower bound. Only measures that do not change energy use
  (energy_effect "none", e.g. cancelling unused seats) save a known 0 kg.
- The CO2 target is proven ("met") only against a complete CO2 baseline. If the baseline
  has unknown parts (#4 coverage "partial", e.g. SaaS without an energy factor), reaching
  -40 % of the known subtotal is reported as "met_known_baseline": unknown baseline
  emissions would dilute the real reduction.
"""

from dataclasses import dataclass
from functools import cache
from itertools import combinations

import pandas as pd

from app.measures.catalogue import PERSON_DAY_CHF, build_catalogue
from app.pipeline.baseline_export import load_calculated_baseline
from app.pipeline.build import BASELINE, read_facts
from app.pipeline.common import DATA_DIR
from app.pipeline.summary import summarize_baseline

BUDGET_CHF = 16_500
COST_TARGET = 0.25
CO2_TARGET = 0.40
OUTPUT = DATA_DIR.parents[1] / "submission" / "measures_package.csv"
TEMPLATE_COLUMNS = [
    "measure_id", "description", "resource_or_source", "change", "effort_person_days",
    "savings_cost_chf_per_year", "savings_energy_kwh_per_year", "savings_co2_kg_location_based",
    "savings_co2_kg_market_based", "risks_and_exceptions", "assumptions_and_sources",
]
# Order inside a resource: usage changes first, then a relocation of what is left.
_ORDER = {"usage": 0, "none": 1, "location": 2}


@dataclass
class Co2Inputs:
    """From the calculation (#4), mid scenario, baseline year."""

    resource_kg: dict[str, float]  # resource_id -> kg CO2e per year; missing or NaN = unknown
    total_kg: float  # baseline CO2 (known subtotal), denominator of the -40 % target
    grid: dict[str, float]  # location -> kg CO2e per kWh; missing = unknown
    resource_kwh: dict[str, float] | None = None  # resource_id -> kWh per year (for the template)
    # True only if total_kg covers the whole baseline (#4 coverage "complete"). Conservative
    # default: a partial baseline cannot prove the target for the whole company.
    baseline_complete: bool = False

    def complete(self) -> bool:
        return self.baseline_complete and all(_known(v) is not None for v in self.resource_kg.values())


# Target status of a package, best first:
# met                 both targets met against a complete baseline
# met_known_baseline  cost met; CO2 -40 % reached on the known part of the baseline only
# pending             cost met; CO2 not calculated or not decidable yet
# not_met             a target is missed
_TARGET_RANK = {"met": 0, "met_known_baseline": 1, "pending": 2, "not_met": 3}


def _known(value) -> float | None:
    """A number, or None if missing/NaN (unknown is not zero)."""
    return None if value is None or value != value else float(value)


SCENARIOS = ("low", "mid", "high")


@cache
def co2_inputs(scenario: str = "mid") -> Co2Inputs:
    """Baseline-year CO2 and kWh per resource from the calculation (#4).

    Resources whose facts are all cost-only (fees, credits) have a known 0. Resources
    without any calculated value (no energy factor, e.g. SaaS seats) stay NaN = unknown.
    The baseline counts as complete only if #4 reports complete emissions coverage.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}, expected one of {SCENARIOS}")
    facts, factors = load_calculated_baseline()
    by_resource = summarize_baseline(facts, by="resource_id").set_index("resource_id")
    annual = summarize_baseline(facts).iloc[0]
    inapplicable = by_resource["emissions_coverage"].eq("inapplicable")
    kg = by_resource[f"co2e_kg_{scenario}"].mask(inapplicable, 0.0)
    kwh = by_resource[f"energy_kwh_{scenario}"].mask(by_resource["energy_coverage"].eq("inapplicable"), 0.0)
    return Co2Inputs(
        resource_kg=kg.astype(float).to_dict(),
        total_kg=float(annual[f"co2e_kg_{scenario}"]),
        grid=factors.grid[f"value_{scenario}"].astype(float).to_dict(),
        resource_kwh=kwh.astype(float).to_dict(),
        baseline_complete=annual["emissions_coverage"] == "complete",
    )


def baseline_cost_chf() -> float:
    facts = read_facts()
    return float(facts.loc[facts["month"].between(*BASELINE), "cost_chf"].sum())


def eligible(cat: pd.DataFrame, include_needs_human: bool = False) -> pd.DataFrame:
    """Measures that may go into a package."""
    allowed = {"allowed", "allowed_outside_windows"} | ({"needs_human"} if include_needs_human else set())
    return cat[cat["status"].isin(allowed)]


_FIELDS = ["measure_id", "resource_id", "status", "energy_effect", "location", "location_after",
           "usage_factor", "cost_factor", "baseline_cost_chf", "effort_person_days"]


def _attribute(records: list[dict], co2: Co2Inputs | None = None) -> list[dict]:
    """Per-measure savings, combining measures on the same resource (plain Python: fast)."""
    by_resource: dict[str, list[dict]] = {}
    for m in records:
        by_resource.setdefault(m["resource_id"], []).append(m)
    out = []
    for resource_id, group in by_resource.items():
        group = sorted(group, key=lambda m: _ORDER[m["energy_effect"]])
        cost_left, usage_left = 1.0, 1.0
        location = start = group[0]["location"]
        kg = kwh = None
        if co2 is not None:
            kg = _known(co2.resource_kg.get(resource_id))
            kwh = _known((co2.resource_kwh or {}).get(resource_id))
        for m in group:
            saved_chf = m["baseline_cost_chf"] * cost_left * (1 - m["cost_factor"])
            cost_left *= m["cost_factor"]
            saved_co2 = saved_kwh = None
            if co2 is not None:
                if m["energy_effect"] == "none":  # energy use unchanged: a known zero
                    saved_co2, saved_kwh = 0.0, 0.0
                else:
                    saved_co2 = _saved_co2(co2, kg, kwh, usage_left, m["usage_factor"],
                                           start, location, m["location_after"])
                    if kwh is not None:
                        saved_kwh = kwh * usage_left * (1 - m["usage_factor"])
                usage_left *= m["usage_factor"]
                location = m["location_after"]
            out.append({**m, "savings_chf": saved_chf, "savings_co2_kg": saved_co2, "savings_kwh": saved_kwh})
    return out


def _saved_co2(co2: Co2Inputs, kg: float | None, kwh: float | None, usage_left: float,
               usage_factor: float, start: str, now: str, after: str) -> float | None:
    """kg CO2 saved by one step on a resource, or None if unknown.

    Without a relocation (all on the start grid) the share of the baseline kg is exact.
    With one, the energy is needed: kWh if known, else kg / start grid (not if that is 0).
    """
    if now == after == start:
        return None if kg is None else kg * usage_left * (1 - usage_factor)
    g_start, g_now, g_after = (_known(co2.grid.get(loc)) for loc in (start, now, after))
    if g_now is None or g_after is None:
        return None
    if kwh is None:
        if kg is None or not g_start:  # no kWh and no way to derive it (unknown or zero grid)
            return None
        kwh = kg / g_start
    return kwh * usage_left * (g_now - usage_factor * g_after)


def attribute(selected: pd.DataFrame, co2: Co2Inputs | None = None) -> pd.DataFrame:
    """Per-measure savings of a selection (DataFrame in, DataFrame out)."""
    return pd.DataFrame(_attribute(selected.to_dict("records"), co2))


def _evaluate(records: list[dict], baseline_chf: float, co2: Co2Inputs | None) -> dict:
    parts = _attribute(records, co2)
    effort_pd = sum(m["effort_person_days"] for m in records)
    savings_chf = sum(p["savings_chf"] for p in parts)
    result = {
        "measures": [m["measure_id"] for m in records],
        "effort_person_days": effort_pd,
        "effort_chf": effort_pd * PERSON_DAY_CHF,
        "savings_chf": savings_chf,
        "cost_reduction": savings_chf / baseline_chf,
        "within_budget": effort_pd * PERSON_DAY_CHF <= BUDGET_CHF,
        "meets_cost_target": savings_chf / baseline_chf >= COST_TARGET,
        "savings_co2_kg": None, "co2_reduction": None, "meets_co2_target": None,
        "co2_unknown": [], "co2_baseline_complete": None,
        "needs_approval": [m["measure_id"] for m in records if m["status"] == "needs_human"],
    }
    if co2 is not None:
        unknown = [p["measure_id"] for p in parts if p["savings_co2_kg"] is None]
        saved = sum(p["savings_co2_kg"] for p in parts if p["savings_co2_kg"] is not None)
        reduction = saved / co2.total_kg if co2.total_kg > 0 else None  # no baseline: undecidable
        # Known savings are a lower bound: enough already, or undecidable while some are unknown.
        if reduction is None:
            met = None
        else:
            met = True if reduction >= CO2_TARGET else (None if unknown else False)
        result.update(savings_co2_kg=saved, co2_reduction=reduction, meets_co2_target=met,
                      co2_unknown=unknown, co2_baseline_complete=co2.complete())
    result["targets"] = _targets(result["meets_cost_target"], result["meets_co2_target"],
                                 result["co2_baseline_complete"])
    return result


def _targets(cost: bool, co2: bool | None, baseline_complete: bool | None = True) -> str:
    """met only if both targets are known to be met on a complete baseline (see _TARGET_RANK)."""
    if not cost or co2 is False:
        return "not_met"
    if co2 is None:
        return "pending"
    return "met" if baseline_complete else "met_known_baseline"


def evaluate(selected: pd.DataFrame, baseline_chf: float, co2: Co2Inputs | None = None) -> dict:
    return _evaluate(selected.to_dict("records"), baseline_chf, co2)


def search(cat: pd.DataFrame, baseline_chf: float, co2: Co2Inputs | None = None,
           include_needs_human: bool = False) -> pd.DataFrame:
    """Every combination within budget, best first.

    Ranking: target status (_TARGET_RANK); then most CO2 saved (if known),
    most CHF saved, least effort."""
    pool = eligible(cat, include_needs_human)[_FIELDS].to_dict("records")
    results = []
    for k in range(1, len(pool) + 1):
        for combo in combinations(pool, k):
            if sum(m["effort_person_days"] for m in combo) * PERSON_DAY_CHF > BUDGET_CHF:
                continue
            results.append(_evaluate(list(combo), baseline_chf, co2))
    out = pd.DataFrame(results)
    out["_target_rank"] = out["targets"].map(_TARGET_RANK)
    keys = ["_target_rank", "savings_co2_kg", "savings_chf", "effort_person_days"] if co2 else \
        ["_target_rank", "savings_chf", "effort_person_days"]
    ascending = [True, False, False, True] if co2 else [True, False, True]
    return out.sort_values(keys, ascending=ascending, ignore_index=True).drop(columns="_target_rank")


def recommend(co2: Co2Inputs | None = None, include_needs_human: bool = False) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """(measure rows of the best package, its summary, ranked alternatives).

    Uses the baseline CO2 (mid scenario) unless other Co2Inputs are given."""
    co2 = co2 or co2_inputs()
    cat = build_catalogue()
    baseline = baseline_cost_chf()
    ranked = search(cat, baseline, co2, include_needs_human)
    best = ranked.iloc[0].to_dict()
    rows = attribute(cat[cat["measure_id"].isin(best["measures"])], co2)
    return rows, best, ranked


def sensitivity(measures: list[str]) -> dict[str, dict]:
    """The same package evaluated with the low, mid and high CO2 scenarios."""
    cat = build_catalogue()
    selected = cat[cat["measure_id"].isin(measures)]
    baseline = baseline_cost_chf()
    return {s: evaluate(selected, baseline, co2_inputs(s)) for s in SCENARIOS}


def to_template(rows: pd.DataFrame) -> pd.DataFrame:
    """The package in the submission template (template_measures_package.csv)."""
    def risks(r):
        parts = [r["risks"]]
        if r["conditions"]:
            parts.append(f"Only outside protection windows: {r['conditions']}")
        if r["status"] == "needs_human":
            parts.append(f"Needs approval by {r['decided_by']}")
        return " ".join(p for p in parts if p)

    def co2_note(r):
        if r["energy_effect"] == "none":
            return " kWh/CO2: no change in energy use, so 0 kWh and 0 kg CO2 saved."
        if pd.isna(r["savings_co2_kg"]):
            return " kWh/CO2: unknown, no energy factor for this resource yet."
        return (" kWh/CO2: baseline-year energy and location-based CO2 of the resource (mid scenario, "
                "submission/template_baseline_and_assumptions.csv) times the usage change"
                + (f", relocated from the {r['location']} to the {r['location_after']} grid" if r["energy_effect"] == "location" else "")
                + ".")

    return pd.DataFrame({
        "measure_id": rows["measure_id"],
        "description": rows["title"],
        "resource_or_source": rows["resource_id"],
        "change": rows["change"] + (" to " + rows["location_after"]).where(rows["location"] != rows["location_after"], ""),
        "effort_person_days": rows["effort_person_days"],
        "savings_cost_chf_per_year": rows["savings_chf"].round(0),
        "savings_energy_kwh_per_year": rows["savings_kwh"].round(0) if rows["savings_kwh"].notna().any() else None,
        "savings_co2_kg_location_based": rows["savings_co2_kg"].round(0) if rows["savings_co2_kg"].notna().any() else None,
        "savings_co2_kg_market_based": None,
        "risks_and_exceptions": rows.apply(risks, axis=1),
        "assumptions_and_sources": rows["assumptions"] + " Sources: " + rows["sources"] + ". Effort: "
        + rows["effort_why"] + "." + rows.apply(co2_note, axis=1),
    })[TEMPLATE_COLUMNS]


def _summary(name: str, r: dict) -> str:
    return (f"{name}: CHF {r['savings_chf']:,.0f}/year ({r['cost_reduction']:.1%}), "
            f"CO2 {r['savings_co2_kg']:,.0f} kg ({r['co2_reduction']:.1%}), "
            f"{r['effort_person_days']:g} PD = CHF {r['effort_chf']:,.0f}; targets: {r['targets']}"
            + (f"; CO2 unknown for {r['co2_unknown']}" if r["co2_unknown"] else "")
            + (f"; needs approval: {r['needs_approval']}" if r["needs_approval"] else ""))


def main() -> None:
    co2 = co2_inputs()
    rows, best, ranked = recommend(co2)
    baseline = baseline_cost_chf()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    to_template(rows).to_csv(OUTPUT, index=False)
    print(f"Baseline year: CHF {baseline:,.0f}, CO2 {co2.total_kg:,.0f} kg (mid, "
          f"{'complete' if co2.complete() else 'known part only'}); targets -25 % cost, -40 % CO2; "
          f"budget CHF {BUDGET_CHF:,}")
    counts = ranked["targets"].value_counts()
    print(f"{len(ranked)} combinations within budget, by target status: "
          + ", ".join(f"{s} {counts.get(s, 0)}" for s in _TARGET_RANK) + "\n")
    print(rows[["measure_id", "status", "effort_person_days", "savings_chf", "savings_kwh", "savings_co2_kg"]]
          .round({"savings_chf": 0, "savings_kwh": 0, "savings_co2_kg": 0}).to_string(index=False))
    print("\n" + _summary("Recommended", best))
    for scenario, r in sensitivity(best["measures"]).items():
        print(f"  CO2 {scenario:>4}: {r['savings_co2_kg']:,.0f} of {co2_inputs(scenario).total_kg:,.0f} kg "
              f"({r['co2_reduction']:.1%}), {r['targets']}")
    print(_summary("With approvals", recommend(co2, include_needs_human=True)[1]))
    print(f"written: {OUTPUT}")


if __name__ == "__main__":
    main()
