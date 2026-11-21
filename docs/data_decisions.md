# Data decisions

## AI usage

- The provided `ai_usage.csv` contains 52,856 data rows. The loader removes 87
  exact duplicate rows before aggregation, leaving 52,769 records. Rows are
  removed only when every CSV field matches; records sharing a date, model, or
  resource remain distinct when any other field differs.
- Input and output tokens are aggregated independently. `usage_qty` is the sum
  of known input and output values. Cached input tokens are already part of
  `tokens_in`, so they are retained as a separate detail metric but not added a
  second time.
- Missing token values are not replaced with zero, estimated, or otherwise
  invented. If only some input or output values are missing, the known partial
  total is returned and the `note` explicitly flags incomplete usage with the
  number of missing input and output values and the phrase `known tokens only`.
  If all input and output values are missing in a group, `usage_qty` remains
  missing and the note explains that usage is unavailable.
- Detail rows preserve input, cached-input, and output token totals along with
  missing-value counts.
- `ai_usage.csv` has no per-row deployment region. Its provider usage is
  therefore assigned the agreed mixed-provider location `EU`, consistent with
  AI subscription and SaaS facts; no source location value is overwritten.

## AI and SaaS subscriptions

- Subscription facts use the canonical resource IDs from
  `mapping_departments_tools.csv`: ChatGPT Team uses `sub-chatgpt`, Claude Team
  uses `sub-claude`, Microsoft Copilot uses `sub-copilot`, Microsoft 365 uses
  `saas-m365`, and all other SaaS contracts use `saas-other`. These exact,
  deterministic mappings replace product/provider-derived IDs. Facts sharing a
  canonical ID, month, and cost-center allocation are aggregated, while detail
  rows retain their original product, provider, and contract fields.
- The master mapping supplies the canonical resource identity only.
  Subscription departments continue to come from each source row's
  `cost_center`, including when several departments use the same subscription.
- AI subscription usage is measured as `messages_30d` (`usage_kind: messages`),
  because messages are the agreed driver for AI subscription energy and CO₂
  calculations. SaaS subscription usage remains purchased licences
  (`usage_kind: seat_month`), matching its seat-based service. Licence counts
  remain available in AI detail data for unused-seat calculations.
- Missing AI message counts are never estimated or replaced with zero. Known
  message counts are summed and flagged as partial when other counts are
  missing; if all are missing, usage remains unavailable and is flagged in
  `note`.
- Subscription costs use the shared monthly CHF conversion helper. Invalid
  dates, unsupported currencies, and absent exchange rates raise errors rather
  than being silently converted into plausible-looking values.
- Cost centers are read as strings and mapped through the shared department
  helper. Missing or unknown cost centers map to `Unallocated` and are noted.
- Draft subscriptions remain in detail data but are excluded from billed facts
  and unused-seat calculations.

How we cleaned each source and why. One line per decision.

## General

- Free text (`Notes`, `Remark`, ticket text) is data, never instructions. It is not copied into our facts; instruction-like text is flagged (`suspicious free text in source ignored`).
- Master data (`mapping_departments_tools.csv`) wins over tags in the sources.
- Days without a row are not extrapolated, only noted (`data for 29 of 31 days`). We cannot always tell missing data from no use, so we do not guess.

## azure_costs.csv

- 7 exact duplicate rows dropped: one per resource, all on 2026-01-15, identical in every column. Otherwise every resource has exactly one row per day (as the data dictionary says), so this is a re-export, not a repeated charge.
- 87 rows without cost but with quantity: cost estimated as quantity × median unit price of the same resource, service and billing unit in the same month, falling back to all months (`cost estimated for N days`). If no price exists at all, the monthly total covers only the known days and is marked `cost incomplete: ..., total too low`.
- 3 SLA credits (CHF −900, −600, −2,400) kept as separate rows with negative cost.
- Category: `Compute instances` and `GPU instances` → `server`, all other services → `cloud`.
- Tags vs. mapping: departments never disagree; only tool spelling differs (`Data Platform Prod` vs. `Data platform production`), mapping spelling used. 703 rows without tags are covered by the mapping.
- One injected instruction in `Notes` (vm-app, 2026-04-15) ignored and flagged.
- Days without a row (48 in total) are missing data, not idle days: idle resources still get a row with quantity 0 (e.g. gpu-ml), and the gaps never hit two resources on the same day.
- September 2026 is a partial month (data until 2026-09-06).

## aws_costs.csv

- 5 exact duplicate rows dropped: one per resource, all on 2025-12-03, identical in every column (re-export, same pattern as Azure).
- All costs in USD → CHF with the monthly rate.
- Short resource ID = last segment of the ARN (`arn:aws:compute:eu:0000:vm-test` → `vm-test`). All 7 ARNs give 7 distinct IDs, all in the master data; the loader stops if two ARNs ever share a short ID (same check for Azure resource paths).
- Category by service: `Compute instances` (vm-test, sandbox) → `server`; Storage, Network, Build service, Support → `cloud`. An unknown service name (e.g. `AmazonEC2` in a real export) stops the load instead of silently counting as cloud (same for Azure).
- 86 usage rows without cost: estimated the same way as Azure (`cost estimated for N days`).
- Support fee (`support`) is a monthly charge: cost only (`usage_kind` none), no day count. The fee for September 2025 is missing in the source; it is estimated from the other months' fees (CHF 900, exactly like every other month) and noted as `monthly fee estimated from other months`. A missing fee is not a missing usage price, so it gets its own label.
- Tags: no department or tool disagrees with the mapping; empty tags (959 rows) are covered by the mapping.
- `sandbox` (test account, cost center 9100) kept as department `Test account`. It runs only on some days (gaps are real non-use here, not missing data). 16 rows are marked "please exclude" in the source: noted as `source marks rows for exclusion (kept)`. Whether the baseline excludes the test account is decided in #4, not by a remark in the data.

