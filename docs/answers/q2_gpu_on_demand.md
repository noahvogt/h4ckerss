# Example question 2: what does it bring to start the GPU server only when needed?

**Short answer: CHF 7,738 and about 163 kg CO₂ (location-based) per year, for 2 person-days (CHF 2,200) of effort. It pays back in about 3.4 months.** The server runs around the clock today but is busy about 6 % of the time outside the quarterly training. If it runs only on working days from 08:00 to 18:00 and around the clock on the training days, it runs 2,728 instead of 8,760 hours a year. The training days stay protected, and the Head of Consulting decides.

Resource: `gpu-ml` (server `gpu-ml-01`, Azure Frankfurt, development environment, AI pilot). Period: baseline year, September 2025 to August 2026. This is measure `M-gpu-ml-pause` in the recommended package (`submission/measures_package.csv`).

## 1. Today's utilisation

| What | Value | Source |
|---|---|---|
| Running time | 168 h in every one of 52 weeks (always on, as provisioned in T-1035) | `server_metrics_weekly.csv`, `it_tickets.csv` |
| GPU load, whole year | **9.2 %** on average (weighted by uptime) | `server_metrics_weekly.csv` |
| GPU load in the 4 training weeks | 42.9 % | `server_metrics_weekly.csv`, T-1101 |
| GPU load in the other 48 weeks | **6.4 %** | `server_metrics_weekly.csv` |
| CPU load | 4.2 % (weekly average), 4 % over the last 30 days | `server_metrics_weekly.csv`, `server_inventory.csv` |
| Billed GPU-hours | 8,640 h, CHF 11,238 (CHF 1.30 per GPU-hour, EUR converted at monthly rates) | `azure_costs.csv`, `exchange_rates.csv` |

The billing covers 8,640 of 8,760 hours because a few days are missing in the invoice data. The real work happens in the quarterly training: days 1–3 of January, April, July and October, together with the development cluster (T-1101).

## 2. The measure

The server runs on the **244 working days from 08:00 to 18:00** (Basel-Stadt calendar), and **around the clock on the 12 training days**:

244 × 10 h + 12 × 24 h = **2,728 h** of 8,760 h = 31.1 % of the year.

The server starts and stops on a schedule, and the training days start automatically. Ad-hoc work outside these hours needs a manual start.

## 3. Savings (open calculation)

Costs and energy fall with the running hours: Azure bills per GPU-hour, and the energy factor is the average power of a running server.

| Step | Calculation | Result |
|---|---|---|
| Hours saved | 8,640 GPU-h × (1 − 0.3114) | 5,950 GPU-h |
| **CHF per year** | 5,950 × CHF 1.30 | **CHF 7,738** |
| Energy today | 8,640 h × 0.0695 kWh × PUE 1.16 | 696 kWh |
| **kWh per year** | 696 × (1 − 0.3114) | **480 kWh** |
| **CO₂ per year** | 480 kWh × 0.339 kg/kWh (German grid) | **163 kg** |
| Effort | 2 person-days × CHF 1,100: schedule with automatic start/stop, keep quarterly training | CHF 2,200 |
| Payback | 2,200 / 7,738 × 12 | 3.4 months |

### Assumptions, with source and range

| Assumption | Low | Mid | High | Source |
|---|---|---|---|---|
| Energy per GPU-hour (board) | 0.046 kWh (idle, 0 % load) | 0.0695 kWh (9.2 % observed load) | 0.300 kWh (100 % load) | Cloud Carbon Footprint methodology (46 W idle), NVIDIA A100 80 GB PCIe brief (300 W), observed load from `server_metrics_weekly.csv` |
| PUE (data centre overhead) | 1.09 | 1.16 | 1.54 | Google 2025 fleet, Microsoft FY25 EMEA, Uptime Institute 2025 survey |
| Grid mix Germany | 0.285 | 0.339 | 0.399 kg CO₂e/kWh | Ember monthly electricity data, Germany, Sep 2025 – Aug 2026 |

The full source references are in `submission/template_baseline_and_assumptions.csv`.

| Scenario | kWh saved | **CO₂ saved** | Idle-only lower bound |
|---|---|---|---|
| Low | 298 | **85 kg** | 85 kg |
| Mid | 480 | **163 kg** | 108 kg |
| High | 2,749 | **1,097 kg** | 168 kg |

- **Realistic range: about 85–163 kg CO₂ per year.** The high scenario assumes the board runs at full load all year, which the metrics clearly contradict (9 %). It is a sensitivity bound for power, not a realistic load.
- **Idle-only lower bound:** If all work done today simply moves into the remaining hours, only the idle power of the off hours is saved: 5,950 h × 46 W × PUE × grid, which is **108 kg** in the mid scenario. Outside the training weeks the load is only 6 %, so most of the off hours are idle anyway.
- **CHF does not depend on these assumptions.** Azure bills every running GPU-hour, so CHF 7,738 holds in every scenario.

## 4. Who decides, and what stays protected

- **Status: allowed outside protection windows.** Rule R04 protects the training days 1–3 of January, April, July and October (T-1035, T-1101). The schedule must keep the server running on those days.
- **Head of Consulting** decides: the server belongs to Consulting (`mapping_departments_tools.csv`, AI pilot) and so does the training.
- **Head of IT** implements the schedule and the automatic start.
- **Switching the server off for good is blocked:** the training needs it every quarter.

In the app: `GET /api/rules/explain?resource_id=gpu-ml&change=pause` for the explain box, and `GET /api/package` for the savings in the package.

## 5. Interaction with other measures

The training uses the GPU server together with the development cluster `dp-dev`, which pauses on the same training days (measure `M-dp-dev-pause`, rule R02). Both schedules must start on the same training days.

## Reproduce

All numbers come from `backend/app/measures/gpu.py`, which uses the same catalogue, package and research factors as the submission. `backend/tests/test_gpu.py` pins them, so this page fails the tests if the data or the factors change.

```sh
cd backend
uv run python -m app.measures.gpu
```
