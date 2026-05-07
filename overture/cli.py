"""Command-line entrypoint for Overture.

Tests may temporarily replace `_linear_client_factory` to stub Linear HTTP while
still exercising the real export command path.

Metrics table output assumes the canonical fixture stage names fit in a
12-character stage column to keep line lengths stable in narrow terminals.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from .export import parse_ticket_file
from .export_store import ExportLedger, compute_hash
from .fixture import PIPELINE_STAGES, PipelineStageError, run_overture_fixture
from .friction_log import FRICTION_CATEGORIES, FrictionLog
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
    fixture.add_argument(
        "--metrics-db-path",
        type=Path,
        default=None,
        help="Persist fixture stage timings to this SQLite metrics DB.",
    )
    fixture.add_argument(
        "--quiet-progress",
        action="store_true",
        help="Suppress live fixture stage progress output on stderr.",
    )

    run = subparsers.add_parser(
        "run",
        help="Run intake through ticket draft, with optional Linear export.",
    )
    run.add_argument(
        "idea",
        nargs="+",
        help="Free-form idea text to run through the Overture pipeline.",
    )
    run.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".overture") / "runs" / "latest",
        help="Directory where run artifacts are written.",
    )
    run.add_argument(
        "--stop-at-stage",
        choices=_stage_choices(),
        default=None,
        help="Stop after the named stage and print that stage's artifact path.",
    )
    run.add_argument(
        "--metrics-db-path",
        type=Path,
        default=None,
        help="Persist run stage timings to this SQLite metrics DB.",
    )
    run.add_argument(
        "--quiet-progress",
        action="store_true",
        help="Suppress live run stage progress output on stderr.",
    )
    run.add_argument(
        "--export",
        action="store_true",
        dest="export_to_linear",
        help="Export the generated ticket draft to Linear at the end of the run.",
    )
    run.add_argument(
        "--team-id",
        default=os.environ.get("LINEAR_TEAM_ID"),
        help="Linear team ID for --export. Defaults to LINEAR_TEAM_ID.",
    )
    run.add_argument(
        "--project-id",
        default=os.environ.get("LINEAR_PROJECT_ID"),
        help="Linear project ID for --export. Defaults to LINEAR_PROJECT_ID.",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="With --export, validate and print the Linear payload without calling Linear.",
    )
    run.add_argument(
        "--force-recreate",
        action="store_true",
        help="With --export, create a new Linear issue even when this ticket path was exported before.",
    )
    run.add_argument(
        "--ledger-db",
        type=Path,
        default=None,
        help="SQLite export ledger path for --export. Defaults to $OVERTURE_HOME/.overture/exports.sqlite.",
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
        help="Summarize recorded fixture pipeline stage timings.",
    )
    metrics.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_METRICS_DB_PATH,
        help="SQLite metrics DB path. Defaults to .overture/metrics.sqlite.",
    )
    metrics.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format. Defaults to table.",
    )
    metrics.add_argument(
        "--last",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Restrict summary to the last N distinct runs by started_at.",
    )

    friction = subparsers.add_parser(
        "friction",
        help="Append or query dogfooding friction notes.",
    )
    friction_subparsers = friction.add_subparsers(dest="friction_command", required=True)

    friction_append = friction_subparsers.add_parser(
        "append",
        help="Append one friction note for a session and run.",
    )
    friction_append.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_METRICS_DB_PATH,
        help="SQLite metrics DB path. Defaults to .overture/metrics.sqlite.",
    )
    friction_append.add_argument(
        "--session-id",
        required=True,
        help="Dogfooding session identifier, for example day-1.",
    )
    friction_append.add_argument(
        "--run-id",
        required=True,
        help='Run identifier to reference. Use "latest" for the most recent metrics run.',
    )
    friction_append.add_argument(
        "--category",
        required=True,
        choices=FRICTION_CATEGORIES,
        help="Operator-selected friction category.",
    )
    friction_append.add_argument(
        "--note",
        required=True,
        help="Free-text friction note.",
    )

    friction_list = friction_subparsers.add_parser(
        "list",
        help="List friction notes, optionally filtered by session and run.",
    )
    friction_list.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_METRICS_DB_PATH,
        help="SQLite metrics DB path. Defaults to .overture/metrics.sqlite.",
    )
    friction_list.add_argument(
        "--session-id",
        default=None,
        help="Only include entries for this dogfooding session.",
    )
    friction_list.add_argument(
        "--run-id",
        default=None,
        help='Only include entries for this run. Use "latest" for the most recent metrics run.',
    )
    friction_list.add_argument(
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
            fixture_kwargs = {
                "metrics_db_path": args.metrics_db_path,
                "quiet_progress": args.quiet_progress,
            }
            if args.idea:
                artifacts = run_overture_fixture(
                    args.output_dir,
                    idea=args.idea,
                    **fixture_kwargs,
                )
            else:
                artifacts = run_overture_fixture(args.output_dir, **fixture_kwargs)
        except PipelineStageError as exc:
            print(f"fixture failed at {exc.stage}: {exc.message}", file=sys.stderr)
            return 1

        for stage, path in artifacts.items():
            print(f"{stage}: {path}")
        return 0

    if args.command == "run":
        return _run_single_shot(args)

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
        return _metrics(args)

    if args.command == "friction":
        return _friction(args)

    parser.print_help(sys.stderr)
    return 2


def _run_single_shot(args: argparse.Namespace) -> int:
    raw_text = " ".join(args.idea)
    stop_at_stage = _normalize_stage(args.stop_at_stage)
    try:
        artifacts = run_overture_fixture(
            args.output_dir,
            idea=raw_text,
            stop_at_stage=stop_at_stage,
            metrics_db_path=args.metrics_db_path,
            quiet_progress=args.quiet_progress,
        )
    except PipelineStageError as exc:
        print(f"run failed at {exc.stage}: {exc.message}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"run failed at setup: {exc}", file=sys.stderr)
        return 2

    artifact_stage = stop_at_stage or "ticket_draft"
    artifact_path = artifacts[artifact_stage]
    print(artifact_path)

    if args.export_to_linear and artifact_stage == "ticket_draft":
        export_code = _export_ticket(
            argparse.Namespace(
                ticket_path=Path(artifact_path),
                team_id=args.team_id,
                project_id=args.project_id,
                dry_run=args.dry_run,
                force_recreate=args.force_recreate,
                ledger_db=args.ledger_db,
            )
        )
        if export_code != 0:
            print(f"run failed at linear_export: export exited with code {export_code}", file=sys.stderr)
        return export_code

    return 0


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


def _metrics(args: argparse.Namespace) -> int:
    store = MetricsStore(args.db_path)
    summary = store.summary(last_runs=args.last)
    if not summary:
        print("no metrics recorded yet", file=sys.stderr)
        return 1

    total_runs = store.count_runs(args.last)
    if args.format == "json":
        payload = dict(summary)
        payload["total_runs"] = total_runs
        print(json.dumps(payload, sort_keys=True))
        return 0

    print(_metrics_table(summary))
    print(f"total runs: {total_runs}")
    return 0


def _friction(args: argparse.Namespace) -> int:
    log = FrictionLog(args.db_path)
    if args.friction_command == "append":
        run_id = _resolve_friction_run_id(log, args.run_id)
        if run_id is None:
            print("no metrics runs recorded yet", file=sys.stderr)
            return 1
        try:
            entry = log.append(
                session_id=args.session_id,
                run_id=run_id,
                category=args.category,
                note=args.note,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"friction entry {entry.id}: {entry.run_id} {entry.category}")
        return 0

    if args.friction_command == "list":
        run_id = None
        if args.run_id is not None:
            run_id = _resolve_friction_run_id(log, args.run_id)
            if run_id is None:
                print("no metrics runs recorded yet", file=sys.stderr)
                return 1
        entries = list(log.iter_entries(session_id=args.session_id, run_id=run_id))
        if args.format == "json":
            print(json.dumps([asdict(entry) for entry in entries], sort_keys=True))
            return 0
        print(_friction_table(entries))
        return 0

    return 2


def _resolve_friction_run_id(log: FrictionLog, run_id: str) -> str | None:
    if run_id == "latest":
        return log.latest_run_id()
    return run_id


def _metrics_table(summary: dict[str, dict[str, float | int]]) -> str:
    widths = {
        "stage": 12,
        "count": 8,
        "median_ms": 10,
        "p95_ms": 10,
        "success_rate": 12,
    }
    headers = ("stage", "count", "median_ms", "p95_ms", "success_rate")
    lines = [_format_metrics_row(dict(zip(headers, headers)), widths)]
    for stage_name in sorted(summary):
        stats = summary[stage_name]
        values = {
            "stage": stage_name[: widths["stage"]],
            "count": str(stats["count"]),
            "median_ms": _format_number(stats["median_ms"]),
            "p95_ms": _format_number(stats["p95_ms"]),
            "success_rate": f"{float(stats['success_rate']):.2f}",
        }
        lines.append(_format_metrics_row(values, widths))
    return "\n".join(lines)


def _format_metrics_row(values: dict[str, str], widths: dict[str, int]) -> str:
    return (
        f"{values['stage']:<{widths['stage']}} "
        f"{values['count']:>{widths['count']}} "
        f"{values['median_ms']:>{widths['median_ms']}} "
        f"{values['p95_ms']:>{widths['p95_ms']}} "
        f"{values['success_rate']:>{widths['success_rate']}}"
    ).rstrip()


def _friction_table(entries) -> str:
    widths = {
        "id": 4,
        "session": 14,
        "run_id": 12,
        "category": 10,
        "note": 48,
    }
    headers = {
        "id": "id",
        "session": "session",
        "run_id": "run_id",
        "category": "category",
        "note": "note",
    }
    lines = [_format_friction_row(headers, widths)]
    for entry in entries:
        values = {
            "id": str(entry.id),
            "session": entry.session_id[: widths["session"]],
            "run_id": entry.run_id[: widths["run_id"]],
            "category": entry.category,
            "note": entry.note[: widths["note"]],
        }
        lines.append(_format_friction_row(values, widths))
    return "\n".join(lines)


def _format_friction_row(values: dict[str, str], widths: dict[str, int]) -> str:
    return (
        f"{values['id']:>{widths['id']}} "
        f"{values['session']:<{widths['session']}} "
        f"{values['run_id']:<{widths['run_id']}} "
        f"{values['category']:<{widths['category']}} "
        f"{values['note']:<{widths['note']}}"
    ).rstrip()


def _format_number(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _stage_choices() -> tuple[str, ...]:
    choices: list[str] = []
    for stage in PIPELINE_STAGES:
        choices.append(stage)
        if "_" in stage:
            choices.append(stage.replace("_", "-"))
    return tuple(choices)


def _normalize_stage(stage: str | None) -> str | None:
    if stage is None:
        return None
    return stage.replace("-", "_")


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
