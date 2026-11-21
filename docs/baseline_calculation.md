# Baseline calculation

The pipeline selects monthly facts, validates research factors, estimates facility electricity and location-based CO₂e per fact, and summarizes and ranks baseline drivers.

## Baseline selection

[`select_baseline_facts()`](../backend/app/pipeline/baseline.py) validates the entire input against the shared fact schema before filtering. This includes out-of-period rows. It checks required fields, allowed categorical values, month starts on the first day at midnight, and a note on any missing CHF cost. It then selects **September 2025 through August 2026**, inclusive, and requires at least one fact in each of the 12 months.

By default, Azure, AWS, the hoster, AI subscriptions, and SaaS contracts must each be present in the selected period and cover all 12 months. A wholly absent required feed is listed by source name. Gaps in a required feed that is present are listed as `(source, month)` pairs. Gateway activity and other sparse sources are exempt unless explicitly required.

For a deliberate subset, pass `required_sources` to replace the default set. An empty collection skips per-source checks while still requiring all 12 baseline months overall.

Within the selected period, it rejects duplicate keys on `(month, source, resource_id, department, usage_kind)` and missing, noncanonical, or unknown resource IDs. IDs must match the [master mapping](../data/provided/mapping_departments_tools.csv) exactly. Ingestion can use a whitespace-tolerant lookup for metadata, and the baseline points out padding on a known ID so the caller can correct the fact key. Selection preserves row order, CHF values, and source notes.

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

## Summaries and driver rankings

[`summarize_baseline()`](../backend/app/pipeline/summary.py) takes the already selected and calculated facts. Use `by="month"` for monthly totals and omit `by` for the annual company total. It also accepts location, department, tool, category, and resource ID, alone or in combination. Missing group labels are kept as a group. Each fact is counted once per grouping. CHF is summed once, with credits retaining their sign. Energy and emissions are summed separately for each scenario over known values. A group with no known values for a metric returns a missing subtotal. An empty input with the fact columns returns an empty summary.

Coverage is tracked independently for cost, energy, and emissions. Each physical metric counts calculated, unknown, and cost-only facts. It also counts calculated facts with partial usage flagged in source notes. The recognized flags are known tokens or messages only and billing periods with missing days. `partial_token_fact_count` counts facts flagged for partial token usage, which can be traced back to the original fact notes.

| Coverage | Meaning |
|---|---|
| `complete` | All applicable facts have numeric values and none have a recognized partial-data flag for the metric. |
| `partial` | A known subtotal exists, and at least one applicable fact is unavailable or flagged as partial. |
| `unavailable` | Applicable facts exist and none have a known value. |
| `inapplicable` | Every fact is cost-only for the physical metric. |

Cost coverage counts known amounts, missing amounts, and known subtotals flagged as incomplete. Estimated CHF amounts remain part of the known subtotal. Cost-only rows contribute to CHF and are excluded from physical coverage. These labels describe the available data and the model's coverage. They do not establish complete physical measurement.

The annual summary counts 698 facts and retains CHF 470,300.4703 net. Energy and emissions each have 468 calculated, 216 unknown, and 14 cost-only facts. Of the calculated facts for each metric, 183 have flagged partial usage, including 134 with partial token counts. The mid scenario known subtotals are **24,185.38 kWh** and **4,203.96 kg CO₂e**, with partial coverage for both metrics.

`rank_drivers()` ranks annual subtotals by resource ID, department, tool, or location. The ranking metric is signed net CHF (`cost_chf`), mid scenario kWh (`energy_kwh`), or mid scenario kg CO₂e (`co2e_kg`). Groups with unavailable values for the selected metric are excluded. Known zero values remain eligible. Rows sort by descending subtotal and ascending group label for ties, with missing labels last. Ranked rows retain the summary's coverage counts and statuses. An optional limit returns the top rows.

## Frontend and audit exports

From the repository root, run:

```sh
cd backend
uv run python -m app.pipeline.baseline_export
```

The command reads the checked-in facts and research assumptions through the existing pipeline. It writes `out/baseline/baseline.json` and `out/baseline/baseline_details.csv` relative to the repository root. Pass `--output-dir PATH` to write both files elsewhere. The default `out/` directory is ignored by Git, and rerunning the command replaces the two generated files.

### JSON contract

The [exporter](../backend/app/pipeline/baseline_export.py) writes `schema_version: 1`, inclusive `period_start` and `period_end`, `scenarios`, `default_scenario: "mid"`, a `units` map, and the companion `details_file` name. Dates use `YYYY-MM-DD`, with monthly rows dated on the first day of each month.

| Field | Content |
|---|---|
| `annual` | Company-wide KPI record. |
| `monthly` | Company-wide records in month order. |
| `breakdowns` | Separate annual arrays keyed by `location`, `department`, `tool`, and `category`. |
| `drivers` | Up to ten known drivers per metric and dimension, in rank order. Metric keys are `cost_chf`, `energy_kwh`, and `co2e_kg`. Each contains rankings by `resource_id`, `department`, `tool`, and `location`. |
| `rows` | Annual groups by location, department, tool, and category for the existing map importer. `energy_kwh` and `co2_kg` are compatibility aliases of the mid scenario values, with `co2_kg` expressed in kg CO₂e. |

Each summary or ranking record includes `cost_chf` in CHF, the three `energy_kwh_*` values in kWh, the three `co2e_kg_*` values in kg CO₂e, `fact_count`, and the coverage fields defined above. Missing numbers are JSON `null`. A numeric zero represents a known zero, and the coverage fields distinguish unavailable and inapplicable results. Values retain their calculation precision. Round for display.

For the [map overview](../frontend/page1-map-overview/README.md), open it with `?dev=1` and import `baseline.json` in Developer tools. The map reads the period and `rows`. Its partial labels depend only on null metric values. It does not interpret `cost_coverage`, `energy_coverage`, `emissions_coverage`, or their counts. A numeric subtotal with flagged partial usage may appear without a partial label, and a null from cost-only activity may trigger a partial label. For coverage-aware displays, use the exported summaries and each metric's explicit coverage fields.

### Audit CSV

The UTF-8 CSV contains one row per original fact, sorted by the stable key `(month, source, resource_id, department, usage_kind)`. It retains all fact fields, original notes, calculated scenarios, and statuses. It adds per-fact coverage, the energy usage divisor, the energy and grid factor values for each scenario, and the source and calculation assumption for each matched factor.

When calling the export functions directly, supply calculated facts from the validated baseline selector. The JSON builder assumes unique fact keys. The combined exporter checks those keys through the audit join before writing either file.

The `pue_multiplier_*` columns show the scenario multiplier for a matched energy factor. Facility-inclusive AI factors use 1. Rows with no energy factor have blank multipliers. PUE research provenance is present where the factor calls for PUE. Grid unit labels are retained from the research CSV. Missing CSV fields are blank, with the status and coverage fields providing their meaning. Use the stable fact key for individual audits or filter by the dimensions of an aggregate row.

## Official submission

The [case instructions](../data/provided/README.md#submission-baseline-assumptions-and-package-of-measures) require two completed tables alongside the prototype. The [baseline and assumptions template](../data/provided/template_baseline_and_assumptions.csv) has one row per parameter, including three annual totals, factor ranges and provenance, and a shared-cost allocation rule. The separate [measures package template](../data/provided/template_measures_package.csv) has one row per measure and belongs to the measures workstream.

From the repository root, generate the official baseline CSV and the supplementary frontend and audit evidence:

```sh
cd backend
uv run python -m app.pipeline.submission_export
uv run python -m app.pipeline.baseline_export
```

| Deliverable | Generated path |
|---|---|
| Official baseline and assumptions | `submission/template_baseline_and_assumptions.csv` |
| Supplementary frontend bundle | `out/baseline/baseline.json` |
| Supplementary per-fact audit | `out/baseline/baseline_details.csv` |

Both commands accept `--output-dir PATH` and use the same checked-in facts, research, and calculation pipeline. The official adapter preserves the template's eight columns, their order, its 17 parameters, and its unit labels. CHF per year has one net value in `value_mid`. Facility kWh per year and location-based emissions have low, mid, and high modeled subtotals. The emissions value is in kg CO₂e per year, with the original template label `kg CO2 per year` retained. The EU grid range and its provenance appear in the location-based emissions assumptions because the template has no separate EU row. Unavailable values and unimplemented bonus fields remain blank.

The allocation row describes the existing fact attribution, including subscription cost centers, gateway source departments, and the master resource mapping for cloud and hoster costs. The research proposal for an FTE-based redistribution was not applied. Energy and emissions totals carry their coverage and partial-usage counts. Use the audit CSV to trace the known subtotals to the underlying facts and assumptions.

Run `uv run pytest tests/test_submission_export.py tests/test_baseline_export.py` from `backend/` to check the official filename, schema, units, provenance, scenario order, blank fields, and reproducibility. The tests also parse strict JSON, check unique audit fact keys and cost-only rows, and reconcile the annual totals with monthly and dimension breakdowns.

The measures package builder (`uv run python -m app.measures.package`) uses the same calculated facts: it sums kWh and kg CO₂e per resource for each scenario, chooses the package against the −25 % cost and −40 % CO₂ targets, and writes `submission/measures_package.csv`. Its CO₂ reduction is measured against the known subtotal above, so it reports the target as met on the known baseline only while coverage is partial.

Before submission, review the coverage caveats and the allocation rule, obtain the completed measures table, and upload both official tables with the prototype to the event platform. Compare any proposed savings against the same period, scenarios, and accounting boundary, and review coverage gaps before assessing the 40% reduction target. The baseline export establishes no reduction claim.

## Limitations and planned work

Energy values use researched proxies. The storage factor assumes logical GB-days, and the GPU factor models the board. Energy and emissions cover only supported kinds and reported usage. The Swiss grid factor uses a consumption mix including imports. The German, Irish, and mixed EU factors use generation-based proxies, and the mixed EU factor represents the region rather than individual providers.

Automatic frontend loading and coverage-aware map labels are separate work.
