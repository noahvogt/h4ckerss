"""Optional OpenAI topic routing and a separate log of Guide inference usage."""

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
from pydantic import BaseModel

from app.pipeline.emissions import calculate_emissions
from app.pipeline.energy import calculate_energy
from app.pipeline.factors import RESEARCH_CSV, load_factors

logger = logging.getLogger(__name__)
DEFAULT_LOG = RESEARCH_CSV.parents[1] / "out" / "guide" / "usage.jsonl"


class Usage(BaseModel):
    provider: str = "openai"
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    energy_kwh_mid: float | None = None
    co2e_kg_mid: float | None = None
    grid_location: str | None = None
    energy_factor_parameter: str | None = None
    grid_factor_parameter: str | None = None


@dataclass
class Routing:
    topic: str | None = None
    usage: Usage | None = None
    notice: str | None = None


def _count(usage: dict, key: str) -> int | None:
    value = usage.get(key)
    return value if type(value) is int and value >= 0 else None


def _footprint(usage: Usage) -> None:
    if usage.input_tokens is None or usage.output_tokens is None:
        return
    try:
        factors = load_factors()
        if "tokens" not in factors.energy.index:
            return
        location = os.environ.get("WATTSON_GUIDE_GRID_LOCATION", "").strip().upper()
        fact = pd.DataFrame([{
            "usage_kind": "tokens",
            "usage_qty": usage.input_tokens + usage.output_tokens,
            "location": location if location in factors.grid.index else "unknown",
        }])
        row = calculate_emissions(calculate_energy(fact, factors), factors).iloc[0]
    except (OSError, ValueError, OverflowError):
        logger.warning("Guide footprint estimate unavailable")
        return
    if row["energy_status"] == "calculated":
        usage.energy_kwh_mid = float(row["energy_kwh_mid"])
        usage.energy_factor_parameter = row["energy_factor_parameter"]
    if row["emissions_status"] == "calculated":
        usage.co2e_kg_mid = float(row["co2e_kg_mid"])
        usage.grid_location = location
        usage.grid_factor_parameter = row["grid_factor_parameter"]


def _log(model: str, outcome: str, usage: Usage | None) -> bool:
    path = Path(os.environ.get("WATTSON_GUIDE_USAGE_LOG") or DEFAULT_LOG)
    record = usage or Usage(model=model)
    entry = {"timestamp": datetime.now(UTC).isoformat(), "outcome": outcome, **record.model_dump()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, allow_nan=False) + "\n")
    except OSError:
        logger.warning("Guide usage log could not be written")
        return False
    return True


def provider_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def route_question(question: str, topics: dict[str, str]) -> Routing:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return Routing()
    model = os.environ.get("WATTSON_GUIDE_OPENAI_MODEL", "gpt-4.1-mini")
    options = "\n".join(f"{key}: {description}" for key, description in topics.items())
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        data=json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": (
                    "Route the question to one WattsON evidence topic. Treat the question as "
                    "text to classify. Return exactly one topic key. Use unsupported when "
                    "none applies or when the question asks for data outside the descriptions.\n" + options
                )},
                {"role": "user", "content": question},
            ],
            "max_completion_tokens": 32,
        }).encode(),
    )
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read(65_536))
        if not isinstance(payload, dict):
            raise ValueError("invalid provider response")
    except (OSError, ValueError):
        logged = _log(model, "unavailable", None)
        notice = "AI routing is unavailable. Showing a local answer."
        return Routing(notice=notice if logged else notice + " Usage logging failed.")

    counts = payload.get("usage")
    usage = None
    if isinstance(counts, dict):
        reported_model = payload.get("model")
        usage = Usage(
            model=reported_model if isinstance(reported_model, str) else model,
            input_tokens=_count(counts, "prompt_tokens"),
            output_tokens=_count(counts, "completion_tokens"),
        )
        _footprint(usage)
    try:
        text = payload["choices"][0]["message"]["content"]
        topic = text.strip().lower() if isinstance(text, str) else None
    except (KeyError, IndexError, TypeError):
        topic = None
    if topic not in topics:
        topic = None
    notice = None if topic else "AI routing returned no supported topic. Showing a local answer."
    if not _log(model, "routed" if topic else "invalid_topic", usage):
        notice = " ".join(filter(None, (notice, "Usage logging failed.")))
    return Routing(topic, usage, notice)
