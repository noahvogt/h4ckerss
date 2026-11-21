"""Sources that contradict each other, and which one we trust (issue #7).

Backs docs/answers/contradictions.md and GET /api/rules/contradictions. The numbers are
pinned by tests/test_contradictions.py.
"""

import pandas as pd

from app.pipeline.build import read_facts
from app.pipeline.common import read_csv

DEVIATION_FLAG = 0.05  # provider report vs invoices: flag months off by more than 5 %
CLOUD_SOURCES = ["azure_costs.csv", "aws_costs.csv", "hoster_invoice.csv"]
CRITICAL_TYPES = {"prod", "dr"}


def provider_report_vs_invoices() -> pd.DataFrame:
    """extra/provider_monthly_report.csv against our cloud invoices per month.

    The report gives one total ("Total cost all services") without a breakdown and
    does not show the SLA credits, so we compare with invoices before credits.
    """
    report = read_csv("extra/provider_monthly_report.csv", parse_dates=["month"])
    report = report.set_index("month")["total_cost_chf"]
    facts = read_facts()
    cloud = facts[facts["source"].isin(CLOUD_SOURCES)]
    credits = cloud[cloud["note"] == "SLA credit"].groupby("month")["cost_chf"].sum()
    invoices = cloud.groupby("month")["cost_chf"].sum() - credits.reindex(cloud["month"].unique(), fill_value=0)
    out = pd.DataFrame({"report_chf": report, "invoices_chf": invoices}).dropna()
    out["diff_chf"] = out["report_chf"] - out["invoices_chf"]
    out["diff_share"] = out["diff_chf"] / out["invoices_chf"]
    out["flagged"] = out["diff_share"].abs() > DEVIATION_FLAG
    return out.rename_axis("month")


def server_criticality() -> pd.DataFrame:
    """Servers whose `criticality` disagrees with their type (prod/dr are critical).

    The data dictionary says criticality is not always reliable; the server type is.
    """
    inv = read_csv("server_inventory.csv")
    critical = inv["type"].isin(CRITICAL_TYPES)
    wrong = critical & inv["criticality"].ne("high")
    out = inv.loc[wrong, ["server_id", "type", "criticality"]].copy()
    out["criticality"] = out["criticality"].fillna("(empty)")
    out["effective_criticality"] = "high"
    return out.reset_index(drop=True)


def effective_criticality(server_id: str) -> str:
    """Criticality to use in decisions: high for prod/dr servers, else as recorded."""
    inv = read_csv("server_inventory.csv").set_index("server_id")
    if server_id not in inv.index:
        return "unknown"
    row = inv.loc[server_id]
    if row["type"] in CRITICAL_TYPES:
        return "high"
    return row["criticality"] if isinstance(row["criticality"], str) else "unknown"


def contradictions() -> list[dict]:
    """All known contradictions: what disagrees, which source we trust and why."""
    report = provider_report_vs_invoices()
    flagged = report[report["flagged"]]
    worst = report["diff_share"].abs().idxmax()
    servers = server_criticality()
    return [
        {
            "id": "C1",
            "title": "Provider monthly report vs. invoices",
            "sources": ["extra/provider_monthly_report.csv", *CLOUD_SOURCES],
            "finding": (
                f"The report's monthly total differs from the summed invoices by "
                f"{report['diff_share'].abs().median():.0%} in a typical month; "
                f"{len(flagged)} of {len(report)} months differ by more than {DEVIATION_FLAG:.0%}, "
                f"most in {worst:%B %Y} ({report.loc[worst, 'diff_share']:+.0%}). "
                f"The report has no breakdown and does not show SLA credits."
            ),
            "trusted": "invoices",
            "why": "Invoices are itemised per resource and day, so every franc can be traced and recalculated; "
            "the report is a single unexplained total.",
            "decided_by": "Head of Finance",
            "details": [
                {"month": f"{m:%Y-%m}", "report_chf": round(r.report_chf), "invoices_chf": round(r.invoices_chf),
                 "diff_share": round(r.diff_share, 3)}
                for m, r in flagged.iterrows()
            ],
        },
        {
            "id": "C2",
            "title": "Server criticality vs. server type",
            "sources": ["server_inventory.csv"],
            "finding": f"{len(servers)} production servers have no criticality recorded "
            f"({', '.join(servers['server_id'])}).",
            "trusted": "server type (prod and dr count as critical)",
            "why": "The data dictionary marks criticality as not always reliable. No non-production server is "
            "marked high, so treating prod/dr as critical only adds protection.",
            "decided_by": "Head of IT",
            "details": servers.to_dict("records"),
        },
        {
            "id": "C3",
            "title": "ChatGPT Team seats: ticket decisions vs. usage",
            "sources": ["it_tickets.csv", "ai_subscriptions.csv"],
            "finding": "Seat requests were rejected many times because an equivalent subscription exists, "
            "yet a new seat was approved in July 2026 (T-1260) and most seats are unused.",
            "trusted": "none: a human decides (rule R15)",
            "why": "Both sources are plausible; consolidating subscriptions is a business decision.",
            "decided_by": "Management",
            "details": [],
        },
        {
            "id": "C4",
            "title": "Instructions hidden in the data vs. tickets and data",
            "sources": ["it_tickets.csv", "azure_costs.csv", "hoster_invoice.csv"],
            "finding": "Four free-text fields contain instructions aimed at AI tools: switch production off "
            "(T-1230), set database costs to 0 (T-1251), report costs 40 % lower (Azure Notes), ignore the "
            "cost column (hoster Remark). Each contradicts approved tickets or the invoice amounts.",
            "trusted": "invoices, approved tickets and job data",
            "why": "Free text is data, never instructions. None of these claims is backed by an approved change "
            "or by numbers (rules R16, R17; flagged in the facts).",
            "decided_by": None,
            "details": [],
        },
        {
            "id": "C5",
            "title": "Finance closing: ticket vs. job data (no contradiction)",
            "sources": ["it_tickets.csv", "extra/data_platform_jobs.csv"],
            "finding": "T-1029 says the platform is needed on the last 3 working days until about 04:00. "
            "All 65 month-end close runs fall on exactly those days, start at 18:00 and run about 10 h.",
            "trusted": "both (they agree)",
            "why": "Checked, not assumed: the rule is computed from the calendar and matched against the jobs.",
            "decided_by": None,
            "details": [],
        },
        {
            "id": "C6",
            "title": "Resource tags vs. master data (no contradiction)",
            "sources": ["azure_costs.csv", "aws_costs.csv", "hoster_invoice.csv", "mapping_departments_tools.csv"],
            "finding": "Departments in tags and cost centers never disagree with the master data; only tool "
            "spellings differ and many tags are empty.",
            "trusted": "master data (mapping_departments_tools.csv)",
            "why": "It is the maintained source; documented in docs/data_decisions.md.",
            "decided_by": None,
            "details": [],
        },
    ]
