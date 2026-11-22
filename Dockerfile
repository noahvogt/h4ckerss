# WattsON: API and frontend in one container (FastAPI serves frontend/ under /).
FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dependencies first, so code changes do not reinstall them.
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project

# The app reads data/, submission/, docs/ and frontend/ relative to the repository root.
COPY . /app

# Runtime writes: approval decisions (data/state) and the Guide usage log (out/).
RUN useradd --uid 1000 --no-create-home --home-dir /app wattson \
    && mkdir -p /app/out \
    && chown -R wattson /app/data/state /app/out
USER wattson

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["fastapi", "run", "--host", "0.0.0.0", "--port", "8000"]
