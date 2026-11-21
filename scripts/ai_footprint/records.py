"""Shared CSV format for team AI usage."""

import csv
import re
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

BASEL = ZoneInfo("Europe/Zurich")
START = date(2026, 11, 20)
END = date(2026, 11, 22)
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")
COUNT_FIELDS = (*TOKEN_FIELDS, "requests")
# Importers derive evidence references from source event IDs, so the reference alone identifies a row.
IMPORTED_METHODS = frozenset({"codex_jsonl", "claude_jsonl"})


@dataclass(frozen=True)
class Usage:
    member: str
    tool: str
    model: str
    timestamp: datetime
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    requests: int | None
    measurement_method: str
    evidence_reference: str


COLUMNS = tuple(field.name for field in fields(Usage))


@dataclass(frozen=True)
class Window:
    start: date = START
    end: date = END

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("start date must be on or before end date")

    @property
    def lower(self) -> datetime:
        return datetime.combine(self.start, time.min, BASEL)

    @property
    def upper(self) -> datetime:
        return datetime.combine(self.end + timedelta(days=1), time.min, BASEL)

    def contains(self, timestamp: datetime) -> bool:
        return self.lower <= timestamp < self.upper


def parse_timestamp(value: str, *, allow_date: bool = False) -> datetime:
    if allow_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.combine(date.fromisoformat(value), time.min, BASEL).astimezone(UTC)
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError("timestamps with a time require a UTC offset or Z")
    return timestamp.astimezone(UTC)


def _parse_row(raw: dict[str, str]) -> Usage:
    if any(raw.get(column) is None for column in COLUMNS) or None in raw:
        raise ValueError("expected exactly one value per column")
    values = {column: raw[column].strip() for column in COLUMNS}
    for name in ("member", "tool", "measurement_method", "evidence_reference"):
        if not values[name]:
            raise ValueError(f"{name} is required")
    counts = {}
    for field in COUNT_FIELDS:
        value = values.pop(field)
        if value and not re.fullmatch(r"[0-9]+", value):
            raise ValueError(f"{field} must be a nonnegative integer or blank")
        counts[field] = int(value) if value else None
    if counts["cached_input_tokens"] is not None and counts["input_tokens"] is not None:
        if counts["cached_input_tokens"] > counts["input_tokens"]:
            raise ValueError("cached_input_tokens must be included in input_tokens")
    return Usage(
        timestamp=parse_timestamp(values.pop("timestamp"), allow_date=True),
        **values,
        **counts,
    )


def read_csv(path: Path) -> Iterable[Usage]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames is None or sorted(reader.fieldnames) != sorted(COLUMNS):
            raise ValueError(f"{path.name}: expected the columns from template.csv")
        for raw in reader:
            if all(value == "" for value in raw.values()):
                continue
            try:
                yield _parse_row(raw)
            except ValueError as error:
                raise ValueError(f"{path.name}:{reader.line_num}: {error}") from None


def write_csv(path: Path, rows: Iterable[Usage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            data = asdict(row)
            data["timestamp"] = row.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
            writer.writerow(data)


def reconcile(rows: Iterable[Usage], window: Window) -> tuple[list[Usage], int, int]:
    """Drop duplicate evidence rows, reject conflicts, and select the period."""
    unique = {}
    outside = duplicates = 0
    for row in rows:
        if not window.contains(row.timestamp):
            outside += 1
            continue
        if row.measurement_method in IMPORTED_METHODS:
            key = (row.measurement_method, row.evidence_reference)
        else:
            key = (row.member.casefold(), row.tool.casefold(), row.model.casefold(),
                   row.timestamp, row.evidence_reference)
        previous = unique.get(key)
        if previous is not None:
            if previous != row:
                raise ValueError("conflicting usage rows refer to the same evidence")
            duplicates += 1
            continue
        unique[key] = row
    return sorted(unique.values(), key=lambda row: (
        row.timestamp, row.member, row.tool, row.model, row.evidence_reference
    )), outside, duplicates
