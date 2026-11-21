"""Generate the pitch statement from normalized, period-filtered usage."""

import sys
from pathlib import Path

from .records import COUNT_FIELDS, Usage, Window


def _display(value: int | float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:,}" if isinstance(value, int) else f"{value:.6g}"


def _coverage(rows: list[Usage], field: str) -> tuple[int | None, int]:
    known = [value for row in rows if (value := getattr(row, field)) is not None]
    return (sum(known) if known else None), len(known)


def render_summary(rows: list[Usage], window: Window, grid: str | None) -> str:
    # The checkout's backend is not installed as a Python package by uv.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    import pandas as pd

    from app.pipeline.emissions import calculate_emissions
    from app.pipeline.energy import calculate_energy
    from app.pipeline.factors import load_factors

    factors = load_factors()
    if grid is not None and grid not in factors.grid.index:
        raise ValueError(f"no WattsON grid factor for {grid!r}; use {', '.join(factors.grid.index)}")
    token_factor = factors.energy.loc["tokens"]
    complete = [
        row.input_tokens + row.output_tokens
        for row in rows if row.input_tokens is not None and row.output_tokens is not None
    ]
    paired_cache_counts = [
        (row.input_tokens, row.cached_input_tokens)
        for row in rows if row.input_tokens is not None and row.cached_input_tokens is not None
    ]
    paired_input = sum(input_tokens for input_tokens, _ in paired_cache_counts)
    totals = {"Electricity (kWh)": [None] * 3, "Location-based CO₂e (kg)": [None] * 3}
    if complete:
        modeled = calculate_emissions(calculate_energy(pd.DataFrame([{
            "usage_kind": "tokens",
            "usage_qty": sum(complete),
            "location": grid or "unknown",
        }]), factors), factors).iloc[0]
        for label, metric in (("Electricity (kWh)", "energy_kwh"), ("Location-based CO₂e (kg)", "co2e_kg")):
            totals[label] = [
                None if pd.isna(value := modeled[f"{metric}_{scenario}"]) else float(value)
                for scenario in ("low", "mid", "high")
            ]

    lines = [
        "# Hackathon team AI footprint",
        "",
        f"Period {window.start} through {window.end} inclusive in Europe/Zurich.",
        f"Coverage includes {len(rows):,} recorded usage rows from submitted evidence.",
    ]
    low, mid, high = totals["Electricity (kWh)"]
    if mid is not None:
        lines.extend([
            "",
            f"**Pitch statement.** For the logged AI usage, our blended token proxy estimates "
            f"{_display(mid)} kWh of inference electricity in the mid scenario "
            f"({_display(low)}–{_display(high)} kWh across the low and high scenarios). "
            f"The estimate covers {len(complete):,} of {len(rows):,} submitted rows.",
        ])
    else:
        lines.extend(["", "**Pitch statement.** The submitted evidence does not support an electricity estimate."])
    lines.extend([
        "",
        "## Reported usage",
        "",
        "| Metric | Known subtotal | Rows reporting it |",
        "|---|---:|---:|",
    ])
    labels = ("Input tokens", "Cached input (included in input)", "Output tokens", "Requests")
    for field, label in zip(COUNT_FIELDS, labels, strict=True):
        total, count = _coverage(rows, field)
        lines.append(f"| {label} | {_display(total)} | {count:,} / {len(rows):,} |")
    if paired_input:
        cached_input = sum(cached for _, cached in paired_cache_counts)
        lines.extend([
            "",
            f"Cached tokens account for {cached_input / paired_input:.1%} of input tokens where both "
            f"counts were reported ({len(paired_cache_counts):,} of {len(rows):,} usage rows).",
        ])
    lines.extend([
        "",
        "## Modeled footprint",
        "",
        f"Electricity estimates cover {len(complete):,} of {len(rows):,} rows "
        f"({_display(sum(complete) if complete else None)} input and output tokens combined).",
        "",
        "| Metric | Low | Mid | High |",
        "|---|---:|---:|---:|",
        *(
            "| " + label + " | " + " | ".join(map(_display, values)) + " |"
            for label, values in totals.items()
        ),
        "",
        f"WattsON uses `{token_factor['parameter']}` ({token_factor['factor_unit']}) "
        "from `submission/research_baseline_and_assumptions.csv`. The factor includes facility overhead. "
        "Low, mid and high are deterministic sensitivity scenarios. They estimate inference electricity.",
    ])
    if grid:
        lines.append(
            f"Location-based CO₂e uses the explicitly selected {grid} grid scenario "
            f"(`{factors.grid.loc[grid, 'parameter']}`) for all modeled rows. "
            "This scenario alone does not establish where inference ran."
        )
    else:
        lines.append("Location-based CO₂e is unknown because no inference grid scenario was supplied.")
    if rows:
        lines.extend(["", "## Usage by tool", "", "| Tool | Rows | Input tokens | Output tokens |", "|---|---:|---:|---:|"])
        for tool in sorted({row.tool for row in rows}, key=str.casefold):
            selected = [row for row in rows if row.tool == tool]
            safe_tool = tool.replace("|", r"\|").replace("\n", " ").replace("\r", " ")
            lines.append(f"| {safe_tool} | {len(selected):,} | "
                         f"{_display(_coverage(selected, 'input_tokens')[0])} | "
                         f"{_display(_coverage(selected, 'output_tokens')[0])} |")
    lines.extend([
        "",
        "## Coverage limitations",
        "",
        f"- {len(rows) - len(complete):,} rows lack at least one token count and contribute no electricity estimate.",
        "- Tools with missing telemetry or unsubmitted evidence may add usage. Subscription percentages cannot establish token counts.",
        "- The blended factor was derived from the company baseline's token mix. "
        "The proxy applies the same factor to cached input, uncached input and output, with cached input counted once. "
        "The research does not establish a separate energy factor for cached input or quantify the effect of caching on this workload.",
    ])
    return "\n".join(lines) + "\n"
