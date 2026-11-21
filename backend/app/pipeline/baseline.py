"""Select and validate the monthly facts for the baseline year."""

import pandas as pd

from app.pipeline.build import BASELINE, KEY
from app.pipeline.common import mapping
from app.pipeline.schema import validate


def select_baseline_facts(facts: pd.DataFrame) -> pd.DataFrame:
    """Return a validated copy of the baseline rows in their original order."""
    facts = validate(facts, name="baseline input")
    baseline = facts.loc[facts["month"].between(*BASELINE)].copy()

    expected_months = pd.date_range(*BASELINE, freq="MS")
    missing_months = expected_months.difference(baseline["month"])
    if not missing_months.empty:
        months = ", ".join(missing_months.strftime("%Y-%m"))
        raise ValueError(f"baseline facts: missing baseline months: {months}")

    duplicates = baseline.duplicated(KEY, keep=False)
    if duplicates.any():
        raise ValueError(
            f"baseline facts: {duplicates.sum()} rows have duplicate fact keys {KEY}"
        )

    resource_ids = baseline["resource_id"]
    missing_ids = resource_ids.isna() | resource_ids.str.strip().eq("")
    if missing_ids.any():
        raise ValueError(f"baseline facts: missing resource IDs in {missing_ids.sum()} row(s)")

    unknown_ids = resource_ids.loc[~resource_ids.isin(mapping().index)].unique()
    if len(unknown_ids):
        raise ValueError(f"baseline facts: unknown resource IDs: {unknown_ids.tolist()}")

    return baseline
