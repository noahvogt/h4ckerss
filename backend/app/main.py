from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.routers import baseline, guide, measures, rules

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "provided"



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
app.include_router(guide.router)


class Health(BaseModel):
    status: str
    data_found: bool


@app.get("/api/health")
def health() -> Health:
    return Health(status="ok", data_found=(DATA_DIR / "README.md").exists())


app.mount("/", StaticFiles(directory=DATA_DIR.parents[1] / "frontend", html=True), name="frontend")
