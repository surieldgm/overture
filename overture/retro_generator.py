"""Markdown retrospective artifact generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import statistics
from typing import Iterable

from .friction_log import FRICTION_CATEGORIES, FrictionEntry, FrictionLog
from .metrics_store import DEFAULT_METRICS_DB_PATH, MetricsStore, StageMetric, TicketMetric
from .observation_log import ObservationEvent, ObservationLog

DEFAULT_RETRO_OUTPUT_PATH = Path(".overture") / "retros" / "milestone-retro.md"


@dataclass(frozen=True)
class RetroWindow:
    milestone: str
    started_at: str
    completed_at: str


@dataclass(frozen=True)
class DesignerRetroData:
    author_key: str
    author_email: str | None
    metrics: tuple[StageMetric, ...]
    ticket_metrics: tuple[TicketMetric, ...]
    observations: tuple[ObservationEvent, ...]
    frictions: tuple[FrictionEntry, ...]


def generate_retro_document(
    *,
    db_path: Path | str = DEFAULT_METRICS_DB_PATH,
    output_path: Path | str = DEFAULT_RETRO_OUTPUT_PATH,
    milestone: str,
    started_at: str,
    completed_at: str,
) -> Path:
    """Write one Markdown retrospective artifact for a milestone window."""

    window = RetroWindow(
        milestone=_require_text(milestone, "milestone"),
        started_at=_require_text(started_at, "started_at"),
        completed_at=_require_text(completed_at, "completed_at"),
    )
    _validate_window(window)

    metrics_store = MetricsStore(db_path)
    friction_log = FrictionLog(db_path)
    metrics = _metrics_in_window(metrics_store.iter_stages(), window)
    frictions = _frictions_in_window(friction_log.iter_entries(), window)
    observations = _observations_in_window(ObservationLog(db_path).iter_events(), window)
    ticket_metrics = tuple(
        ticket
        for ticket in metrics_store.iter_ticket_rework_counters()
        if ticket.milestone is None or ticket.milestone == window.milestone
    )
    summary = _summarize_metrics(metrics)
    designer_sections = _designer_sections(metrics, ticket_metrics, observations, frictions)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_retro_markdown(
            window,
            frictions,
            summary,
            designer_sections=designer_sections if window.milestone.upper() == "M3" else (),
        ),
        encoding="utf-8",
    )
    return target


def render_retro_markdown(
    window: RetroWindow,
    frictions: Iterable[FrictionEntry],
    metrics_summary: dict[str, dict[str, float | int]],
    *,
    designer_sections: Iterable[DesignerRetroData] = (),
) -> str:
    entries = list(frictions)
    designers = list(designer_sections)
    lines: list[str] = [
        f"# {window.milestone} Retrospective",
        "",
        "## Executive Summary",
        "",
        f"- Milestone window: `{window.started_at}` to `{window.completed_at}`.",
        f"- Friction entries in window: {len(entries)}.",
        f"- Metrics stages in window: {len(metrics_summary)}.",
        "- Dependency: this artifact only reflects frictions and metrics captured in the local Overture stores.",
        "",
        "## Time Distribution",
        "",
    ]

    if metrics_summary:
        lines.extend(
            [
                "| Stage | Count | Median ms | P95 ms | Success rate |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for stage_name in sorted(metrics_summary):
            stats = metrics_summary[stage_name]
            lines.append(
                "| "
                f"{_escape_table(stage_name)} | "
                f"{stats['count']} | "
                f"{_format_number(stats['median_ms'])} | "
                f"{_format_number(stats['p95_ms'])} | "
                f"{float(stats['success_rate']):.2f} |"
            )
    else:
        lines.append("_No metrics were recorded in this milestone window._")

    lines.extend(["", "## Frictions By Category", ""])
    by_category = _group_frictions(entries)
    for category in FRICTION_CATEGORIES:
        category_entries = by_category[category]
        lines.extend([f"### {category.title()}", ""])
        if not category_entries:
            lines.append("_No entries._")
        else:
            for entry in category_entries:
                lines.append(
                    f"- `{entry.created_at}` session `{entry.session_id}` run `{entry.run_id}`: {entry.note}"
                )
        lines.append("")

    lines.extend(
        [
            "## Observations",
            "",
            "- This section is generated from raw counts only.",
            f"- Captured friction categories with entries: {_format_category_counts(by_category)}.",
            f"- Captured metric stage rows: {sum(int(stats['count']) for stats in metrics_summary.values())}.",
            "",
            "## M2 Implications",
            "",
            "- No generated interpretation is included.",
            "- Review the friction entries and metrics table above when scoping M2.",
            "",
        ]
    )
    if designers:
        lines.extend(_render_m3_designer_sections(designers))
        lines.extend(_render_m3_team_section(designers))
    return "\n".join(lines)


def _metrics_in_window(metrics: Iterable[StageMetric], window: RetroWindow) -> list[StageMetric]:
    started = _parse_iso(window.started_at)
    completed = _parse_iso(window.completed_at)
    return [
        metric
        for metric in metrics
        if started <= _parse_iso(metric.started_at) and _parse_iso(metric.completed_at) <= completed
    ]


def _frictions_in_window(entries: Iterable[FrictionEntry], window: RetroWindow) -> list[FrictionEntry]:
    started = _parse_iso(window.started_at)
    completed = _parse_iso(window.completed_at)
    return [entry for entry in entries if started <= _parse_iso(entry.created_at) <= completed]


def _observations_in_window(events: Iterable[ObservationEvent], window: RetroWindow) -> list[ObservationEvent]:
    started = _parse_iso(window.started_at)
    completed = _parse_iso(window.completed_at)
    return [event for event in events if started <= _parse_iso(event.occurred_at) <= completed]


def _summarize_metrics(metrics: Iterable[StageMetric]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[StageMetric]] = {}
    for metric in metrics:
        grouped.setdefault(metric.stage_name, []).append(metric)

    summary: dict[str, dict[str, float | int]] = {}
    for stage_name, stage_metrics in grouped.items():
        durations = [metric.duration_ms for metric in stage_metrics]
        success_count = sum(1 for metric in stage_metrics if metric.status == "success")
        summary[stage_name] = {
            "count": len(durations),
            "median_ms": statistics.median(durations),
            "p95_ms": _p95(durations),
            "success_rate": success_count / len(durations),
        }
    return summary


def _designer_sections(
    metrics: Iterable[StageMetric],
    ticket_metrics: Iterable[TicketMetric],
    observations: Iterable[ObservationEvent],
    frictions: Iterable[FrictionEntry],
) -> tuple[DesignerRetroData, ...]:
    metrics_by_author: dict[str, list[StageMetric]] = {}
    tickets_by_author: dict[str, list[TicketMetric]] = {}
    observations_by_author: dict[str, list[ObservationEvent]] = {}
    frictions_by_author: dict[str, list[FrictionEntry]] = {}
    emails: dict[str, str] = {}

    for metric in metrics:
        key = _author_key(metric.author_id, metric.author_email)
        metrics_by_author.setdefault(key, []).append(metric)
        _remember_email(emails, key, metric.author_email)
    for ticket in ticket_metrics:
        key = _author_key(ticket.author_id, ticket.author_email)
        tickets_by_author.setdefault(key, []).append(ticket)
        _remember_email(emails, key, ticket.author_email)
    for event in observations:
        key = _author_key(event.author_id, event.author_email)
        observations_by_author.setdefault(key, []).append(event)
        _remember_email(emails, key, event.author_email)
    for friction in frictions:
        if not friction.confirmed:
            continue
        key = _author_key(friction.author_id, friction.author_email)
        frictions_by_author.setdefault(key, []).append(friction)
        _remember_email(emails, key, friction.author_email)

    author_keys = sorted(
        set(metrics_by_author)
        | set(tickets_by_author)
        | set(observations_by_author)
        | set(frictions_by_author)
    )
    return tuple(
        DesignerRetroData(
            author_key=author_key,
            author_email=emails.get(author_key),
            metrics=tuple(metrics_by_author.get(author_key, ())),
            ticket_metrics=tuple(tickets_by_author.get(author_key, ())),
            observations=tuple(observations_by_author.get(author_key, ())),
            frictions=tuple(frictions_by_author.get(author_key, ())),
        )
        for author_key in author_keys
    )


def _render_m3_designer_sections(designers: Iterable[DesignerRetroData]) -> list[str]:
    lines = ["## Designer Breakdowns", ""]
    for designer in designers:
        lines.extend(
            [
                f"### Designer: {_escape_heading(designer.author_key)}",
                "",
                f"- Author email: {_format_optional(designer.author_email)}.",
                "- Redaction review required: yes.",
                "",
                "#### Sprint Metrics",
                "",
            ]
        )
        lines.extend(_render_designer_metrics(designer))
        lines.extend(["", "#### Observation Highlights", ""])
        lines.extend(_render_designer_observations(designer.observations))
        lines.extend(["", "#### Confirmed Frictions", ""])
        lines.extend(_render_designer_frictions(designer.frictions))
        lines.append("")
    return lines


def _render_designer_metrics(designer: DesignerRetroData) -> list[str]:
    if not designer.metrics and not designer.ticket_metrics:
        return ["_No metrics were recorded for this designer._"]

    lines = [
        "| Sprint | Stage | Count | Median ms | P95 ms | Success rate | Rework count |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    sprint_rework = _rework_by_sprint(designer.ticket_metrics)
    stage_summary = _summarize_metrics(designer.metrics)
    if stage_summary:
        for stage_name in sorted(stage_summary):
            stats = stage_summary[stage_name]
            lines.append(
                "| "
                "milestone window | "
                f"{_escape_table(stage_name)} | "
                f"{stats['count']} | "
                f"{_format_number(stats['median_ms'])} | "
                f"{_format_number(stats['p95_ms'])} | "
                f"{float(stats['success_rate']):.2f} | "
                f"{sum(sprint_rework.values())} |"
            )
    for sprint in sorted(sprint_rework):
        lines.append(
            "| "
            f"{_escape_table(sprint)} | "
            "ticket rework | "
            "0 | 0 | 0 | 0.00 | "
            f"{sprint_rework[sprint]} |"
        )
    return lines


def _render_designer_observations(events: Iterable[ObservationEvent]) -> list[str]:
    event_list = list(events)
    if not event_list:
        return ["_No observation events were recorded for this designer._"]
    return [
        f"- `{event.occurred_at}` session `{event.session_id}` `{event.event_type}` `{event.action}` on `{event.route}`{_format_error(event.error)}."
        for event in event_list
    ]


def _render_designer_frictions(frictions: Iterable[FrictionEntry]) -> list[str]:
    entries = list(frictions)
    if not entries:
        return ["_No confirmed frictions were recorded for this designer._"]
    return [
        f"- confirmed `{entry.category}` friction in session `{entry.session_id}` run `{entry.run_id}` at `{entry.created_at}`: {entry.note}"
        for entry in entries
    ]


def _render_m3_team_section(designers: Iterable[DesignerRetroData]) -> list[str]:
    designer_list = list(designers)
    category_counts = {category: 0 for category in FRICTION_CATEGORIES}
    for designer in designer_list:
        for entry in designer.frictions:
            category_counts[entry.category] = category_counts.get(entry.category, 0) + 1

    lines = [
        "## M3 Team-Wide Designer Synthesis",
        "",
        f"- Designers with captured data: {len(designer_list)}.",
        f"- Designers with confirmed frictions: {sum(1 for designer in designer_list if designer.frictions)}.",
        f"- Designers with observation events: {sum(1 for designer in designer_list if designer.observations)}.",
        f"- Confirmed friction category counts: {_format_category_counts(category_counts)}.",
        "",
        "| Designer | Metric rows | Observation events | Confirmed frictions |",
        "| --- | ---: | ---: | ---: |",
    ]
    for designer in designer_list:
        lines.append(
            "| "
            f"{_escape_table(designer.author_key)} | "
            f"{len(designer.metrics)} | "
            f"{len(designer.observations)} | "
            f"{len(designer.frictions)} |"
        )
    lines.append("")
    return lines


def _rework_by_sprint(ticket_metrics: Iterable[TicketMetric]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ticket in ticket_metrics:
        sprint = ticket.sprint_label or "unknown sprint"
        counts[sprint] = counts.get(sprint, 0) + ticket.rework_count
    return counts


def _group_frictions(entries: Iterable[FrictionEntry]) -> dict[str, list[FrictionEntry]]:
    grouped = {category: [] for category in FRICTION_CATEGORIES}
    for entry in entries:
        grouped.setdefault(entry.category, []).append(entry)
    return grouped


def _format_category_counts(by_category: dict[str, list[FrictionEntry]]) -> str:
    counts = [f"{category}={_category_count(by_category, category)}" for category in FRICTION_CATEGORIES]
    return ", ".join(counts)


def _category_count(by_category: dict[str, list[FrictionEntry]] | dict[str, int], category: str) -> int:
    value = by_category.get(category, 0)
    if isinstance(value, int):
        return value
    return len(value)


def _author_key(author_id: str | None, author_email: str | None) -> str:
    return _optional_text(author_id) or _optional_text(author_email) or "unknown author"


def _remember_email(emails: dict[str, str], author_key: str, author_email: str | None) -> None:
    email = _optional_text(author_email)
    if email and author_key not in emails:
        emails[author_key] = email


def _optional_text(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _format_optional(value: str | None) -> str:
    return f"`{value}`" if value else "_not recorded_"


def _format_error(error: str | None) -> str:
    return f" error `{error}`" if error else ""


def _validate_window(window: RetroWindow) -> None:
    if _parse_iso(window.completed_at) < _parse_iso(window.started_at):
        raise ValueError("completed_at must not be earlier than started_at")


def _require_text(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _p95(durations: list[int]) -> float | int:
    if len(durations) == 1:
        return durations[0]
    return statistics.quantiles(durations, n=100, method="inclusive")[94]


def _format_number(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|")


def _escape_heading(value: str) -> str:
    return value.replace("#", "\\#").strip()
