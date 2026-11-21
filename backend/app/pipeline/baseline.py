"""Select and validate the monthly facts for the baseline year."""

from collections.abc import Collection

import pandas as pd

from app.pipeline.build import BASELINE, KEY
from app.pipeline.common import mapping
from app.pipeline.schema import validate

# Recurring billing and licence feeds in the case dataset.
_MONTHLY_BILLING_SOURCES = {
    "azure_costs.csv",
    "aws_costs.csv",
    "hoster_invoice.csv",
    "ai_subscriptions.csv",
    "saas_contracts.csv",
}


def select_baseline_facts(
    facts: pd.DataFrame,
    *,
    required_sources: Collection[str] | None = None,
) -> pd.DataFrame:
    """Validate the full input, then check baseline coverage and keys.

    The recurring billing feeds are required by default. An explicit collection
    replaces that set. An empty collection disables per-source coverage checks.
    """
    facts = validate(facts, name="baseline input")
    baseline = facts.loc[facts["month"].between(*BASELINE)].copy()

    expected_months = pd.date_range(*BASELINE, freq="MS")
    missing_months = expected_months.difference(baseline["month"])
    coverage_problems = []
    if not missing_months.empty:
        months = ", ".join(missing_months.strftime("%Y-%m"))
        coverage_problems.append(f"missing baseline months: {months}")

    required = _MONTHLY_BILLING_SOURCES if required_sources is None else set(required_sources)
    months_by_source = baseline.groupby("source")["month"].unique()
    missing_sources = required.difference(months_by_source.index)
    if missing_sources:
        coverage_problems.append(f"missing required sources: {', '.join(sorted(missing_sources))}")

    missing_source_months = [
        f"({source}, {month:%Y-%m})"
        for source in sorted(required - missing_sources)
        for month in expected_months.difference(months_by_source[source])
    ]
    if missing_source_months:
        coverage_problems.append(f"missing source months: {', '.join(missing_source_months)}")
    if coverage_problems:
        raise ValueError("baseline facts: " + "; ".join(coverage_problems))

    duplicates = baseline.duplicated(KEY, keep=False)
    if duplicates.any():
        raise ValueError(
            f"baseline facts: {duplicates.sum()} rows have duplicate fact keys {KEY}"
        )

    resource_ids = baseline["resource_id"]
    missing_ids = resource_ids.isna() | resource_ids.str.strip().eq("")
    if missing_ids.any():
        raise ValueError(f"baseline facts: missing resource IDs in {missing_ids.sum()} row(s)")

    master_ids = mapping().index
    invalid_ids = resource_ids.loc[~resource_ids.isin(master_ids)].drop_duplicates()
    noncanonical = invalid_ids.str.strip().isin(master_ids)
    problems = []
    if noncanonical.any():
        corrections = ", ".join(
            f"{resource_id!r} (use {resource_id.strip()!r})"
            for resource_id in invalid_ids.loc[noncanonical]
        )
        problems.append(f"noncanonical resource IDs: {corrections}")
    if (~noncanonical).any():
        problems.append(f"unknown resource IDs: {invalid_ids.loc[~noncanonical].tolist()}")
    if problems:
        raise ValueError("baseline facts: " + "; ".join(problems))

    return baseline
