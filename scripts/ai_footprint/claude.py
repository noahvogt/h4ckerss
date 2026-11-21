"""Extract usage metadata from Claude Code transcripts without retaining conversation content."""

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .records import Usage, Window, parse_timestamp

# Claude Code reports uncached input, cache reads and cache writes as disjoint counts.
INPUT_PARTS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
USAGE_FIELDS = (*INPUT_PARTS, "output_tokens")


def default_transcripts() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


@dataclass
class Response:
    model: str
    timestamp: datetime
    counts: dict[str, int | None]


def _merge(response: Response, model: str, timestamp: datetime, counts: dict[str, int | None],
           warnings: Counter) -> None:
    if counts != response.counts:
        # Streamed content blocks of one response can carry growing counters.
        warnings["transcript lines of one response disagreed; used the largest counts"] += 1
        response.counts = {
            key: max(values) if (values := [v for v in (response.counts[key], counts[key]) if v is not None])
            else None
            for key in USAGE_FIELDS
        }
    if timestamp < response.timestamp:
        response.timestamp = timestamp
    if model and model != response.model:
        if response.model:
            warnings["responses with conflicting model names exported without a model"] += 1
            response.model = ""
        else:
            response.model = model


def _read_file(path: Path, responses: dict[str, Response], warnings: Counter) -> None:
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = _object(json.loads(line))
            except ValueError:
                warnings["unreadable or truncated JSONL lines skipped"] += 1
                continue
            if row.get("type") != "assistant":
                continue
            message = _object(row.get("message"))
            model = message.get("model")
            model = model if isinstance(model, str) else ""
            if model == "<synthetic>":
                # Locally generated placeholders, not API responses.
                continue
            usage = _object(message.get("usage"))
            if not usage:
                warnings["assistant messages without usage skipped"] += 1
                continue
            identity = row.get("requestId") or message.get("id")
            if not isinstance(identity, str) or not identity:
                warnings["assistant messages without a request or message ID skipped"] += 1
                continue
            raw_timestamp = row.get("timestamp")
            try:
                timestamp = parse_timestamp(raw_timestamp) if isinstance(raw_timestamp, str) else None
            except ValueError:
                timestamp = None
            if timestamp is None:
                warnings["assistant messages without a usable timestamp skipped"] += 1
                continue
            counts = {key: _count(usage.get(key)) for key in USAGE_FIELDS}
            # Resumed and forked sessions may copy earlier responses into a new file.
            key = "claude:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
            if (previous := responses.get(key)) is not None:
                _merge(previous, model, timestamp, counts, warnings)
            else:
                responses[key] = Response(model, timestamp, counts)


def import_claude(path: Path, member: str, window: Window) -> tuple[list[Usage], Counter]:
    files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path] if path.is_file() else []
    if not files:
        raise ValueError("no Claude Code transcript JSONL files found; check --transcripts")
    warnings = Counter()
    responses: dict[str, Response] = {}
    for file in files:
        _read_file(file, responses, warnings)

    rows = []
    for evidence, response in responses.items():
        if not window.contains(response.timestamp):
            continue
        counts = response.counts
        parts = [part for key in INPUT_PARTS if (part := counts[key]) is not None]
        input_tokens = sum(parts) if len(parts) == len(INPUT_PARTS) else None
        if input_tokens is None:
            warnings["responses with incomplete input counts exported without input"] += 1
        rows.append(Usage(
            member, "Claude Code", response.model, response.timestamp,
            input_tokens=input_tokens,
            cached_input_tokens=counts["cache_read_input_tokens"],
            output_tokens=counts["output_tokens"],
            requests=1,
            measurement_method="claude_jsonl",
            evidence_reference=evidence,
        ))
    return rows, warnings
