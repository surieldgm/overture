"""Markdown retrospective artifact generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import statistics
from typing import Iterable

from .friction_log import FRICTION_CATEGORIES, FrictionEntry, FrictionLog
from .metrics_store import DEFAULT_METRICS_DB_PATH, StageMetric, MetricsStore

DEFAULT_RETRO_OUTPUT_PATH = Path(".overture") / "retros" / "milestone-retro.md"


@dataclass(frozen=True)
class RetroWindow:
    milestone: str
    started_at: str
    completed_at: str


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
    summary = _summarize_metrics(metrics)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_retro_markdown(window, frictions, summary), encoding="utf-8")
    return target


def render_retro_markdown(
    window: RetroWindow,
    frictions: Iterable[FrictionEntry],
    metrics_summary: dict[str, dict[str, float | int]],
) -> str:
    entries = list(frictions)
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


def _group_frictions(entries: Iterable[FrictionEntry]) -> dict[str, list[FrictionEntry]]:
    grouped = {category: [] for category in FRICTION_CATEGORIES}
    for entry in entries:
        grouped.setdefault(entry.category, []).append(entry)
    return grouped


def _format_category_counts(by_category: dict[str, list[FrictionEntry]]) -> str:
    counts = [f"{category}={len(by_category.get(category, []))}" for category in FRICTION_CATEGORIES]
    return ", ".join(counts)


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
