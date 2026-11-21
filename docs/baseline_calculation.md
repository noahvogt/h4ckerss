# Baseline Calculation Methodology

## 1. Purpose

This document describes how the baseline calculation pipeline estimates energy consumption and location-based greenhouse gas emissions from the provided monthly usage and cost data.

**Baseline period:** September 2025 – August 2026 (12 months).

The validated baseline contains 698 facts with net costs of CHF 470,300.4703.

All estimates are traceable to the researched assumptions in `submission/research_baseline_and_assumptions.csv`.

## 2. Energy Calculation

For each fact and scenario \(s \in \{\text{low}, \text{mid}, \text{high}\}\), estimated facility energy is calculated as:

\[
E_s =
\frac{\text{usage\_qty}}{\text{usage\_divisor}}
\times \text{energy\_factor}_s
\times
\begin{cases}
\text{PUE}_s & \text{if apply\_pue = true}\\
1 & \text{otherwise}
\end{cases}
\]

Where:

- `usage_qty`: Monthly usage quantity from the fact.
- `usage_divisor`: Number of usage units represented by one factor value.
- `energy_factor_s`: Researched energy factor for scenario `s`.
- `PUE_s`: Power Usage Effectiveness for scenario `s`.
- `apply_pue`: Whether the energy factor requires facility overhead.

The resulting energy is expressed in **kWh**.

### Factor units

| Usage kind | Factor unit | Divisor | Apply PUE |
|---|---|---:|---|
| `vcpu_h` | kWh/vCPU-hour | 1 | Yes |
| `node_h` | kWh/node-hour | 1 | Yes |
| `gpu_h` | kWh/GPU-hour | 1 | Yes |
| `gb_day` | kWh/GB-day | 1 | Yes |
| `tokens` | kWh/1,000 tokens | 1,000 | No |
| `messages` | kWh/message | 1 | No |

PUE is applied only when the researched factor represents IT energy rather than facility-inclusive energy. It must never be applied twice.

## 3. Scenario Interpretation

All calculations preserve three scenarios:

- **Low:** Lower-bound sensitivity estimate.
- **Mid:** Central estimate used for the default dashboard view.
- **High:** Upper-bound sensitivity estimate.

These scenarios are deterministic sensitivity estimates, **not statistical confidence intervals**.

The frontend should display the Mid scenario by default and allow users to inspect Low and High.

## 4. Emissions Calculation

For each fact with a known location and calculable energy:

\[
CO_{2e,s} = E_s \times I_{\text{location},s}
\]

Where \(I_{\text{location},s}\) is the researched location-based grid intensity in kg CO₂e/kWh.

Supported grid locations:

- `CH`: Switzerland
- `DE`: Germany
- `IE`: Ireland
- `EU`: EU mixed proxy

The original CSV unit labels and provenance are preserved. Some research rows use the template label `kg CO2 per kWh`, while their documented methodological basis is CO₂e.

Unknown locations must not receive an invented grid factor.

## 5. Missing Data and Cost-Only Facts

Not every fact has a supported energy model.

The pipeline must distinguish:

| Status | Meaning |
|---|---|
| `calculated` | Energy can be estimated from a supported factor. |
| `unknown` | Energy cannot be calculated because a suitable factor or required input is unavailable. |
| `cost_only` | Financial entry without meaningful usage-based energy, such as a fee or credit. |

Missing energy must **never** be silently replaced with zero.

Negative financial credits remain part of net cost totals but do not automatically represent negative energy consumption.

## 6. Traceability

The calculation output should preserve sufficient metadata to reproduce and explain each result:

- Original fact identifiers and usage quantity
- Energy factor parameter and precise unit
- Research source and calculation assumption
- PUE applicability
- Low/Mid/High energy results
- Calculation status

## 7. Implementation Plan

1. Select and validate baseline facts.
2. Load and validate researched energy factors.
3. Calculate facility energy per fact.
4. Calculate location-based emissions.
5. Aggregate monthly and annual totals and rank drivers.
6. Export detailed calculation results for the frontend.
7. Export the official baseline and assumptions submission.

## 8. Validation

The calculation pipeline must be tested against synthetic examples and the actual baseline dataset.

Baseline reconciliation:

- 698 facts
- 12 months
- CHF 470,300.4703 net costs

The pipeline must preserve all original facts and financial values while adding calculated environmental metrics.