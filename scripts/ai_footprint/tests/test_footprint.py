import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ai_footprint.codex import import_codex
from scripts.ai_footprint.records import COLUMNS, Window, read_csv, reconcile

ROOT = Path(__file__).resolve().parents[3]


def metadata(timestamp="2026-11-20T09:00:00Z", identity="synthetic-session"):
    return {"type": "session_meta", "payload": {"id": identity, "timestamp": timestamp}}


def counters(values):
    if values is None:
        return None
    return dict(zip(("input_tokens", "cached_input_tokens", "output_tokens"), values, strict=True))


def token(timestamp, total, last=None):
    return {
        "type": "event_msg", "timestamp": timestamp,
        "payload": {"type": "token_count", "info": {
            "total_token_usage": counters(total), "last_token_usage": counters(last),
        }},
    }


def session(path, *rows):
    path.write_text("".join((row if isinstance(row, str) else json.dumps(row)) + "\n" for row in rows))
    return path


def usage(rows):
    return [(row.input_tokens, row.cached_input_tokens, row.output_tokens) for row in rows]


def test_cumulative_increments_snapshots_and_resets(tmp_path):
    path = session(
        tmp_path / "rollout.jsonl",
        metadata(), {"type": "turn_context", "payload": {"model": "test-model"}},
        token("2026-11-20T09:00:01Z", (100, 50, 10), (100, 50, 10)),
        token("2026-11-20T09:00:02Z", (150, 70, 15), (50, 20, 5)),
        token("2026-11-20T09:00:03Z", (150, 70, 15), (50, 20, 5)),
        metadata(),  # Resume metadata repeats the same session ID.
        token("2026-11-20T09:00:04Z", None, (20, 8, 2)),
        token("2026-11-20T09:00:05Z", (200, 90, 20), (30, 12, 3)),
        token("2026-11-20T09:00:06Z", (25, 5, 2), (25, 5, 2)),
        token("2026-11-20T09:00:07Z", (50, 10, 4)),
        '{"broken":',
    )
    rows, warnings = import_codex(path, "Pat", Window())
    assert usage(rows) == [(100, 50, 10), (50, 20, 5), (20, 8, 2), (30, 12, 3), (25, 5, 2), (25, 5, 2)]
    assert all(row.requests is None and row.model == "test-model" for row in rows)
    assert warnings["repeated cumulative snapshots ignored"] == 1
    assert warnings["cumulative counter resets observed"] == 1
    assert warnings["unreadable or truncated JSONL lines skipped"] == 1


def test_resume_republishes_usage_with_a_new_timestamp(tmp_path):
    path = session(
        tmp_path / "rollout.jsonl",
        metadata(),
        token("2026-11-20T09:00:01Z", (100, 50, 10), (100, 50, 10)),
        metadata(),
        token("2026-11-20T10:00:01Z", (100, 50, 10), (100, 50, 10)),
        token("2026-11-20T10:00:02Z", (130, 75, 12), (30, 25, 2)),
    )
    rows, warnings = import_codex(path, "Pat", Window())
    assert usage(rows) == [(100, 50, 10), (30, 25, 2)]
    assert warnings["repeated cumulative snapshots ignored"] == 1


def test_boundary_uses_latest_increment_and_preserves_zeros_and_unknowns(tmp_path):
    path = session(
        tmp_path / "rollout.jsonl",
        metadata("2026-11-19T22:00:00Z"),
        token("2026-11-19T22:59:59Z", (100, 50, 10), (100, 50, 10)),
        token("2026-11-19T23:00:00Z", (250, 90, 25), (20, 5, 2)),
        token("2026-11-22T22:59:59Z", (260, 90, None), (10, 0, None)),
        token("2026-11-22T23:00:00Z", (300, 95, 35), (40, 5, 10)),
        metadata("2026-11-21T09:00:00Z", "next-session"),
        token("2026-11-21T09:00:01Z", (0, 0, 0), (0, 0, 0)),
    )
    rows, warnings = import_codex(path, "Pat", Window())
    assert usage(rows) == [(20, 5, 2), (10, 0, None), (0, 0, 0)]
    assert warnings["cumulative components could not be fully attributed to the period"] == 3


def test_clipped_cumulative_only_first_snapshot_is_not_assigned_to_the_period(tmp_path):
    path = session(
        tmp_path / "rollout.jsonl",
        metadata("2026-11-19T22:00:00Z"),
        token("2026-11-20T09:00:01Z", (1000, 900, 100)),
        token("2026-11-20T09:00:02Z", (1100, 950, 120)),
    )
    rows, _ = import_codex(path, "Pat", Window())
    assert usage(rows) == [(None, None, None), (100, 50, 20)]


def test_duplicate_files_produce_one_record_and_metadata_only(tmp_path):
    event = token("2026-11-21T09:00:01Z", (25, 5, 2), (25, 5, 2))
    path = session(
        tmp_path / "personal-rollout.jsonl",
        metadata(),
        {"type": "response_item", "payload": {"content": "never export this prompt"}},
        event, event,
    )
    shutil.copyfile(path, tmp_path / "different-name.jsonl")
    rows, warnings = import_codex(tmp_path, "Pat", Window())
    rows, outside, duplicates = reconcile(rows, Window())
    assert (len(rows), outside, duplicates) == (1, 0, 1)
    assert warnings["duplicate token events ignored"] == 2
    assert rows[0].evidence_reference.startswith("codex:")
    assert "synthetic-session" not in repr(rows[0])
    assert "personal-rollout" not in repr(rows[0])
    assert "never export" not in repr(rows[0])


def test_catch_up_and_context_only_snapshots_are_not_new_usage(tmp_path):
    context = token("2026-11-20T09:00:04Z", None, (0, 0, 0))
    context["payload"]["info"]["last_token_usage"]["total_tokens"] = 9999
    path = session(
        tmp_path / "rollout.jsonl", metadata(),
        token("2026-11-20T09:00:01Z", (100, 50, 10)),
        token("2026-11-20T09:00:02Z", None, (50, 20, 5)),
        token("2026-11-20T09:00:03Z", (150, 70, 15), (50, 20, 5)),
        context,
        token("2026-11-20T09:00:05Z", (160, 75, 16), (10, 5, 1)),
    )
    rows, warnings = import_codex(path, "Pat", Window())
    assert usage(rows) == [(100, 50, 10), (50, 20, 5), (10, 5, 1)]
    assert warnings["cumulative catch-up snapshots ignored"] == 1
    assert warnings["token events without measured counters skipped"] == 1


def test_fork_history_is_not_counted_again(tmp_path):
    session(tmp_path / "original.jsonl", metadata(), token("2026-11-20T09:01:00Z", (100, 50, 10)))
    clone = metadata("2026-11-20T09:05:00Z", "fork")
    clone["payload"]["forked_from_id"] = "synthetic-session"
    session(tmp_path / "fork.jsonl", clone, metadata(), token("2026-11-20T09:05:01Z", (100, 50, 10)))
    rows, warnings = import_codex(tmp_path, "Pat", Window())
    assert usage(rows) == [(100, 50, 10)]
    assert warnings["forked rollouts skipped because inherited usage could not be isolated"] == 1


def test_increment_before_observed_reset_is_not_counted_twice(tmp_path):
    path = session(
        tmp_path / "rollout.jsonl", metadata(),
        token("2026-11-20T09:00:01Z", (100, 50, 10)),
        token("2026-11-20T09:00:02Z", None, (10, 5, 1)),
        token("2026-11-20T09:00:03Z", (10, 5, 1), (10, 5, 1)),
        token("2026-11-20T09:00:04Z", (15, 6, 2), (5, 1, 1)),
    )
    rows, _ = import_codex(path, "Pat", Window())
    assert usage(rows) == [(100, 50, 10), (10, 5, 1), (5, 1, 1)]


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.ai_footprint", *map(str, args)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def test_cli_template_manual_combine_and_summary(tmp_path):
    manual, exported, combined, pitch = (
        tmp_path / name for name in ("manual.csv", "codex.csv", "team.csv", "pitch.md")
    )
    assert run("template", "-o", manual).returncode == 0
    assert manual.read_bytes() == (ROOT / "scripts/ai_footprint/template.csv").read_bytes()
    with manual.open("a", newline="") as stream:
        writer = csv.writer(stream)
        record = ["Alex", "Claude Code", "", "2026-11-20", "", "", "3", "0", "official_export", "evidence-A"]
        writer.writerows([record, record, ["Alex", "Cursor", "", "2026-11-23", "55", "", "", "", "screenshot", "evidence-B"]])
    source = session(
        tmp_path / "rollout.jsonl", metadata(),
        {"type": "event_msg", "payload": {"type": "user_message", "message": "private-text"}},
        token("2026-11-20T09:00:01Z", (900, 200, 100), (900, 200, 100)),
    )
    result = run("import-codex", "--member", "Pat", "--sessions", source, "-o", exported)
    assert result.returncode == 0, result.stderr
    assert "private-text" not in exported.read_text()
    result = run("combine", manual, exported, "-o", combined)
    assert result.returncode == 0 and "1 outside period, 1 duplicate rows removed" in result.stderr
    assert len(list(read_csv(combined))) == 2
    report = run("summary", combined, "-o", pitch)
    assert report.returncode == 0, report.stderr
    text = pitch.read_text()
    assert "| Output tokens | 103 | 2 / 2 |" in text
    assert "| Requests | 0 | 1 / 2 |" in text
    assert "our blended token proxy estimates" in text
    assert "22.2% of input tokens where both counts were reported (1 of 2 usage rows)" in text
    assert "same factor to cached input, uncached input and output" in text
    assert "| Electricity (kWh) | 0.00013405 | 0.00026811 | 0.00053622 |" in text
    assert "| Location-based CO₂e (kg) | unknown | unknown | unknown |" in text
    report = run("summary", combined, "--grid", "CH")
    assert report.returncode == 0, report.stderr
    assert "| Location-based CO₂e (kg) | 7.64085e-06 | 2.41299e-05 | 7.23897e-05 |" in report.stdout


@pytest.mark.parametrize("bad_count", ["12%", "-1", "1.5"])
def test_manual_token_counts_reject_percentages_and_invalid_values(tmp_path, bad_count):
    path = tmp_path / "manual.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerow(["Pat", "Copilot", "", "2026-11-20", bad_count, "", "", "", "screenshot", "ref"])
    with pytest.raises(ValueError, match="input_tokens must be a nonnegative integer or blank"):
        list(read_csv(path))


def test_conflicting_rows_fail_instead_of_inflating_the_total(tmp_path):
    path = tmp_path / "manual.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        for total in (10, 20):
            writer.writerow(["Pat", "Gemini", "", "2026-11-20", total, "", "", "", "official_export", "same-ref"])
    with pytest.raises(ValueError, match="same evidence"):
        reconcile(read_csv(path), Window())
