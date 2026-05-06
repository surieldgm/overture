"""Command-line entrypoint for Overture."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from .fixture import PipelineStageError, run_overture_fixture
from .intake import create_intake_record, load_intake_record
from .research_llm import (
    LLMSuggestedSourceAdapter,
    cli_approver,
    codex_cli_client,
    fake_llm_client,
    write_research_result,
)


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

    parser.print_help(sys.stderr)
    return 2
