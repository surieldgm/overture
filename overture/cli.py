"""Command-line entrypoint for Overture.

Tests may temporarily replace `_linear_client_factory` to stub Linear HTTP while
still exercising the real export command path.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from .export import parse_ticket_file
from .export_store import ExportStore
from .fixture import PipelineStageError, run_overture_fixture
from .intake import create_intake_record, load_intake_record
from .linear_client import LinearAPIError, LinearClient
from .research_llm import (
    LLMSuggestedSourceAdapter,
    cli_approver,
    codex_cli_client,
    fake_llm_client,
    write_research_result,
)


def _linear_client_factory() -> LinearClient:
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise RuntimeError("LINEAR_API_KEY is required for real Linear export")
    return LinearClient(api_key=api_key)


def _default_overture_home() -> Path:
    return Path(os.environ.get("OVERTURE_HOME", ".")).expanduser()


def _default_export_store_path() -> Path:
    return _default_overture_home() / ".overture" / "exports.sqlite"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overture")
    subparsers = parser.add_subparsers(dest="command", required=True)

    intake = subparsers.add_parser(
        "intake",
        help="Store an isolated idea as an intake record.",
    )
    intake.add_argument(
        "idea",
        nargs="+",
        help="Free-form idea text to preserve in the intake record.",
    )
    intake.add_argument(
        "--store-dir",
        type=Path,
        default=Path(".overture") / "intake",
        help="Directory where intake records are stored.",
    )

    fixture = subparsers.add_parser(
        "fixture",
        help="Run the deterministic Overture MVP end-to-end fixture.",
    )
    fixture.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".overture") / "fixtures" / "overture-mvp",
        help="Directory where fixture artifacts are written.",
    )
    fixture.add_argument(
        "--idea",
        help="Raw idea string to use instead of the built-in Overture MVP fixture idea.",
    )

    research = subparsers.add_parser(
        "research",
        help="Suggest and approve research sources for an intake record.",
    )
    research.add_argument(
        "intake_id",
        help="Intake record ID to load from <store-dir>/intake/<intake-id>.json.",
    )
    research.add_argument(
        "--store-dir",
        type=Path,
        default=Path(".overture"),
        help="Base Overture store directory containing intake/ and research/.",
    )

    export = subparsers.add_parser(
        "export",
        help="Export a validated Symphony ticket draft to Linear.",
    )
    export.add_argument(
        "ticket_path",
        type=Path,
        help="Path to a Symphony-ready ticket Markdown draft.",
    )
    export.add_argument(
        "--team-id",
        required=True,
        help="Linear team ID for the created issue.",
    )
    export.add_argument(
        "--project-id",
        help="Optional Linear project ID for the created issue.",
    )
    export.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the ticket without creating a Linear issue.",
    )
    export.add_argument(
        "--ledger-db",
        type=Path,
        default=None,
        help="SQLite export ledger path. Defaults to $OVERTURE_HOME/.overture/exports.sqlite.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "intake":
        raw_text = " ".join(args.idea)
        try:
            record, path = create_intake_record(raw_text, args.store_dir)
        except ValueError as exc:
            parser.error(str(exc))
            return 2

        print(path)
        print(record.id)
        return 0

    if args.command == "fixture":
        try:
            if args.idea:
                artifacts = run_overture_fixture(args.output_dir, idea=args.idea)
            else:
                artifacts = run_overture_fixture(args.output_dir)
        except PipelineStageError as exc:
            print(f"fixture failed at {exc.stage}: {exc.message}", file=sys.stderr)
            return 1

        for stage, path in artifacts.items():
            print(f"{stage}: {path}")
        return 0

    if args.command == "research":
        intake_path = args.store_dir / "intake" / f"{args.intake_id}.json"
        try:
            intake = load_intake_record(intake_path)
        except FileNotFoundError:
            print(f"intake record not found: {intake_path}", file=sys.stderr)
            return 1
        except (KeyError, ValueError) as exc:
            print(f"invalid intake record {intake_path}: {exc}", file=sys.stderr)
            return 1

        llm_client = (
            fake_llm_client
            if os.environ.get("OVERTURE_LLM_CLIENT") == "fake"
            else codex_cli_client
        )
        adapter = LLMSuggestedSourceAdapter(llm_client=llm_client, approver=cli_approver)
        result = adapter.research(intake)
        output_path = write_research_result(
            args.store_dir / "research" / f"{intake.id}.json",
            result,
        )
        print(output_path)
        if result.errors:
            for error in result.errors:
                print(f"{error.code}: {error.message}", file=sys.stderr)
        return 0 if result.items else 1

    if args.command == "export":
        try:
            parsed = parse_ticket_file(args.ticket_path)
        except (OSError, ValueError) as exc:
            print(f"invalid ticket {args.ticket_path}: {exc}", file=sys.stderr)
            return 1

        if args.dry_run:
            print(f"title: {parsed.title}")
            print(f"body: {_one_line_summary(parsed.description, 200)}")
            return 0

        store = ExportStore(args.ledger_db or _default_export_store_path())
        existing = store.get(args.ticket_path)
        if existing is not None:
            print(f"already exported: {existing.linear_url}")
            return 0

        try:
            issue = _linear_client_factory().create_issue(
                team_id=args.team_id,
                title=parsed.title,
                description=parsed.description,
                project_id=args.project_id,
            )
        except (RuntimeError, LinearAPIError) as exc:
            print(f"export failed: {exc}", file=sys.stderr)
            return 1

        store.insert(
            ticket_path=args.ticket_path,
            title=parsed.title,
            linear_issue_id=issue.id,
            linear_identifier=issue.identifier,
            linear_url=issue.url,
        )
        print(issue.url)
        return 0

    parser.print_help(sys.stderr)
    return 2


def _one_line_summary(text: str, limit: int) -> str:
    summary = " ".join(text.split())
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3].rstrip() + "..."
