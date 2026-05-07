"""Shared Linear export runner for CLI and local UI flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .export import parse_ticket_file
from .export_store import ExportLedger, compute_hash
from .linear_client import CreatedIssue, LinearAPIError


@dataclass(frozen=True)
class ExportRunResult:
    status: str
    message: str
    url: str | None = None


LinearClientFactory = Callable[[], object]


def run_ticket_export(
    ticket_path: Path | str,
    *,
    team_id: str | None,
    project_id: str | None,
    dry_run: bool,
    force_recreate: bool = False,
    ledger_db: Path | str,
    linear_client_factory: LinearClientFactory,
) -> ExportRunResult:
    path = Path(ticket_path).expanduser().resolve(strict=False)
    if not path.exists():
        return ExportRunResult("error", f"ticket file not found: {path}")

    try:
        ticket_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ExportRunResult("error", f"could not read ticket file {path}: {exc}")

    ticket_hash = compute_hash(ticket_text)
    ticket_path_key = str(path)
    ledger = ExportLedger(ledger_db)
    record = None if dry_run else ledger.find(ticket_path_key)
    if record is not None and not force_recreate:
        if record.ticket_hash == ticket_hash:
            return ExportRunResult("already_exported", f"already exported: {record.linear_url}", record.linear_url)
        return ExportRunResult("changed", f"ticket changed since last export: {record.linear_url}", record.linear_url)

    try:
        parsed = parse_ticket_file(path)
    except ValueError as exc:
        return ExportRunResult("error", str(exc))

    if dry_run:
        lines = [f"would create: title={parsed.title}"]
        if parsed.metadata.sprint_label:
            lines.append(f"metadata sprint_label={parsed.metadata.sprint_label}")
        if parsed.metadata.priority is not None:
            lines.append(f"metadata priority={parsed.metadata.priority}")
        if parsed.metadata.milestone:
            lines.append(f"metadata milestone={parsed.metadata.milestone}")
        lines.append(parsed.description.rstrip("\n"))
        return ExportRunResult("dry_run", "\n".join(lines).rstrip() + "\n")

    if not team_id:
        return ExportRunResult("error", "missing required Linear team id: pass --team-id or set LINEAR_TEAM_ID")
    if parsed.metadata.milestone and not project_id:
        return ExportRunResult(
            "error",
            "missing required Linear project id for frontmatter milestone: pass --project-id or set LINEAR_PROJECT_ID",
        )

    try:
        client = linear_client_factory()
        issue = client.create_issue(
            team_id=team_id,
            title=parsed.title,
            description=parsed.description,
            project_id=project_id,
            priority=parsed.metadata.priority,
            sprint_label=parsed.metadata.sprint_label,
            milestone=parsed.metadata.milestone,
        )
    except RuntimeError as exc:
        return ExportRunResult("error", str(exc))
    except LinearAPIError as exc:
        return ExportRunResult("error", str(exc))

    if not isinstance(issue, CreatedIssue):
        issue = CreatedIssue(id=str(issue.id), identifier=str(issue.identifier), url=str(issue.url))
    ledger.record(ticket_path_key, ticket_hash, issue.id, issue.url)
    return ExportRunResult("exported", issue.url, issue.url)
