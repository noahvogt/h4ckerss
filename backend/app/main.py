from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.routers import baseline, measures, rules, wattson

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "provided"
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
STATE_DIR = Path(__file__).resolve().parents[2] / "data" / "state"
APPROVALS_FILE = STATE_DIR / "approval_decisions.json"



@asynccontextmanager
async def lifespan(_: FastAPI):
    """Compute the baseline and the packages once at startup (a few seconds), so the first
    request in a demo is as fast as the others. The data does not change while running."""
    baseline.warm_up()
    measures.warm_up()
    yield


app = FastAPI(title="WattsON API", version="0.1.0", lifespan=lifespan)

# Hackathon setting: allow any frontend origin. Restrict before real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rules.router)
app.include_router(baseline.router)
app.include_router(measures.router)
app.include_router(wattson.router)

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="frontend-assets")
    app.mount("/data", StaticFiles(directory=FRONTEND_DIR / "data"), name="frontend-data")


class Health(BaseModel):
    status: str
    data_found: bool


class ApprovalDecision(BaseModel):
    state: Literal["pending", "ok", "no"]


class ApprovalDecisions(BaseModel):
    decisions: dict[str, Literal["pending", "ok", "no"]]


def _read_approval_decisions() -> dict[str, str]:
    if not APPROVALS_FILE.exists():
        return {}
    try:
        data = json.loads(APPROVALS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, "approval decisions file is not valid JSON") from exc
    decisions = data.get("decisions", data)
    if not isinstance(decisions, dict):
        raise HTTPException(500, "approval decisions file must contain an object")
    return {str(k).lower(): v for k, v in decisions.items() if v in {"pending", "ok", "no"}}


def _write_approval_decisions(decisions: dict[str, str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"decisions": decisions}, indent=2, sort_keys=True)
    tmp = APPROVALS_FILE.with_suffix(".json.tmp")
    tmp.write_text(payload + "\n", encoding="utf-8", newline="\n")
    tmp.replace(APPROVALS_FILE)


@app.get("/api/health")
def health() -> Health:
    return Health(status="ok", data_found=(DATA_DIR / "README.md").exists())


@app.get("/api/approvals")
def approval_decisions() -> ApprovalDecisions:
    """Saved frontend approval/rejection choices for demo persistence."""
    return ApprovalDecisions(decisions=_read_approval_decisions())


@app.put("/api/approvals/{measure_id}")
def save_approval_decision(measure_id: str, decision: ApprovalDecision) -> ApprovalDecisions:
    """Persist one approval card state. Use `pending` to undo a decision."""
    key = measure_id.lower()
    if not key or any(ch in key for ch in "/\\"):
        raise HTTPException(422, "invalid measure id")
    decisions = _read_approval_decisions()
    if decision.state == "pending":
        decisions.pop(key, None)
    else:
        decisions[key] = decision.state
    _write_approval_decisions(decisions)
    return ApprovalDecisions(decisions=decisions)


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    if not FRONTEND_DIR.exists():
        raise HTTPException(404, "frontend directory not found")
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/{page_name}.html", include_in_schema=False)
def frontend_page(page_name: str) -> FileResponse:
    if page_name not in {"index", "package", "forecast", "integrations"}:
        raise HTTPException(404, "frontend page not found")
    page = FRONTEND_DIR / f"{page_name}.html"
    if not page.exists():
        raise HTTPException(404, "frontend page not found")
    return FileResponse(page)
