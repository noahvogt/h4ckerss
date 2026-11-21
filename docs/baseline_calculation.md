# Baseline calculation

The implemented pipeline selects monthly facts, validates research factors, and estimates facility electricity per fact.

## Baseline selection

[`select_baseline_facts()`](../backend/app/pipeline/baseline.py) validates the input against the shared fact schema, including required fields, allowed categorical values, month-start dates, and a note on any missing CHF cost. It selects **September 2025 through August 2026**, inclusive, and requires at least one fact in each of the 12 months.

Within the selected period, it rejects duplicate keys on `(month, source, resource_id, department, usage_kind)` and missing or unknown resource IDs. Valid IDs come from the [master mapping](../data/provided/mapping_departments_tools.csv). Selection preserves row order, CHF values, and source notes.

## Research factors

[`load_factors()`](../backend/app/pipeline/factors.py) reads the [research CSV](../submission/research_baseline_and_assumptions.csv). It requires the energy, PUE, and location-based grid assumptions, rejects duplicate parameters, and checks required fields, exact units, and the documented `Must` or `Bonus` labels. Values must be finite and satisfy `0 <= low <= mid <= high`. PUE must be at least 1.

The loader retains the original `unit`, `parameter`, `source`, and `calculation_or_assumption` fields. Each energy factor also supplies a precise `factor_unit`, a `usage_divisor` for converting the fact quantity to the factor's denominator, and an `apply_pue` flag.

| Supported `usage_kind` | Factor unit | Divisor | Apply PUE |
|---|---|---:|---|
| `vcpu_h` | kWh/vCPU-hour | 1 | Yes |
| `node_h` | kWh/node-hour | 1 | Yes |
| `gpu_h` | kWh/GPU-hour | 1 | Yes |
| `gb_day` | kWh/GB-day | 1 | Yes |
| `tokens` | kWh/1,000 tokens | 1,000 | No |
| `messages` | kWh/message | 1 | No |

## Facility energy

[`calculate_energy()`](../backend/app/pipeline/energy.py) applies the following formula separately for each scenario `s` in `low`, `mid`, and `high`.

```text
energy_kwh_s = (usage_qty / usage_divisor) * value_s * (PUE_s if apply_pue else 1)
```

`value_s` and `PUE_s` come from the same scenario column in the energy and power usage effectiveness (PUE) assumptions. Infrastructure factors represent IT energy and receive PUE once. AI token and message factors already include facility overhead. Low, mid, and high are deterministic sensitivity scenarios with no statistical confidence interpretation. Mid is the central estimate.

The result preserves every original fact, its index, and its order. It adds `energy_kwh_low`, `energy_kwh_mid`, `energy_kwh_high`, and `energy_status`. It records `energy_factor_parameter`, `energy_factor_unit`, and `energy_apply_pue` for matched factors. The parameter links back to the research provenance. A non-finite or negative calculated result raises `ValueError`.

| `energy_status` | Meaning | Baseline facts |
|---|---|---:|
| `calculated` | A supported factor and finite, nonnegative usage produce an estimate. Valid zero usage produces zero kWh. | 468 |
| `unknown` | Missing, nonnumeric, negative, or non-finite usage leaves kWh missing. The unsupported kinds `gb_transfer`, `capacity_day`, `runner_min`, and `seat_month` also leave kWh missing. | 216 |
| `cost_only` | `usage_kind = none` leaves kWh missing for fees and credits. Negative CHF credits remain in net cost. | 14 |

The [checked-in facts](../data/derived/facts.csv) reconcile to **698 facts, 12 months, and CHF 470,300.4703 net**, including the test account. All 216 unknown rows lack a supported factor. The 134 gateway rows with partial token counts use the available quantity and retain their source notes. Their estimates cover the reported usage only.

## Limitations and planned work

Energy values use researched proxies. The storage factor assumes logical GB-days, and the GPU factor models the board. Coverage is limited to supported usage and the quantities reported in the facts.

**CO₂e calculation — NOT YET IMPLEMENTED.** The loader validates grid factors for CH, DE, IE, and mixed EU, but facility energy does not use them. Planned location-based emissions will multiply each scenario's facility kWh by the matching location and scenario intensity in kg CO₂e/kWh. Unknown locations have no grid factor. The CH, DE, and IE CSV labels retain `kg CO2 per kWh`, while their documented basis is CO₂e. The mixed EU row already uses `kg CO2e per kWh`.

Aggregation, frontend integration, and submission export are also outside the current pipeline.
