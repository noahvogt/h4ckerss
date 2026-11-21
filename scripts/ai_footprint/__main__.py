"""Commands for team AI footprint evidence and reporting."""

import argparse
import csv
import sys
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from .claude import default_transcripts, import_claude
from .codex import import_codex
from .records import END, START, Usage, Window, read_csv, reconcile, write_csv

IMPORTERS = {
    "import-codex": ("Codex", "sessions", import_codex),
    "import-claude": ("Claude Code", "transcripts", import_claude),
}


def _period(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=date.fromisoformat, default=START, help="first Basel date, inclusive")
    parser.add_argument("--end", type=date.fromisoformat, default=END, help="last Basel date, inclusive")


def _combine(paths: Iterable[Path]) -> Iterable[Usage]:
    for path in paths:
        yield from read_csv(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract and summarize the hackathon team's AI usage locally.")
    commands = parser.add_subparsers(dest="command", required=True)
    codex = commands.add_parser("import-codex", help="export usage metadata from local Codex session logs")
    codex.add_argument("--sessions", type=Path, default=Path.home() / ".codex" / "sessions",
                       help="JSONL file or directory (default: ~/.codex/sessions)")
    codex.add_argument("--member", required=True, help="team member's name or agreed alias")
    codex.add_argument("--output", "-o", type=Path, required=True, help="destination CSV")
    _period(codex)

    claude = commands.add_parser("import-claude", help="export usage metadata from local Claude Code transcripts")
    claude.add_argument("--transcripts", type=Path, default=default_transcripts(),
                        help="JSONL file or directory (default: ~/.claude/projects)")
    claude.add_argument("--member", required=True, help="team member's name or agreed alias")
    claude.add_argument("--output", "-o", type=Path, required=True, help="destination CSV")
    _period(claude)

    template = commands.add_parser("template", help="create an empty manual usage CSV")
    template.add_argument("--output", "-o", type=Path, required=True)

    combine = commands.add_parser("combine", help="validate, filter and deduplicate member CSVs")
    combine.add_argument("files", nargs="+", type=Path)
    combine.add_argument("--output", "-o", type=Path, required=True)
    _period(combine)

    summary = commands.add_parser("summary", help="generate a Markdown pitch summary")
    summary.add_argument("files", nargs="+", type=Path)
    summary.add_argument("--grid", type=str.upper, help="explicit inference grid scenario, e.g. DE or EU")
    summary.add_argument("--output", "-o", type=Path, help="destination Markdown file (default: stdout)")
    _period(summary)

    args = parser.parse_args()
    try:
        if args.command == "template":
            if args.output.exists():
                raise ValueError("template destination already exists")
            write_csv(args.output, ())
            return 0

        window = Window(args.start, args.end)
        if args.command in IMPORTERS:
            label, source, importer = IMPORTERS[args.command]
            if not args.member.strip():
                raise ValueError("member must be nonempty")
            logs = getattr(args, source).expanduser()
            if args.output.resolve().suffix.lower() != ".csv" or args.output.resolve() == logs.resolve():
                raise ValueError(f"choose a new CSV destination separate from the {label} logs")
            rows, warnings = importer(logs, args.member.strip(), window)
            for message, count in sorted(warnings.items()):
                print(f"{label}: {count:,} {message}.", file=sys.stderr)
        else:
            if args.output is not None and args.output.resolve() in {path.resolve() for path in args.files}:
                raise ValueError("choose an output path different from the input files")
            rows = _combine(args.files)
        selected, outside, duplicates = reconcile(rows, window)
        print(f"{len(selected):,} usage rows selected. {outside:,} outside period, "
              f"{duplicates:,} duplicate rows removed.", file=sys.stderr)

        if args.command != "summary":
            write_csv(args.output, selected)
            return 0

        from .summary import render_summary

        report = render_summary(selected, window, args.grid)
        if args.output is None:
            print(report, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
        return 0
    except (OSError, ValueError, csv.Error, ImportError, OverflowError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
