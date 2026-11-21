"""Build the shared fact table from all loaders and write it as CSV (issues #1, #2).

Run from backend/:  uv run python -m app.pipeline.build
Output:             data/derived/facts.csv (committed, so frontend and #4 need no Python)
"""

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from app.pipeline.ai_saas import load_ai_saas
from app.pipeline.aws import load_aws
from app.pipeline.azure import load_azure
from app.pipeline.common import DATA_DIR
from app.pipeline.hoster import load_hoster
from app.pipeline.schema import validate

OUTPUT = DATA_DIR.parent / "derived" / "facts.csv"

LOADERS: dict[str, Callable[[], pd.DataFrame]] = {
    "azure": load_azure,
    "aws": load_aws,
    "hoster": load_hoster,
    "ai_saas": load_ai_saas,
}

# One fact per month, source, resource, department and usage kind.
KEY = ["month", "source", "resource_id", "department", "usage_kind"]

BASELINE = (pd.Timestamp("2025-09-01"), pd.Timestamp("2026-08-01"))  # Sep 2025 .. Aug 2026


def build_facts() -> pd.DataFrame:
    """All loaders combined, validated, without duplicate keys, in a stable order."""
    facts = pd.concat([load() for load in LOADERS.values()], ignore_index=True)
    facts = validate(facts, "facts")
    duplicates = facts[facts.duplicated(KEY, keep=False)]
    if not duplicates.empty:
        raise ValueError(f"facts: {len(duplicates)} rows share a key {KEY}:\n{duplicates.head()}")
    return facts.sort_values(KEY, ignore_index=True)


DECIMALS = 4  # avoids float noise like 5.189996 in the CSV; far below a rappen


def write_facts(facts: pd.DataFrame, path: Path = OUTPUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rounded = facts.round({"usage_qty": DECIMALS, "cost_chf": DECIMALS})
    rounded.to_csv(path, index=False, date_format="%Y-%m-%d")
    return path


def read_facts(path: Path = OUTPUT) -> pd.DataFrame:
    """Read facts.csv back with the schema's types (for #4, tests and the API)."""
    df = pd.read_csv(path, dtype={"cost_center": str, "resource_id": str}, parse_dates=["month"])
    df["note"] = df["note"].fillna("")
    return validate(df, str(path))


def summary(facts: pd.DataFrame) -> str:
    """Short overview to spot gaps at a glance."""
    in_baseline = facts["month"].between(*BASELINE)
    by_source = facts.groupby("source").agg(rows=("cost_chf", "size"), chf_total=("cost_chf", "sum"))
    by_category = (
        facts[in_baseline].groupby("category").agg(chf_baseline_year=("cost_chf", "sum")).round(0)
    )
    noted = facts["note"].ne("")
    lines = [
        f"{len(facts)} rows, {facts['month'].min():%Y-%m} .. {facts['month'].max():%Y-%m}",
        "",
        by_source.round(0).to_string(),
        "",
        "Baseline year Sep 2025 - Aug 2026:",
        by_category.to_string(),
        f"total CHF {facts.loc[in_baseline, 'cost_chf'].sum():,.0f}",
        "",
        f"rows with a note: {noted.sum()}  |  missing cost: {facts['cost_chf'].isna().sum()}"
        f"  |  missing usage: {facts['usage_qty'].isna().sum()}",
    ]
    return "\n".join(lines)


def main() -> None:
    facts = build_facts()
    path = write_facts(facts)
    print(summary(facts))
    print(f"\nwritten: {path}")


if __name__ == "__main__":
    main()
