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
- Short resource ID = last segment of the ARN (`arn:aws:compute:eu:0000:vm-test` → `vm-test`). All 7 ARNs give 7 distinct IDs, all in the master data; the loader stops if two ARNs ever share a short ID (same check for Azure resource paths).
- Category by service: `Compute instances` (vm-test, sandbox) → `server`; Storage, Network, Build service, Support → `cloud`. An unknown service name (e.g. `AmazonEC2` in a real export) stops the load instead of silently counting as cloud (same for Azure).
- 86 usage rows without cost: estimated the same way as Azure (`cost estimated for N days`).
- Support fee (`support`) is a monthly charge: cost only (`usage_kind` none), no day count. The fee for September 2025 is missing in the source; it is estimated from the other months' fees (CHF 900, exactly like every other month) and noted as `monthly fee estimated from other months`. A missing fee is not a missing usage price, so it gets its own label.
- Tags: no department or tool disagrees with the mapping; empty tags (959 rows) are covered by the mapping.
- `sandbox` (test account, cost center 9100) kept as department `Test account`. It runs only on some days (gaps are real non-use here, not missing data). 16 rows are marked "please exclude" in the source: noted as `source marks rows for exclusion (kept)`. Whether the baseline excludes the test account is decided in #4, not by a remark in the data.

## hoster_invoice.csv

- No resource key: each `Item` label is matched to the master data by tool name (`Web hosting and CDN` → `web-cdn`, `Logging and monitoring` → `logs`, `Project file storage` → `st-proj`). An unknown label stops the load instead of being guessed.
- Dates are `DD.MM.YYYY`; amounts are already CHF.
- 3 exact duplicate rows dropped: one per item, all on 2026-06-01 (re-export, same pattern as Azure and AWS).
- 35 rows without amount: estimated the same way as Azure (`cost estimated for N days`).
- No region in the file: the hoster runs in Zurich (`extra/data_center_locations.csv`: Swiss Hoster, Switzerland (Zurich), used by the SME).
- 189 rows without cost center: the master data supplies it. Where the source has a cost center, it always matches the master data.
- One injected instruction in `Remark` (st-proj, July 2026) ignored and flagged.
- All hoster services (Log storage, Storage, Web hosting/CDN) are `cloud`; an unknown service name stops the load (same rule as Azure and AWS).
