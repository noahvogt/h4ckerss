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
