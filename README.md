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

The FastAPI app also serves the frontend:

- `http://127.0.0.1:8000/` -> baseline page
- `http://127.0.0.1:8000/package.html` -> package page
- `http://127.0.0.1:8000/forecast.html` -> forecast page
- `http://127.0.0.1:8000/integrations.html` -> integrations page

The frontend checks the API at startup. If an endpoint is unavailable, or a frontend
demo feature has no one-to-one backend contract yet, it keeps the existing mocked data
and shows that in the API status panel.

Approval/rejection choices are saved by the backend in
`data/state/approval_decisions.json`, so the Package page restores them after refresh.

Wattson can call an LLM through the backend. Set `OPENAI_API_KEY` in your shell or in a
local, ignored `.env` file at the repo root or under `backend/`:

```sh
OPENAI_API_KEY=sk-...
WATTSON_MODEL=gpt-5
```

The browser never receives the key. Without a key, `/api/wattson/chat` returns a local
fallback answer so the UI still works.

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
| `POST /api/wattson/chat` | LLM-backed Wattson chat using current UI context, backend summaries, and source metadata; falls back locally without `OPENAI_API_KEY` |

Unknown values are `null`, never 0. CORS is open, so a page served from another port can call the API.

## Baseline submission

From `backend/`, generate the official baseline table and the supplementary evidence:

```sh
uv run python -m app.pipeline.submission_export
uv run python -m app.pipeline.baseline_export
uv run pytest tests/test_submission_export.py tests/test_baseline_export.py
```

The official output is [submission/template_baseline_and_assumptions.csv](submission/template_baseline_and_assumptions.csv). The supplementary JSON and audit CSV are written to `out/baseline/`. The baseline records annual CHF, kWh, and kg CO₂e, with partial physical coverage disclosed in the table. See the [methodology and validation notes](docs/baseline_calculation.md#official-submission).

For the final submission, review the baseline caveats and upload the prototype and both completed official tables. The measures table is generated with `uv run python -m app.measures.package` from the same baseline.
