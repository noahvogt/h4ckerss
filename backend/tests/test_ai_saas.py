import pandas as pd
import pytest

from app.pipeline import common
from app.pipeline.ai_saas import (
    calculate_unused_ai_seats,
    load_ai_saas,
    load_ai_subscription_details,
    load_ai_usage_details,
    load_saas_subscription_details,
)
from app.pipeline.schema import validate


def _write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)


def _data_dir(tmp_path, *, missing_tokens_out=False, missing_usd_rate=False):
    _write_csv(
        tmp_path / "ai_usage.csv",
        [
            {
                "date": "2026-08-02",
                "resource_id": "ai-helper",
                "tool": "AI Helper",
                "department": "Consulting",
                "task_type": "Draft texts",
                "model_class": "large",
                "provider": "OpenAI",
                "model": "GPT-X",
                "requests": 5,
                "tokens_in": 100,
                "tokens_in_cache": 20,
                "tokens_out": "" if missing_tokens_out else 40,
                "cost_chf": 2.0,
                "project_id": "",
            }
        ],
    )
    _write_csv(
        tmp_path / "ai_subscriptions.csv",
        [
            {
                "month": "2026-08-01",
                "product": "ChatGPT Team",
                "provider": "OpenAI",
                "cost_center": "4000",
                "licences_purchased": 4,
                "licences_active_30d": 1,
                "messages_30d": 12,
                "price_per_seat": 25,
                "currency": "USD",
                "amount": 100,
                "contract_status": "Final",
                "contract_end": "2027-01-31",
                "notice_period_days": 30,
                "billing": "monthly",
            },
            {
                "month": "2026-08-01",
                "product": "ChatGPT Team",
                "provider": "OpenAI",
                "cost_center": "4100",
                "licences_purchased": 10,
                "licences_active_30d": 2,
                "messages_30d": 10,
                "price_per_seat": 25,
                "currency": "USD",
                "amount": 250,
                "contract_status": "Draft",
                "contract_end": "2027-01-31",
                "notice_period_days": 30,
                "billing": "monthly",
            },
        ],
    )
    _write_csv(
        tmp_path / "saas_contracts.csv",
        [
            {
                "month": "2026-08-01",
                "contract": "CRM",
                "provider": "Vendor",
                "cost_center": "4100",
                "licences_purchased": 3,
                "licences_active_30d": 2,
                "price_per_licence": 16.67,
                "currency": "EUR",
                "amount": 50,
                "contract_status": "Final",
                "contract_end": "2027-01-31",
                "notice_period_days": 30,
                "billing": "annual",
            },
            {
                "month": "2026-08-01",
                "contract": "Draft CRM",
                "provider": "Vendor",
                "cost_center": "4200",
                "licences_purchased": 2,
                "licences_active_30d": 1,
                "price_per_licence": 20,
                "currency": "CHF",
                "amount": 40,
                "contract_status": "Draft",
                "contract_end": "2027-01-31",
                "notice_period_days": 30,
                "billing": "monthly",
            },
            {
                "month": "2026-08-01",
                "contract": "Time tracking",
                "provider": "Vendor",
                "cost_center": "4200",
                "licences_purchased": 2,
                "licences_active_30d": 2,
                "price_per_licence": 10,
                "currency": "CHF",
                "amount": 20,
                "contract_status": "Final",
                "contract_end": "2027-01-31",
                "notice_period_days": 30,
                "billing": "annual",
            },
        ],
    )
    _write_csv(
        tmp_path / "exchange_rates.csv",
        [
            {
                "month": "2026-08-01",
                "eur_chf": 0.9,
                "usd_chf": "" if missing_usd_rate else 0.8,
            }
        ],
    )
    return tmp_path


def test_loads_valid_monthly_facts_and_keeps_ai_cost_in_chf(tmp_path):
    facts = load_ai_saas(_data_dir(tmp_path))

    assert list(validate(facts).columns) == [
        "month",
        "category",
        "source",
        "resource_id",
        "tool",
        "department",
        "cost_center",
        "location",
        "usage_kind",
        "usage_qty",
        "cost_chf",
        "note",
    ]
    ai_usage = facts.loc[facts["source"].eq("ai_usage.csv")].iloc[0]
    assert ai_usage["usage_kind"] == "tokens"
    assert ai_usage["usage_qty"] == 140
    assert ai_usage["cost_chf"] == 2.0
    assert ai_usage["location"] == "EU"

    ai_subscription = facts.loc[facts["source"].eq("ai_subscriptions.csv")].iloc[0]
    assert ai_subscription["resource_id"] == "sub-chatgpt"
    assert ai_subscription["cost_chf"] == 80
    assert ai_subscription["usage_kind"] == "messages"
    assert ai_subscription["usage_qty"] == 12
    assert ai_subscription["department"] == "Consulting"
    saas_facts = facts.loc[facts["source"].eq("saas_contracts.csv")]
    assert saas_facts["cost_chf"].tolist() == [45, 20]
    assert saas_facts["usage_kind"].tolist() == ["seat_month", "seat_month"]
    assert saas_facts["usage_qty"].tolist() == [3, 2]
    assert facts["location"].eq("EU").all()
    assert not facts["note"].str.contains("Draft", na=False).any()


def test_subscription_facts_use_canonical_ids_and_preserve_allocations(tmp_path):
    path = _data_dir(tmp_path)
    ai_template = pd.read_csv(path / "ai_subscriptions.csv").iloc[0].to_dict()
    ai_rows = [
        ai_template,
        ai_template | {"messages_30d": 8, "amount": 50},
        ai_template
        | {
            "cost_center": "4100",
            "messages_30d": 3,
            "amount": 25,
        },
        ai_template
        | {
            "product": "Claude Team",
            "provider": "Anthropic",
            "messages_30d": 7,
            "amount": 40,
        },
        ai_template
        | {
            "product": "Microsoft Copilot",
            "provider": "Microsoft",
            "messages_30d": 9,
            "amount": 60,
        },
    ]
    _write_csv(path / "ai_subscriptions.csv", ai_rows)

    saas_template = pd.read_csv(path / "saas_contracts.csv").iloc[0].to_dict()
    saas_rows = [
        saas_template
        | {
            "contract": "Microsoft 365",
            "provider": "Microsoft",
            "licences_purchased": 6,
            "amount": 90,
        },
        saas_template
        | {"contract": "CRM platform", "licences_purchased": 3, "amount": 50},
        saas_template
        | {"contract": "Time tracking", "licences_purchased": 2, "amount": 20},
        saas_template
        | {
            "contract": "Password manager",
            "cost_center": "4200",
            "licences_purchased": 4,
            "amount": 30,
        },
    ]
    _write_csv(path / "saas_contracts.csv", saas_rows)

    facts = load_ai_saas(path)
    subscriptions = facts.loc[
        facts["source"].isin(["ai_subscriptions.csv", "saas_contracts.csv"])
    ]
    assert set(subscriptions["resource_id"]).issubset(set(common.mapping().index))
    assert set(subscriptions["resource_id"]) == {
        "sub-chatgpt",
        "sub-claude",
        "sub-copilot",
        "saas-m365",
        "saas-other",
    }

    chatgpt = subscriptions.loc[subscriptions["resource_id"].eq("sub-chatgpt")]
    assert set(zip(chatgpt["cost_center"], chatgpt["department"], strict=True)) == {
        ("4000", "Consulting"),
        ("4100", "Sales"),
    }
    consulting_chatgpt = chatgpt.loc[chatgpt["cost_center"].eq("4000")].iloc[0]
    assert consulting_chatgpt["usage_qty"] == 20
    assert consulting_chatgpt["cost_chf"] == 120

    other_sales = subscriptions.loc[
        subscriptions["resource_id"].eq("saas-other")
        & subscriptions["cost_center"].eq("4100")
    ].iloc[0]
    assert other_sales["usage_qty"] == 5
    assert other_sales["cost_chf"] == 63
    assert other_sales["department"] == "Sales"

    ai_details = load_ai_subscription_details(path)
    saas_details = load_saas_subscription_details(path)
    assert set(ai_details["product"]) == {
        "ChatGPT Team",
        "Claude Team",
        "Microsoft Copilot",
    }
    assert set(saas_details["product"]) == {
        "Microsoft 365",
        "CRM platform",
        "Time tracking",
        "Password manager",
    }
    assert set(saas_details["provider"]) == {"Microsoft", "Vendor"}


def test_preserves_monthly_ai_details_without_counting_cached_tokens_twice(tmp_path):
    details = load_ai_usage_details(_data_dir(tmp_path))
    row = details.iloc[0]

    assert row["tokens_in"] == 100
    assert row["tokens_in_cache"] == 20
    assert row["tokens_out"] == 40
    assert row["model"] == "GPT-X"
    assert row["provider"] == "OpenAI"
    assert row["department"] == "Consulting"


def test_flags_incomplete_token_totals_instead_of_filling_with_zero(tmp_path):
    path = _data_dir(tmp_path, missing_tokens_out=True)
    facts = load_ai_saas(path)
    detail = load_ai_usage_details(path).iloc[0]
    ai_usage = facts.loc[facts["source"].eq("ai_usage.csv")].iloc[0]

    assert ai_usage["usage_qty"] == 100
    assert (
        "incomplete token usage: 0 missing input values, 1 missing output values; "
        "known tokens only"
    ) in ai_usage["note"]
    assert pd.isna(detail["tokens_out"])
    assert detail["missing_tokens_out"] == 1


def test_removes_only_exact_duplicate_ai_usage_rows(tmp_path):
    path = _data_dir(tmp_path)
    original = pd.read_csv(path / "ai_usage.csv").iloc[0].to_dict()
    distinct = original | {"requests": 6, "tokens_in": 70, "tokens_out": 30}
    _write_csv(path / "ai_usage.csv", [original, original.copy(), distinct])

    facts = load_ai_saas(path)
    details = load_ai_usage_details(path)
    ai_usage = facts.loc[facts["source"].eq("ai_usage.csv")].iloc[0]

    assert ai_usage["usage_qty"] == 240
    assert ai_usage["cost_chf"] == 4.0
    assert details["rows"].sum() == 2
    assert details.iloc[0]["tokens_in"] == 170
    assert details.iloc[0]["tokens_out"] == 70


def test_sums_known_partial_input_and_output_tokens(tmp_path):
    path = _data_dir(tmp_path)
    rows = pd.read_csv(path / "ai_usage.csv").iloc[0].to_dict()
    second = rows | {"tokens_in": None, "tokens_in_cache": None, "tokens_out": 40}
    first = rows | {"tokens_out": None}
    _write_csv(path / "ai_usage.csv", [first, second])

    facts = load_ai_saas(path)
    details = load_ai_usage_details(path).iloc[0]
    ai_usage = facts.loc[facts["source"].eq("ai_usage.csv")].iloc[0]

    assert ai_usage["usage_qty"] == 140
    assert (
        "incomplete token usage: 1 missing input values, 1 missing output values; "
        "known tokens only"
    ) in ai_usage["note"]
    assert details["tokens_in"] == 100
    assert details["tokens_out"] == 40
    assert details["tokens_in_cache"] == 20
    assert details["missing_tokens_in"] == 1
    assert details["missing_tokens_in_cache"] == 1
    assert details["missing_tokens_out"] == 1


def test_keeps_usage_nan_when_both_token_columns_are_missing(tmp_path):
    path = _data_dir(tmp_path, missing_tokens_out=True)
    usage = pd.read_csv(path / "ai_usage.csv")
    usage["tokens_in"] = None
    usage["tokens_in_cache"] = None
    _write_csv(path / "ai_usage.csv", usage.to_dict(orient="records"))

    facts = load_ai_saas(path)
    details = load_ai_usage_details(path).iloc[0]
    ai_usage = facts.loc[facts["source"].eq("ai_usage.csv")].iloc[0]

    assert pd.isna(ai_usage["usage_qty"])
    assert "all input and output token values missing" in ai_usage["note"]
    assert pd.isna(details["tokens_in"])
    assert pd.isna(details["tokens_out"])
    assert details["missing_tokens_in"] == 1
    assert details["missing_tokens_out"] == 1


def test_cached_tokens_are_not_added_to_usage_qty(tmp_path):
    path = _data_dir(tmp_path)
    facts = load_ai_saas(path)
    detail = load_ai_usage_details(path).iloc[0]
    ai_usage = facts.loc[facts["source"].eq("ai_usage.csv")].iloc[0]

    assert detail["tokens_in_cache"] == 20
    assert ai_usage["usage_qty"] == detail["tokens_in"] + detail["tokens_out"]


def test_reads_cost_centers_as_strings_and_notes_missing_centers(tmp_path):
    path = _data_dir(tmp_path)
    subscriptions = pd.read_csv(path / "ai_subscriptions.csv")
    missing = subscriptions.iloc[0].copy()
    missing["product"] = "Unallocated product"
    missing["cost_center"] = None
    subscriptions = pd.concat(
        [subscriptions, pd.DataFrame([missing])], ignore_index=True
    )
    subscriptions.to_csv(path / "ai_subscriptions.csv", index=False)

    details = load_ai_subscription_details(path)
    valid = details.loc[details["product"].eq("ChatGPT Team")].iloc[0]
    unallocated = details.loc[
        details["product"].eq("Unallocated product")
    ].iloc[0]

    assert valid["cost_center"] == "4000"
    assert valid["department"] == "Consulting"
    assert pd.isna(unallocated["cost_center"])
    assert unallocated["department"] == "Unallocated"
    assert "unmapped cost center (missing)" in unallocated["note"]


def test_ai_subscription_messages_sum_known_values_and_flag_partial_usage(tmp_path):
    path = _data_dir(tmp_path)
    subscriptions = pd.read_csv(path / "ai_subscriptions.csv")
    extra = subscriptions.iloc[0].copy()
    extra["messages_30d"] = 5
    extra["amount"] = 0
    subscriptions.loc[0, "messages_30d"] = pd.NA
    subscriptions = pd.concat(
        [subscriptions, pd.DataFrame([extra])], ignore_index=True
    )
    subscriptions.to_csv(path / "ai_subscriptions.csv", index=False)

    facts = load_ai_saas(path)
    ai_fact = facts.loc[
        facts["source"].eq("ai_subscriptions.csv")
        & facts["resource_id"].eq("sub-chatgpt")
    ].iloc[0]

    assert ai_fact["usage_kind"] == "messages"
    assert ai_fact["usage_qty"] == 5
    assert ai_fact["cost_chf"] == 80
    assert (
        "incomplete message usage: 1 missing message values; known messages only"
        in ai_fact["note"]
    )


def test_all_missing_ai_subscription_messages_keep_nan_and_are_flagged(tmp_path):
    path = _data_dir(tmp_path)
    subscriptions = pd.read_csv(path / "ai_subscriptions.csv")
    subscriptions.loc[0, "messages_30d"] = pd.NA
    subscriptions.to_csv(path / "ai_subscriptions.csv", index=False)

    facts = load_ai_saas(path)
    ai_fact = facts.loc[
        facts["source"].eq("ai_subscriptions.csv")
        & facts["resource_id"].eq("sub-chatgpt")
    ].iloc[0]

    assert ai_fact["usage_kind"] == "messages"
    assert pd.isna(ai_fact["usage_qty"])
    assert ai_fact["cost_chf"] == 80
    assert "all message values missing; usage unavailable" in ai_fact["note"]


def test_preserves_seat_details_but_excludes_drafts_from_billing_and_unused_seats(tmp_path):
    path = _data_dir(tmp_path)
    ai_details = load_ai_subscription_details(path)
    saas_details = load_saas_subscription_details(path)
    unused = calculate_unused_ai_seats(path)

    draft = ai_details.loc[ai_details["contract_status"].eq("Draft")].iloc[0]
    assert draft["licences_purchased"] == 10
    assert draft["licences_active_30d"] == 2
    assert len(saas_details.loc[saas_details["contract_status"].eq("Draft")]) == 1

    ai_team = unused.loc[unused["product"].eq("ChatGPT Team")].iloc[0]
    assert ai_team["licences_purchased"] == 4
    assert ai_team["licences_active_30d"] == 1
    assert ai_team["licences_unused"] == 3
    assert ai_team["cost_chf"] == 80
    assert ai_team["unused_cost_chf"] == 60


def test_flags_missing_monthly_exchange_rate_without_zero_cost(tmp_path):
    with pytest.raises(ValueError, match="no exchange rate"):
        load_ai_saas(_data_dir(tmp_path, missing_usd_rate=True))


def test_rejects_unsupported_currency(tmp_path):
    path = _data_dir(tmp_path)
    subscriptions = pd.read_csv(path / "ai_subscriptions.csv")
    subscriptions.loc[0, "currency"] = "GBP"
    subscriptions.to_csv(path / "ai_subscriptions.csv", index=False)

    with pytest.raises(ValueError, match="unknown or missing currency"):
        load_ai_saas(path)


def test_rejects_invalid_month(tmp_path):
    path = _data_dir(tmp_path)
    subscriptions = pd.read_csv(path / "ai_subscriptions.csv")
    subscriptions.loc[0, "month"] = "not-a-date"
    subscriptions.to_csv(path / "ai_subscriptions.csv", index=False)

    with pytest.raises(ValueError):
        load_ai_saas(path)
