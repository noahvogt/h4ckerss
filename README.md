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

## Baseline submission

From `backend/`, generate the official baseline table and the supplementary evidence:

```sh
uv run python -m app.pipeline.submission_export
uv run python -m app.pipeline.baseline_export
uv run pytest tests/test_submission_export.py tests/test_baseline_export.py
```

The official output is [submission/template_baseline_and_assumptions.csv](submission/template_baseline_and_assumptions.csv). The supplementary JSON and audit CSV are written to `out/baseline/`. The baseline records annual CHF, kWh, and kg CO₂e, with partial physical coverage disclosed in the table. See the [methodology and validation notes](docs/baseline_calculation.md#official-submission).

For the final submission, review the baseline caveats and upload the prototype and both completed official tables. The measures table is generated with `uv run python -m app.measures.package` from the same baseline.
