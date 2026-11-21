# Data decisions

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
- 86 usage rows without cost: estimated the same way as Azure (`cost estimated for N days`).
- Support fee (`support`) is a monthly charge: cost only (`usage_kind` none), no day count. The missing September 2025 fee is estimated from the other months (CHF 900, like every other month).
- Tags: no department or tool disagrees with the mapping; empty tags (959 rows) are covered by the mapping.
- `sandbox` (test account, cost center 9100) kept as department `Test account`. It runs only on some days (gaps are real non-use here, not missing data). 16 rows are marked "please exclude" in the source: noted as `source marks rows for exclusion (kept)`. Whether the baseline excludes the test account is decided in #4, not by a remark in the data.
