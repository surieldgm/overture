"""Command-line entrypoint for Overture.

The `_linear_client_factory` seam lets tests replace LinearClient construction
without monkey-patching urllib internals.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Sequence

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
from .ticket_writer import validate_linear_issue_payload


_linear_client_factory: Callable[[str], LinearClient] = LinearClient


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
        help="Create a Linear issue from a validated ticket Markdown file.",
    )
    export.add_argument(
        "ticket_path",
        type=Path,
        help="Path to a Symphony-ready ticket Markdown file.",
    )
    export.add_argument(
        "--team-id",
        default=os.environ.get("LINEAR_TEAM_ID"),
        help="Linear team ID. Defaults to LINEAR_TEAM_ID.",
    )
    export.add_argument(
        "--project-id",
        default=os.environ.get("LINEAR_PROJECT_ID"),
        help="Linear project ID. Defaults to LINEAR_PROJECT_ID.",
    )
    export.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the issue payload without calling Linear.",
    )

    return parser


def parse_ticket_file(path: Path) -> tuple[str, str, str]:
    """Parse a ticket Markdown file into title, full description, and body."""

    full_description = path.read_text(encoding="utf-8")
    lines = full_description.splitlines(keepends=True)
    first_content_index = next(
        (index for index, line in enumerate(lines) if line.strip()),
        None,
    )
    if first_content_index is None:
        raise ValueError("ticket parser error: first non-empty line must be an H1 title")

    title_line = lines[first_content_index]
    if not title_line.startswith("# ") or title_line.startswith("## "):
        raise ValueError("ticket parser error: first non-empty line must be an H1 title")

    title = title_line[2:].strip()
    body_lines = lines[first_content_index + 1 :]
    if body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]
    body_without_h1 = "".join(body_lines)
    return title, full_description, body_without_h1


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
        if not args.team_id:
            print("missing required --team-id or LINEAR_TEAM_ID", file=sys.stderr)
            return 2

        ticket_path = args.ticket_path.resolve()
        if not ticket_path.exists():
            print(f"ticket path not found: {ticket_path}", file=sys.stderr)
            return 2

        try:
            title, full_description, body_without_h1 = parse_ticket_file(ticket_path)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        errors = validate_linear_issue_payload(title, full_description)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1

        if args.dry_run:
            print(f"would create: title={title}")
            print(body_without_h1, end="" if body_without_h1.endswith("\n") else "\n")
            return 0

        api_key = os.environ.get("LINEAR_API_KEY")
        if not api_key:
            print("missing required environment variable LINEAR_API_KEY", file=sys.stderr)
            return 2

        try:
            issue = _linear_client_factory(api_key).create_issue(
                team_id=args.team_id,
                title=title,
                description=body_without_h1,
                project_id=args.project_id,
            )
        except LinearAPIError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        print(issue.url)
        return 0

    parser.print_help(sys.stderr)
    return 2
