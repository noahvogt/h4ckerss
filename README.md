# h4ckerss

Hackathon case info: [docs/case_info.md](docs/case_info.md)

Background on Basel2037 and ALTYCA: [docs/knowledge_pack.md](docs/knowledge_pack.md)

Case data provided: [Fa-Bee/sprintd-basel-green-ai-data](https://github.com/Fa-Bee/sprintd-basel-green-ai-data)

## Backend

Needs [uv](https://docs.astral.sh/uv/).

```sh
cd backend
uv sync              # install dependencies
uv run fastapi dev   # API on http://127.0.0.1:8000, docs at /docs
uv run pytest        # tests
uv run python -m app.pipeline.build   # rebuild data/derived/facts.csv from data/provided
uv run python -m app.measures.catalogue   # rebuild data/derived/measures.csv (measures with effort and CHF savings)
uv run python -m app.measures.package     # best package under target and budget -> submission/measures_package.csv
```

### API for the frontend

Same numbers as the files in `submission/`. Details and response schemas at `/docs`.

| Endpoint | For |
|---|---|
| `GET /api/baseline` | Page 1: cost, kWh, CO₂ per year, month, location, department, tool; drivers; `rows` for the map |
| `GET /api/package` | Page 2: recommended package, targets, per-measure savings, CO₂ low/mid/high, alternatives (`?approvals=true` includes measures that need a human decision) |
| `POST /api/package/evaluate` | Page 2: recalculate after approve/reject, body `{"measure_ids": [...]}` |
| `GET /api/measures` | all measures, also blocked ones, each with its own savings |
| `GET /api/rules/explain?resource_id=…&change=…` | explain box (every measure has its `explain_url`) |
| `GET /api/rules/contradictions` | contradicting sources and which one we trust |
| `GET /api/guide/examples` | Official example questions and Guide mode |
| `POST /api/guide/ask` | Guide reply, sources and provider-reported token usage for `{"question": "..."}` |

Unknown values are `null`, never 0. CORS is open, so a page served from another port can call the API.

## WattsON Guide

From `backend/`, run `uv sync` and `uv run uvicorn app.main:app`. Open
<http://127.0.0.1:8000/> or <http://127.0.0.1:8000/package.html> and click **Ask Wattson**.
The Guide works in **Demo mode** without credentials. Try **Unused AI seats**, **GPU on demand**,
and **Production off-hours**. These use the official prompts in
[example_questions.md](data/provided/example_questions.md). Expand **Sources and calculations**
to see repository paths and live API evidence where available.

The Guide also explains annual baseline totals and the emissions methodology, top drivers,
the recommended package, and individual measure IDs such as `M-vm-test-downsize`. Each question
is independent and answers use the baseline period regardless of the dashboard’s date slider.
The Guide uses calculated backend results, which can differ from the surrounding dashboard’s
illustrative figures.
Energy and emissions subtotals describe the usage the pipeline could model. Production
scheduling still requires the approvals shown in the answer.

Set `OPENAI_API_KEY` before starting the backend to enable OpenAI topic routing.
`WATTSON_GUIDE_OPENAI_MODEL` defaults to `gpt-4.1-mini`. The backend sends the question and
the supported topic descriptions to OpenAI. The server writes the answers from the project’s
calculations and selects the sources. Local routing remains available if the provider fails.

Provider attempts append to `out/guide/usage.jsonl` at the repository root. Override the path
with `WATTSON_GUIDE_USAGE_LOG`. The log records provider-reported input and output token counts
when available, without logging questions or keys. A local reply uses no provider tokens.
With both counts available, the shared pipeline applies the research CSV’s facility-inclusive
inference proxy to estimate mid-scenario electricity. This proxy uses the baseline token mix
and is not a measurement of the Guide model. Location-based CO₂e remains unknown unless
`WATTSON_GUIDE_GRID_LOCATION` identifies a verified inference region with a compatible factor
(`CH`, `DE`, `IE`, or the mixed `EU` proxy). These estimates track Guide use separately from the
historical baseline.

## Baseline submission

From `backend/`, generate the official baseline table and the supplementary evidence:

```sh
uv run python -m app.pipeline.submission_export
uv run python -m app.pipeline.baseline_export
uv run pytest tests/test_submission_export.py tests/test_baseline_export.py
```

The official output is [submission/template_baseline_and_assumptions.csv](submission/template_baseline_and_assumptions.csv). The supplementary JSON and audit CSV are written to `out/baseline/`. The baseline records annual CHF, kWh, and kg CO₂e, with partial physical coverage disclosed in the table. See the [methodology and validation notes](docs/baseline_calculation.md#official-submission).

For the final submission, review the baseline caveats and upload the prototype and both completed official tables. The measures table is generated with `uv run python -m app.measures.package` from the same baseline.
