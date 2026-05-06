"""Command-line entrypoint for Overture.

Tests may temporarily replace `_linear_client_factory` to stub Linear HTTP while
still exercising the real export command path.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from .export import parse_ticket_file
from .export_store import ExportLedger, compute_hash
from .fixture import PipelineStageError, run_overture_fixture
from .intake import create_intake_record, load_intake_record
from .linear_client import LinearAPIError, LinearClient
from .metrics_store import DEFAULT_METRICS_DB_PATH, MetricsStore
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
        help="Create a Linear issue from a generated ticket Markdown file.",
    )
    export.add_argument(
        "ticket_path",
        type=Path,
        help="Path to the Markdown ticket draft to export.",
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
    export.add_argument(
        "--force-recreate",
        action="store_true",
        help="Create a new Linear issue even when this ticket path was exported before.",
    )
    export.add_argument(
        "--ledger-db",
        type=Path,
        default=None,
        help="SQLite export ledger path. Defaults to $OVERTURE_HOME/.overture/exports.sqlite.",
    )

    metrics = subparsers.add_parser(
        "metrics",
        help="Summarize recorded fixture stage metrics.",
    )
    metrics.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_METRICS_DB_PATH,
        help="SQLite metrics database path. Defaults to .overture/metrics.sqlite.",
    )
    metrics.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format. Defaults to table.",
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
        return _export_ticket(args)

    if args.command == "metrics":
        return _metrics_summary(args)

    parser.print_help(sys.stderr)
    return 2


def _metrics_summary(args: argparse.Namespace) -> int:
    store = MetricsStore(args.db_path)
    payload = _metrics_summary_payload(store, args.db_path)

    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"metrics db: {payload['db_path']}")
    print(f"total runs: {payload['total_runs']}")
    print("stage          count  median_ms  p95_ms  success_rate")
    print("-----------------------------------------------------")
    for stage_name in sorted(payload["stages"]):
        stats = payload["stages"][stage_name]
        print(
            f"{stage_name:<14} "
            f"{stats['count']:>5} "
            f"{_format_metric_number(stats['median_ms']):>10} "
            f"{_format_metric_number(stats['p95_ms']):>7} "
            f"{stats['success_rate']:>12.0%}"
        )
    return 0


def _metrics_summary_payload(store: MetricsStore, db_path: Path) -> dict[str, object]:
    rows = list(store.iter_stages())
    summary = store.summary()
    return {
        "db_path": str(db_path),
        "total_runs": len({row.run_id for row in rows}),
        "total_stage_rows": len(rows),
        "stages": summary,
    }


def _format_metric_number(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


def _export_ticket(args: argparse.Namespace) -> int:
    ticket_path = args.ticket_path.expanduser().resolve(strict=False)
    if not ticket_path.exists():
        print(f"ticket file not found: {ticket_path}", file=sys.stderr)
        return 2

    try:
        ticket_text = ticket_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"could not read ticket file {ticket_path}: {exc}", file=sys.stderr)
        return 2

    ticket_hash = compute_hash(ticket_text)
    ticket_path_key = str(ticket_path)
    ledger = ExportLedger(args.ledger_db or _default_export_store_path())
    record = None if args.dry_run else ledger.find(ticket_path_key)
    if record is not None and not args.force_recreate:
        if record.ticket_hash == ticket_hash:
            print(f"already exported: {record.linear_url}")
            return 0
        print(f"ticket changed since last export: {record.linear_url}", file=sys.stderr)
        return 3

    try:
        parsed = parse_ticket_file(ticket_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"would create: title={parsed.title}")
        print(parsed.description, end="" if parsed.description.endswith("\n") else "\n")
        return 0

    if not args.team_id:
        print("missing required Linear team id: pass --team-id or set LINEAR_TEAM_ID", file=sys.stderr)
        return 2

    try:
        client = _build_linear_client()
        issue = client.create_issue(
            team_id=args.team_id,
            title=parsed.title,
            description=parsed.description,
            project_id=args.project_id,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except LinearAPIError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    ledger.record(ticket_path_key, ticket_hash, issue.id, issue.url)
    print(issue.url)
    return 0


def _build_linear_client():
    signature = inspect.signature(_linear_client_factory)
    required_positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if required_positional:
        api_key = os.environ.get("LINEAR_API_KEY")
        if not api_key:
            raise RuntimeError("missing required environment variable: LINEAR_API_KEY")
        return _linear_client_factory(api_key)
    return _linear_client_factory()
