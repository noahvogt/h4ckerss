"""Extract usage metadata from Codex rollouts without retaining conversation content."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .records import TOKEN_FIELDS, Usage, Window, parse_timestamp


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _counts(value: object) -> dict[str, int]:
    payload = _object(value)
    # Context estimates can populate only total_tokens and leave real usage at zero.
    if (payload.get("input_tokens") == payload.get("output_tokens") == 0
            and (_count(payload.get("total_tokens")) or 0) > 0):
        return {}
    return {key: count for key in TOKEN_FIELDS if (count := _count(payload.get(key))) is not None}


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_timestamp(value)
    except ValueError:
        return None


@dataclass
class Checkpoint:
    total: int
    accounted: int
    timestamp: datetime


@dataclass
class Session:
    identity: str
    started: datetime | None
    model: str = ""
    checkpoint_model: str = ""
    checkpoints: dict[str, Checkpoint] = field(default_factory=dict)
    unanchored: Counter = field(default_factory=Counter)
    latest_event: datetime | None = None

    def account(
        self, total: dict[str, int], last: dict[str, int], timestamp: datetime,
        window: Window, warnings: Counter,
    ) -> dict[str, int | None] | None:
        if total and all(
            key in self.checkpoints and current == self.checkpoints[key].total
            for key, current in total.items()
        ):
            warnings["repeated cumulative snapshots ignored"] += 1
            return None

        reset = any(
            key in self.checkpoints and current < self.checkpoints[key].total
            for key, current in total.items()
        )
        origin = self.latest_event if reset else self.started
        if reset:
            warnings["cumulative counter resets observed"] += 1
            # An increment-only event may already belong to the newly visible epoch.
            for key, current in total.items():
                previous = self.checkpoints.get(key)
                if previous is not None:
                    self.unanchored[key] = min(current, previous.accounted - previous.total)
                else:
                    self.unanchored[key] = min(current, self.unanchored[key])
            self.checkpoints.clear()

        usage = {}
        catching_up = False
        for key in TOKEN_FIELDS:
            current, increment = total.get(key), last.get(key)
            previous = self.checkpoints.get(key)
            if current is None:
                usage[key] = increment
                if increment is not None:
                    if previous is not None:
                        previous.accounted += increment
                    else:
                        self.unanchored[key] += increment
                continue

            accounted = previous.accounted if previous is not None else self.unanchored[key]
            catching_up |= accounted > (previous.total if previous is not None else 0)
            delta = current - accounted
            boundary = previous.timestamp if previous is not None else origin
            if delta < 0:
                warnings["cumulative counters lagged reported increments"] += 1
                usage[key] = None
            elif boundary is None or boundary < window.lower or (
                previous is None and increment is not None and increment != delta
            ):
                # Only the most recent increment is attributable at a clipped or resumed edge.
                usage[key] = min(increment, delta) if increment is not None else None
                if window.contains(timestamp) and usage[key] != delta:
                    warnings["cumulative components could not be fully attributed to the period"] += 1
            else:
                usage[key] = delta
            self.checkpoints[key] = Checkpoint(current, max(current, accounted), timestamp)
            self.unanchored.pop(key, None)

        if not total and last and window.contains(timestamp):
            warnings["events used latest usage without a cumulative checkpoint"] += 1
        self.latest_event = timestamp
        if catching_up and all(value == 0 for value in usage.values()):
            warnings["cumulative catch-up snapshots ignored"] += 1
            return None
        return usage


def _read_file(path: Path, member: str, window: Window, warnings: Counter) -> Iterator[Usage]:
    session = Session(path.name, None)
    seen = set()
    saw_session_header = False
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = _object(json.loads(line))
            except ValueError:
                warnings["unreadable or truncated JSONL lines skipped"] += 1
                continue
            payload = _object(row.get("payload"))
            kind = row.get("type")
            if kind == "session_meta":
                if not saw_session_header and payload.get("forked_from_id"):
                    # Some Codex versions re-log parent history under new timestamps.
                    warnings["forked rollouts skipped because inherited usage could not be isolated"] += 1
                    return
                saw_session_header = True
                identity = payload.get("id") or payload.get("session_id")
                if isinstance(identity, str) and identity != session.identity:
                    session = Session(identity, _timestamp(payload.get("timestamp")))
                continue
            if kind == "turn_context":
                model = payload.get("model")
                session.model = model if isinstance(model, str) else ""
                continue
            if kind != "event_msg" or payload.get("type") != "token_count":
                continue

            timestamp = _timestamp(row.get("timestamp"))
            if timestamp is None:
                warnings["token events without a usable timestamp skipped"] += 1
                continue
            info = _object(payload.get("info"))
            total = _counts(info.get("total_token_usage"))
            last = _counts(info.get("last_token_usage"))
            if not (total or last):
                if window.contains(timestamp):
                    warnings["token events without measured counters skipped"] += 1
                continue

            event = json.dumps([session.identity, timestamp.isoformat(), total, last], sort_keys=True)
            evidence = "codex:" + hashlib.sha256(event.encode()).hexdigest()[:24]
            if evidence in seen:
                warnings["duplicate token events ignored"] += 1
                continue
            if session.latest_event is not None and timestamp < session.latest_event:
                warnings["out-of-order token events skipped"] += 1
                continue
            seen.add(evidence)
            usage = session.account(total, last, timestamp, window, warnings)
            if usage is None:
                continue
            model = session.model
            if session.checkpoint_model and session.checkpoint_model != model and any(
                value is not None and value != last.get(key) for key, value in usage.items()
            ):
                # A cumulative delta spanning models has no reliable per-model split.
                model = ""
            if total:
                session.checkpoint_model = session.model
            if not window.contains(timestamp):
                continue
            if usage["input_tokens"] is not None and usage["cached_input_tokens"] is not None:
                if usage["cached_input_tokens"] > usage["input_tokens"]:
                    usage["cached_input_tokens"] = None
                    warnings["inconsistent cached-input counts omitted"] += 1
            yield Usage(member, "Codex CLI", model, timestamp, **usage, requests=None,
                        measurement_method="codex_jsonl", evidence_reference=evidence)


def import_codex(path: Path, member: str, window: Window) -> tuple[list[Usage], Counter]:
    files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path] if path.is_file() else []
    if not files:
        raise ValueError("no Codex session JSONL files found; check --sessions")
    warnings = Counter()
    rows = [row for file in files for row in _read_file(file, member, window, warnings)]
    return rows, warnings
