# Baseline calculation

The implemented pipeline selects monthly facts, validates research factors, and estimates facility electricity and location-based CO₂e per fact.

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
pue_multiplier_s = PUE_s if apply_pue is true, otherwise 1
energy_kwh_s = (usage_qty / usage_divisor) * value_s * pue_multiplier_s
```

`value_s` and `PUE_s` come from the same scenario column in the energy and power usage effectiveness (PUE) assumptions. Infrastructure factors represent IT energy and receive PUE once. AI token and message factors already include facility overhead. Low, mid, and high are deterministic sensitivity scenarios with no statistical confidence interpretation. Mid is the central estimate.

The result preserves every original fact, its index, and its order. It adds `energy_kwh_low`, `energy_kwh_mid`, `energy_kwh_high`, and `energy_status`. It records `energy_factor_parameter`, `energy_factor_unit`, and `energy_apply_pue` for matched factors. The parameter links back to the research provenance. A non-finite or negative calculated result raises `ValueError`.

| `energy_status` | Meaning | Baseline facts |
|---|---|---:|
| `calculated` | The model estimates energy from the reported quantity using a supported factor. The quantity must be finite and nonnegative. Valid zero usage produces zero kWh. | 468 |
| `unknown` | Missing, nonnumeric, negative, or non-finite usage leaves kWh missing. The unsupported kinds `gb_transfer`, `capacity_day`, `runner_min`, and `seat_month` also leave kWh missing. | 216 |
| `cost_only` | `usage_kind = none` leaves kWh missing for fees and credits. Negative CHF credits remain in net cost. | 14 |

`calculated` describes which reported quantities were modeled. It does not establish that the source captured all real-world usage. For example, 134 gateway rows have partial token counts. Their energy estimates use the available tokens and preserve the original source notes.

The [checked-in facts](../data/derived/facts.csv) reconcile to **698 facts, 12 months, and CHF 470,300.4703 net**, including the test account. All 216 unknown rows lack a supported factor.

## Location-based emissions

[`calculate_emissions()`](../backend/app/pipeline/emissions.py) uses the grid factor for each fact's location and pairs each facility energy scenario with the same grid intensity scenario.

```text
co2e_kg_s = energy_kwh_s * grid_intensity_s
```

Grid factors cover Switzerland (`CH`), Germany (`DE`), Ireland (`IE`), and a mixed EU proxy (`EU`). The output retains the original `grid_factor_parameter` and `grid_factor_unit` for matched locations. CH, DE, and IE retain the CSV label `kg CO2 per kWh`, and the EU row uses `kg CO2e per kWh`. All four methods document a CO₂e basis, so the output values are in kg CO₂e.

| `emissions_status` | Meaning | Baseline facts |
|---|---|---:|
| `calculated` | The fact has calculated energy in all three scenarios and a matching grid factor. Zero energy gives zero CO₂e. | 468 |
| `unknown` | An unmatched location or unavailable energy leaves all three emissions values missing. Any existing energy estimates are preserved. | 216 |
| `cost_only` | Cost-only energy facts keep this status and have missing emissions. | 14 |

The result adds `co2e_kg_low`, `co2e_kg_mid`, and `co2e_kg_high` alongside the status and grid metadata. It preserves the original facts and their index and order. Non-finite or negative calculated emissions raise `ValueError`. All 216 unknown emissions facts in the checked-in baseline lack an energy estimate.

## Limitations and planned work

Energy values use researched proxies. The storage factor assumes logical GB-days, and the GPU factor models the board. Energy and emissions cover only supported kinds and reported usage. The Swiss grid factor uses a consumption mix including imports. The German, Irish, and mixed EU factors use generation-based proxies, and the mixed EU factor represents the region rather than individual providers.

Aggregation, frontend integration, and submission export are outside the current pipeline.
