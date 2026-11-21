import csv
import json
import os
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routers import baseline, measures, rules

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "provided"
ROOT_DIR = Path(__file__).resolve().parents[3]
MODEL = os.getenv("WATTSON_MODEL", "gpt-5")

router = APIRouter(prefix="/api/wattson", tags=["wattson"])


class WattsonMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2400)


class WattsonRequest(BaseModel):
    message: str = Field(max_length=2400)
    page: str = Field(default="", max_length=80)
    ui_context: dict[str, Any] = Field(default_factory=dict)
    history: list[WattsonMessage] = Field(default_factory=list, max_length=10)


class WattsonResponse(BaseModel):
    reply: str
    model: str
    live: bool
    fallback: bool = False


def _safe_number(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 3)
    return value


def _compact(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {str(k)[:80]: _compact(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_compact(v, depth + 1) for v in value[:25]]
    return _safe_number(value)


@lru_cache(maxsize=1)
def _source_catalog() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(DATA_DIR.rglob("*")):
        if path.suffix.lower() not in {".csv", ".jsonl", ".md"}:
            continue
        rel = path.relative_to(DATA_DIR).as_posix()
        item: dict[str, Any] = {"file": rel}
        try:
            if path.suffix.lower() == ".csv":
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.reader(handle)
                    header = next(reader, [])
                    first = next(reader, [])
                item["columns"] = header[:18]
                item["sample"] = first[:8]
            elif path.suffix.lower() == ".jsonl":
                with path.open("r", encoding="utf-8") as handle:
                    first_line = next((line for line in handle if line.strip()), "{}")
                parsed = json.loads(first_line)
                item["columns"] = list(parsed.keys())[:18] if isinstance(parsed, dict) else []
                item["sample"] = dict(list(parsed.items())[:8]) if isinstance(parsed, dict) else parsed
            else:
                item["summary"] = path.read_text(encoding="utf-8", errors="ignore")[:1200]
        except Exception as exc:
            item["error"] = str(exc)
        out.append(item)
    return out


@lru_cache(maxsize=1)
def _application_context() -> dict[str, Any]:
    package = measures.package(approvals=True, alternatives=5)
    return {
        "backend": {
            "baseline": _compact(baseline.baseline()),
            "package": _compact(package.model_dump()),
            "measures": _compact([m.model_dump() for m in measures.measures()]),
            "contradictions": _compact([c.model_dump() for c in rules.contradictions()]),
        },
        "data_sources": _source_catalog(),
    }


def _fallback(req: WattsonRequest) -> str:
    page = req.page or "this page"
    context = req.ui_context or {}
    selected = context.get("selected") or context.get("visible") or {}
    hint = "I can still use the app context, but the OpenAI API key is not configured on the backend."
    if "forecast" in page.lower():
        return f"{hint} From the current forecast controls, compare the selected path against the package path and check whether cost and CO2 targets still hold."
    if "package" in page.lower():
        return f"{hint} On the package page, review pending approvals first because rejected measures change the recommended savings."
    if "integration" in page.lower():
        return f"{hint} On Integrations, import AWS/GCP invoices as files for now; live connectors are mocked until /api/connect exists."
    if selected:
        return f"{hint} Current UI context says: {json.dumps(_compact(selected), ensure_ascii=False)[:350]}"
    return f"{hint} Ask about regional waste, approvals, imported sources, forecast assumptions, or which source file supports a number."


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    for path in (ROOT_DIR / ".env", ROOT_DIR / "backend" / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, raw = text.split("=", 1)
            if key.strip() == name:
                return raw.strip().strip('"').strip("'") or None
    return None


def _call_openai(req: WattsonRequest, api_key: str) -> str:
    app_context = _application_context()
    history = [m.model_dump() for m in req.history[-8:]]
    payload = {
        "model": _env_value("WATTSON_MODEL") or MODEL,
        "instructions": (
            "You are Wattson, a concise GreenOps analyst inside the WattsOn demo. "
            "Use only the supplied app context, UI context, backend summaries, and source catalog. "
            "Give practical next actions, cite source filenames when useful, and say when something is mocked or missing. "
            "Do not ask for secrets. Do not claim that a live cloud connector is working unless the context says it is. "
            "Keep answers under 140 words unless the user asks for details."
        ),
        "input": [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_message": req.message,
                        "current_page": req.page,
                        "recent_chat": history,
                        "ui_context": _compact(req.ui_context),
                        "application_context": app_context,
                    },
                    ensure_ascii=False,
                ),
            }
        ],
        "max_output_tokens": 1800,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:800]
        raise HTTPException(502, f"OpenAI request failed: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"OpenAI request failed: {exc.reason}") from exc

    text = data.get("output_text")
    if text:
        return str(text).strip()
    pieces: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                pieces.append(str(content["text"]))
    return "\n".join(pieces).strip() or "I could not read a text answer from the model response."


@router.post("/chat")
def chat(req: WattsonRequest) -> WattsonResponse:
    api_key = _env_value("OPENAI_API_KEY")
    if not api_key:
        return WattsonResponse(reply=_fallback(req), model=_env_value("WATTSON_MODEL") or MODEL, live=False, fallback=True)
    return WattsonResponse(reply=_call_openai(req, api_key), model=_env_value("WATTSON_MODEL") or MODEL, live=True)
