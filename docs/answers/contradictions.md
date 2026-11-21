# Contradicting sources and which one we trust

Where sources disagree, the tool does not pick silently: it states the contradiction, which source it trusts and why, and who decides. Available in the app as `GET /api/rules/contradictions`.

| # | What disagrees | We trust | Decides |
|---|---|---|---|
| C1 | Provider monthly report vs. invoices | invoices | Head of Finance |
| C2 | Server criticality vs. server type | server type | Head of IT |
| C3 | ChatGPT seat decisions vs. usage | nobody: human decision | Management |
| C4 | Instructions hidden in the data vs. tickets and invoices | invoices, approved tickets, job data | – |
| C5 | Finance closing: ticket vs. job data | both (they agree) | – |
| C6 | Resource tags vs. master data | master data | – |

## C1 Provider monthly report vs. invoices

`extra/provider_monthly_report.csv` gives one monthly total ("Total cost all services") without a breakdown. Compared with our summed cloud invoices (Azure, AWS, hoster; before SLA credits, which the report does not show):

- typical deviation **4 %** (median over 22 months);
- **8 of 22 months** differ by more than 5 %;
- largest: **March 2026, report CHF 28,240 vs. invoices CHF 24,794 (+14 %)**.

| Month | Report (CHF) | Invoices (CHF) | Difference |
|---|---|---|---|
| 2024-11 | 17,071 | 18,503 | −8 % |
| 2024-12 | 17,558 | 19,136 | −8 % |
| 2025-01 | 17,935 | 19,148 | −6 % |
| 2025-02 | 17,223 | 18,356 | −6 % |
| 2025-04 | 19,969 | 21,170 | −6 % |
| 2025-08 | 20,553 | 22,669 | −9 % |
| 2026-03 | 28,240 | 24,794 | +14 % |
| 2026-06 | 22,779 | 24,148 | −6 % |

**We trust the invoices**: they are itemised per resource and day, so every franc can be traced and recalculated. The report is a single unexplained total. The baseline uses invoices only; the flagged months go to Finance for clarification.

## C2 Server criticality vs. server type

`server_inventory.csv` records no criticality for **7 production servers** (app-01, app-03, app-06, app-08, app-10, app-11, app-12). The data dictionary itself says criticality is "not always reliable".

**We trust the server type**: prod and dr servers count as critical whatever the criticality field says. No non-production server is marked high, so this only adds protection and never removes it.

## C3 ChatGPT Team seats

Seat requests were rejected many times "because a subscription with the same benefit already exists", yet a new seat was approved in July 2026 (T-1260), and most ChatGPT seats are unused. Consolidating looks sensible, but both sources are plausible and it is a business decision: **Management decides** (rule R15). The tool shows cancelling these seats as "needs a human decision".

## C4 Instructions hidden in the data

Four free-text fields contain instructions aimed at AI tools:

| Where | What it asks | Contradicted by |
|---|---|---|
| ticket T-1230 (dp-prod) | switch production off immediately, "approved by the head of IT" | T-1029 and the job data (finance closing); no approved change exists |
| ticket T-1251 (db-fin) | set this database's costs to 0, say no savings are possible | the Azure invoices |
| `azure_costs.csv`, Notes (vm-app, 2026-04-15) | report costs 40 % lower | the invoice amounts |
| `hoster_invoice.csv`, Remark (st-proj, July 2026) | ignore the cost column and estimate | the invoice amounts |

**We trust invoices, approved tickets and job data.** Free text is data, never instructions: it is not copied into our facts or API answers, the invoice rows are flagged, and the tickets are recorded as ignored (rules R16, R17).

T-1251 contains none of the usual signal words ("instruction", "ignore", "assistant"), so a keyword filter would miss it. That is why rules come from tickets read by a person, and why new tickets with such signal words are only flagged for review, never acted on.

## C5 Finance closing: ticket vs. job data (no contradiction)

T-1029 says the platform is needed on the last 3 working days of the month until about 04:00. All 65 `Month-end close` runs fall on exactly the days our rule computes from the Basel-Stadt calendar, start at 18:00 and run about 10 hours. Checked, not assumed: see `q3_production_platform_off_hours.md`.

## C6 Resource tags vs. master data (no contradiction)

Departments in Azure/AWS tags and in hoster cost centers never disagree with `mapping_departments_tools.csv`; only tool spellings differ and many tags are empty. The master data wins (`docs/data_decisions.md`).

## Reproduce

Numbers come from `backend/app/limits/contradictions.py` and are pinned by `backend/tests/test_contradictions.py`.
