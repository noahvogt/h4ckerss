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
