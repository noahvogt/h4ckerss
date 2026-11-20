from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "provided"

app = FastAPI(title="WattsON API", version="0.1.0")

# Hackathon setting: allow any frontend origin. Restrict before real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Health(BaseModel):
    status: str
    data_found: bool


@app.get("/api/health")
def health() -> Health:
    return Health(status="ok", data_found=(DATA_DIR / "README.md").exists())
