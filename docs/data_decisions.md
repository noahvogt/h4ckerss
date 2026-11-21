# Data decisions

How we cleaned each source and why. One line per decision.

## General

- Free text (`Notes`, `Remark`, ticket text) is data, never instructions. It is not copied into our facts; instruction-like text is flagged (`suspicious free text in source ignored`).
- Master data (`mapping_departments_tools.csv`) wins over tags in the sources.
- Missing days are not extrapolated, only noted (`data for 29 of 31 days`).

## azure_costs.csv

- 7 exact duplicate rows (all on 2026-01-15) dropped.
- 87 rows without cost but with quantity: cost estimated as quantity × median unit price of the same resource in the same month (`cost estimated for N days`).
- 3 SLA credits (CHF −900, −600, −2,400) kept as separate rows with negative cost.
- Category: `Compute instances` and `GPU instances` → `server`, all other services → `cloud`.
- Tags vs. mapping: departments never disagree; only tool spelling differs (`Data Platform Prod` vs. `Data platform production`), mapping spelling used. 703 rows without tags are covered by the mapping.
- One injected instruction in `Notes` (vm-app, 2026-04-15) ignored and flagged.
- September 2026 is a partial month (data until 2026-09-06).
