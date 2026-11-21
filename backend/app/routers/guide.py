"""Evidence-backed WattsON Guide answers from the existing case calculations."""

import re
from collections.abc import Callable
from functools import cache
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints

from app.guide_usage import Usage, provider_enabled, route_question
from app.limits import evidence
from app.limits.explain import explain
from app.measures import gpu
from app.pipeline.ai_saas import calculate_unused_ai_seats
from app.pipeline.common import DATA_DIR
from app.routers import baseline, measures

router = APIRouter(prefix="/api/guide", tags=["guide"])
Mode = Literal["demo", "ai"]


class Question(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=700)]


class Source(BaseModel):
    reference: str
    api_url: str | None = None


class Answer(BaseModel):
    answer: str
    sources: list[Source]
    topic: str
    mode: Mode
    usage: Usage | None = None
    notice: str | None = None


class Example(BaseModel):
    label: str
    question: str


class Examples(BaseModel):
    mode: Mode
    examples: list[Example]


@cache
def _examples() -> tuple[Example, ...]:
    questions = [
        line.removeprefix("**Question:** ").strip()
        for line in (DATA_DIR / "example_questions.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("**Question:** ")
    ]
    return tuple(
        Example(label=label, question=question)
        for label, question in zip(("Unused AI seats", "GPU on demand", "Production off-hours"), questions, strict=True)
    )


@router.get("/examples")
def examples() -> Examples:
    return Examples(mode="ai" if provider_enabled() else "demo", examples=list(_examples()))


def _number(value, digits: int = 2) -> str:
    return "unknown" if pd.isna(value) else f"{value:,.{digits}f}"


def _files(*names: str) -> list[Source]:
    return [Source(reference=f"data/provided/{name}") for name in names]


RESEARCH = Source(reference="submission/research_baseline_and_assumptions.csv")
BASELINE = Source(reference="docs/baseline_calculation.md", api_url="/api/baseline")
PACKAGE = Source(reference="submission/measures_package.csv", api_url="/api/package")


def _seats() -> tuple[str, list[Source]]:
    rows = calculate_unused_ai_seats()
    totals = rows[["licences_purchased", "licences_active_30d", "licences_unused", "unused_cost_chf"]].sum(
        skipna=False, min_count=1
    )
    answer = [
        f"In August 2026, Final AI subscription contracts had "
        f"{_number(totals['licences_purchased'], 0)} purchased seats, "
        f"{_number(totals['licences_active_30d'], 0)} active in 30 days, and "
        f"{_number(totals['licences_unused'], 0)} unused. "
        f"The unused share cost CHF {_number(totals['unused_cost_chf'])} for the month.",
    ]
    answer.extend(
        f"• {r.product} ({r.provider}): {_number(r.licences_purchased, 0)} purchased, "
        f"{_number(r.licences_active_30d, 0)} active, {_number(r.licences_unused, 0)} unused, "
        f"CHF {_number(r.unused_cost_chf)} per month for unused seats."
        for r in rows.itertuples(index=False)
    )
    answer.append(
        "For each contract row, unused seats = purchased − active. Apply the August exchange rate "
        "to the billed amount, then allocate that CHF cost by unused ÷ purchased seats. "
        "Drafts are excluded. The seat counts support a cost allocation only."
    )
    return "\n\n".join(answer), _files("ai_subscriptions.csv", "exchange_rates.csv")


def _gpu() -> tuple[str, list[Source]]:
    data = gpu.answer()
    savings, usage, schedule = data["savings"], data["utilisation"], data["schedule"]
    bill, decision = data["billing"], data["decision"]
    low, mid, high = (savings["scenarios"][s] for s in ("low", "mid", "high"))
    return (
        f"Running {data['server']['server_id']} on demand could save CHF {savings['saved_chf']:,.2f} "
        f"and {mid['saved_co2_kg']:,.1f} kg CO₂e per year in the modeled mid scenario. "
        f"Implementation takes {savings['effort_person_days']:g} person-days "
        f"(CHF {savings['effort_chf']:,.0f}), with about {savings['payback_months']:.1f} months to pay back.\n\n"
        f"The server ran {usage['uptime_h_per_week']:g} h/week (median). Uptime-weighted GPU load was "
        f"{usage['gpu_avg_pct']:.1f}% overall and {usage['gpu_avg_pct_other_weeks']:.1f}% outside training weeks. "
        f"The proposed schedule keeps {schedule['kept_h']:,} of {schedule['hours_per_year']:,} "
        f"calendar hours, including {schedule['training_days']} protected training days.\n\n"
        f"Apply the off share to {bill['gpu_h']:,.0f} billed GPU-hours to save {savings['off_gpu_h']:,.1f} GPU-hours. "
        f"At CHF {bill['chf_per_gpu_h']:.5f}/GPU-hour this yields the CHF savings above (rounded in the measure). "
        f"For energy: hours saved × {mid['kwh_per_gpu_h']:.6f} kWh/GPU-hour × PUE {mid['pue']:.2f} "
        f"≈ {mid['saved_kwh']:,.1f} kWh. Multiply the energy by "
        f"{mid['grid_kg_per_kwh']:.6f} kg CO₂e/kWh ({bill['location']}) for location-based emissions.\n\n"
        f"The research gives low/high factors of {low['kwh_per_gpu_h']:g}–{high['kwh_per_gpu_h']:g} kWh/GPU-hour, "
        f"PUE {low['pue']:g}–{high['pue']:g}, and a {bill['location']} grid intensity of "
        f"{low['grid_kg_per_kwh']:.3f}–{high['grid_kg_per_kwh']:.3f} kg CO₂e/kWh. "
        f"Low/high sensitivity: {low['saved_co2_kg']:,.1f}–{high['saved_co2_kg']:,.1f} kg CO₂e/year. "
        f"If work simply moves to the retained hours, the mid idle-only estimate is "
        f"{mid['idle_only_co2_kg']:,.1f} kg CO₂e/year. These are modeled savings.\n\n"
        f"{decision['decided_by']} decides. Keep the quarterly training protected "
        f"({', '.join(decision['conditions'])}). A permanent shutdown is {decision['switch_off']}.",
        [
            Source(reference="docs/answers/q2_gpu_on_demand.md", api_url="/api/rules/explain?resource_id=gpu-ml&change=pause"),
            *_files("azure_costs.csv", "exchange_rates.csv", "server_inventory.csv", "server_metrics_weekly.csv", "it_tickets.csv"),
            RESEARCH, PACKAGE,
        ],
    )


def _production() -> tuple[str, list[Source]]:
    rule = explain("dp-prod", "schedule_off")
    permanent = explain("dp-prod", "switch_off")
    daily = rule["evidence"]["usage_by_day_type"]
    checked, conflicts = evidence.off_schedule_conflicts()
    hours = evidence.possible_off_hours()["off_hours"].sum()
    lines = [f"A scheduled shutdown for dp-prod is {rule['status'].replace('_', ' ')}. "
             f"A permanent shutdown is {permanent['status']}. Protect these local windows:"]
    lines.extend(f"• {window['rule_id']}: {window['when']}. {window['summary']}" for window in rule["windows"])
    lines.extend([
        "Reported active hours per day: " + ", ".join(
            f"{_number(row['active_use_h'], 1)} on a {row['day_type']}" for row in daily
        ) + ".",
        f"The case schedule identifies {hours:,.0f} candidate off-hours over the baseline year. "
        f"The overlap check found {len(conflicts):,} conflicts in {checked:,} scheduled job runs. "
        "These windows assume automatic restart and still need approval. Daily usage gives only indirect evidence of interactive hours.",
        f"{rule['decided_by']} owns the closing windows. Confirm the nightly jobs with the Head of Consulting "
        "and the restart schedule with the Head of IT before implementation.",
    ])
    return "\n\n".join(lines), [
        Source(reference="docs/answers/q3_production_platform_off_hours.md",
               api_url="/api/rules/explain?resource_id=dp-prod&change=schedule_off"),
        *_files("data_platform_usage.csv", "extra/data_platform_jobs.csv", "it_tickets.csv",
                "business_calendar.csv", "mapping_departments_tools.csv"),
    ]


def _baseline() -> tuple[str, list[Source]]:
    payload = baseline.baseline()
    a = payload["annual"]
    return (
        f"From {payload['period_start']} through {payload['period_end']}, the baseline recorded "
        f"CHF {_number(a['cost_chf'])} in net cost. The modeled mid-scenario subtotals are "
        f"{_number(a['energy_kwh_mid'])} kWh and {_number(a['co2e_kg_mid'])} kg CO₂e (location-based).\n\n"
        f"Emissions coverage is {a['emissions_coverage']}: {a['emissions_calculated_count']} calculated "
        f"({a['emissions_partial_usage_count']} with partial source usage), "
        f"{a['emissions_unknown_count']} unknown, and {a['emissions_cost_only_count']} cost-only. "
        "These modeled subtotals include only the reported usage with compatible factors. Unknown rows add no estimate.\n\n"
        "Per fact, divide usage by the factor divisor, multiply by the matching scenario's energy factor, "
        "then apply PUE only for factors that exclude facility overhead. Multiply that energy by the "
        "same-scenario grid factor for the deployment location to get kg CO₂e. Low/mid/high are sensitivity cases.",
        [BASELINE, Source(reference="data/derived/facts.csv"), RESEARCH],
    )


def _drivers() -> tuple[str, list[Source]]:
    rankings = baseline.baseline()["drivers"]
    lines = ["Largest baseline resources, ranked separately by annual net cost and known modeled mid-scenario subtotals:"]
    for metric, field, unit in (
        ("cost_chf", "cost_chf", "CHF"), ("energy_kwh", "energy_kwh_mid", "kWh"), ("co2e_kg", "co2e_kg_mid", "kg CO₂e")
    ):
        leaders = rankings[metric]["resource_id"][:3]
        lines.append(f"• {unit}: " + ", ".join(f"{row['resource_id']} ({_number(row[field])})" for row in leaders))
    lines.append("Physical coverage is partial. Resources with unknown values for a metric are excluded from that ranking.")
    return "\n\n".join(lines), [BASELINE, RESEARCH]


def _package() -> tuple[str, list[Source]]:
    package = measures.package(approvals=False, alternatives=5)
    s = package.summary
    titles = ", ".join(m.title for m in package.measures)
    return (
        f"The recommended package models CHF {_number(s.savings_chf)} in annual savings and "
        f"{_number(s.savings_co2_kg)} kg CO₂e/year in location-based mid-scenario savings, "
        f"for CHF {_number(s.effort_chf)} of implementation effort.\n\n"
        f"Included measures: {titles}.\n\n"
        "The emissions comparison uses the known baseline subtotal. Coverage is partial, so the "
        "results cannot establish a company-wide reduction. Savings are estimates. Interacting measures "
        "on the same resource are evaluated together.",
        [PACKAGE, BASELINE, RESEARCH],
    )


def _measure(measure_id: str) -> tuple[str, list[Source]] | None:
    for m in measures.measures():
        if m.measure_id.lower() == measure_id:
            energy = _number(m.savings_kwh) if m.energy_effect != "none" else "inapplicable"
            co2e = _number(m.savings_co2_kg) if m.energy_effect != "none" else "inapplicable"
            decision = f" Decision owner: {m.decided_by}." if m.decided_by else ""
            return (
                f"{m.title} ({m.measure_id}). Standalone estimate per year: CHF {_number(m.savings_chf)}, "
                f"{energy} kWh, {co2e} kg CO₂e (location-based mid). "
                f"Effort: {m.effort_person_days:g} person-day{'s' if m.effort_person_days != 1 else ''} "
                f"(CHF {_number(m.effort_chf)}).\n\n"
                f"Rule status: {m.status.replace('_', ' ')}.{decision} {m.assumptions} "
                "Physical savings use the available modeled baseline.",
                [Source(reference="backend/app/measures/catalogue.py", api_url="/api/measures"),
                 Source(reference="backend/app/limits/explain.py", api_url=m.explain_url), RESEARCH],
            )
    return None


_TOPICS: dict[str, tuple[str, str, Callable[[], tuple[str, list[Source]]]]] = {
    "seats": ("unused AI subscription seats and cost for August 2026", r"\bseats?\b|licen[cs]es?|subscription", _seats),
    "gpu": ("on-demand GPU server schedule, utilization, annual savings, effort", r"\bgpu\b", _gpu),
    "production": ("dp-prod production platform nights, weekends, and approval", r"\bproduction\b|dp-prod", _production),
    "drivers": ("largest baseline cost, energy, and emissions drivers", r"\b(drivers?|largest|biggest)\b", _drivers),
    "package": ("recommended measures package and estimated savings", r"\b(package|recommend\w*|measures?)\b", _package),
    "baseline": ("annual baseline totals and energy and location-based emissions methods",
                 r"\b(baseline|annual totals?|energy|carbon|emissions|grid|pue|co2e?)\b|co₂", _baseline),
}


@router.post("/ask")
def ask(body: Question) -> Answer:
    question = body.question.lower()
    example_topics = dict(zip(
        (ex.question.lower() for ex in _examples()), ("seats", "gpu", "production"), strict=True
    ))
    exact_topic = example_topics.get(question)
    measure_id = re.search(r"\bm-[a-z0-9]+(?:-[a-z0-9]+)+\b", question)
    if measure_id:
        result = _measure(measure_id[0])
        if result:
            return Answer(answer=result[0], sources=result[1], topic="measure", mode="demo")

    options = {key: details[0] for key, details in _TOPICS.items()}
    options["unsupported"] = "outside those data and calculations"
    routed = route_question(body.question, options)
    local_topic = next((key for key, (_, pattern, _) in _TOPICS.items() if re.search(pattern, question)), None)
    topic = exact_topic or routed.topic or local_topic or "unsupported"
    answer, sources = (
        _TOPICS[topic][2]() if topic in _TOPICS else (
            "I don’t have a calculation that answers that question. Try one of the three examples, "
            "ask about the annual baseline or recommended package, or enter a measure ID.", [],
        )
    )
    return Answer(answer=answer, sources=sources, topic=topic, mode="ai" if routed.topic else "demo",
                  usage=routed.usage, notice=routed.notice)
