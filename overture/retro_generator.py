"""Markdown retrospective artifact generation."""

from __future__ import annotations

import re
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


@dataclass(frozen=True)
class PersonaFinding:
    number: str
    severity: str
    description: str


@dataclass(frozen=True)
class PersonaMonologue:
    persona: str
    text: str


@dataclass(frozen=True)
class ParsedPersonaReport:
    headline_metric: str
    closed_baseline_findings: tuple[PersonaFinding, ...]
    residual_findings: tuple[PersonaFinding, ...]
    new_findings: tuple[PersonaFinding, ...]
    monologues: tuple[PersonaMonologue, ...]


def generate_retro_document(
    *,
    db_path: Path | str = DEFAULT_METRICS_DB_PATH,
    output_path: Path | str = DEFAULT_RETRO_OUTPUT_PATH,
    persona_report_path: Path | str | None = None,
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

    if persona_report_path is not None:
        parsed = _parse_persona_report(persona_report_path)
        rendered = render_persona_retro_markdown(window, parsed)
    else:
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
        rendered = render_retro_markdown(
            window,
            frictions,
            summary,
            designer_sections=designer_sections if window.milestone.upper() == "M3" else (),
        )

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
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
    designer_summaries = _designer_summaries(entries)
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
            "## Team Summary",
            "",
            f"- Designers represented: {len(designer_summaries)}.",
            f"- Confirmed friction entries: {len(entries)}.",
            f"- Captured friction categories with entries: {_format_category_counts(by_category)}.",
            "",
            "## Designer Summaries",
            "",
        ]
    )
    if designer_summaries:
        for designer in designer_summaries:
            lines.extend(
                [
                    f"### {designer['label']}",
                    "",
                    f"- Confirmed friction entries: {designer['count']}.",
                    f"- Categories: {designer['categories']}.",
                    f"- Sessions: {designer['sessions']}.",
                    "",
                ]
            )
    else:
        lines.extend(["_No designer-authored friction entries recorded._", ""])

    lines.extend(
        [
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


def render_persona_retro_markdown(window: RetroWindow, report: ParsedPersonaReport) -> str:
    lines: list[str] = [
        f"# {window.milestone} Retrospective",
        "",
        "## M-WIZ Persona Report",
        "",
        "### Headline metric",
        "",
        f"- {report.headline_metric}",
        "",
        "## Closed baseline findings",
        "",
    ]

    if report.closed_baseline_findings:
        for finding in report.closed_baseline_findings:
            lines.append(f"- {finding.number} ({_normalize_severity(finding.severity)}): {finding.description}")
    else:
        lines.append("_No baseline findings were confirmed as closed._")

    lines.extend(["", "## Residual findings carried forward", ""])
    residuals_by_severity = _group_findings_by_severity(report.residual_findings)
    if residuals_by_severity:
        for severity in sorted(residuals_by_severity):
            lines.append(f"### {severity}")
            for finding in residuals_by_severity[severity]:
                lines.append(f"- {finding.number}: {finding.description}")
            lines.append("")
    else:
        lines.append("_No residual findings were carried forward._")

    lines.extend(["## New findings discovered during M-WIZ", ""])
    if report.new_findings:
        for finding in report.new_findings:
            lines.append(f"- {finding.number} ({_normalize_severity(finding.severity)}): {finding.description}")
    else:
        lines.append("_No new findings were observed during this run._")

    lines.extend(["", "## Qualitative summary", "", _persona_summary_paragraph(report)])
    return "\n".join(lines)


def _parse_persona_report(path: Path | str) -> ParsedPersonaReport:
    report_path = Path(path)
    if not report_path.exists():
        raise ValueError(f"persona report not found: {report_path}")

    report_lines = report_path.read_text(encoding="utf-8").splitlines()
    sections: dict[str, list[str]] = {"preamble": []}
    current_section = "preamble"

    for raw_line in report_lines:
        heading = _parse_markdown_heading(raw_line)
        if heading is None:
            sections[current_section].append(raw_line)
            continue

        section_key = _normalize_heading(heading)
        current_section = section_key
        sections.setdefault(section_key, [])

    headline_metric = _extract_headline_metric(_find_section(sections, "headline metric"))
    baseline_rows = _parse_markdown_table(
        _find_section(sections, "baseline comparison table"),
        expected_columns=5,
    )
    if baseline_rows is None:
        raise ValueError("persona report missing required section: baseline comparison table")

    closed, residual = _split_baseline_findings(baseline_rows)
    new_findings = tuple(
        _parse_new_finding_rows(
            _parse_markdown_table(
                _find_section(sections, "new findings"),
                expected_columns=3,
            )
        )
    )

    residual_bullets = _parse_residual_bullet_list(_find_section(sections, "residuals"))
    residual = list(residual)
    residual_numbers = {item.number for item in residual}
    for item in residual_bullets:
        if item.number not in residual_numbers:
            residual.append(item)
            residual_numbers.add(item.number)

    residual = tuple(
        sorted(
            residual,
            key=lambda finding: (finding.number, finding.severity, finding.description),
        )
    )

    monologues = tuple(_extract_persona_monologues(report_lines))

    return ParsedPersonaReport(
        headline_metric=headline_metric,
        closed_baseline_findings=tuple(sorted(closed, key=lambda finding: finding.number)),
        residual_findings=tuple(sorted(residual, key=lambda finding: finding.number)),
        new_findings=tuple(sorted(new_findings, key=lambda finding: finding.number)),
        monologues=monologues,
    )


def _find_section(sections: dict[str, list[str]], name: str) -> list[str]:
    if name in sections:
        return sections[name]
    for section_name, value in sections.items():
        if section_name.startswith(name):
            return value
    return []


def _parse_markdown_heading(line: str) -> str | None:
    match = re.match(r"^\s*#{1,6}\s+(.*)\s*$", line)
    if not match:
        return None
    return match.group(1).strip()


def _normalize_heading(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().lower())


def _extract_headline_metric(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        bold = re.search(r"\*\*(.+?)\*\*", stripped)
        if bold:
            return bold.group(1).strip()
        if stripped.startswith("-"):
            stripped = stripped.lstrip("-").strip()
            if stripped:
                return stripped
        return stripped
    raise ValueError("persona report missing required section: headline metric")


def _parse_markdown_table(lines: list[str], expected_columns: int) -> list[tuple[str, ...]] | None:
    rows: list[tuple[str, ...]] = []
    found_header = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in stripped.strip("|").split("|"))
        if len(cells) <= 2:
            continue
        if not found_header:
            if set(cells) == {"-"} or any("finding" in cell.lower() for cell in cells):
                found_header = True
            continue
        if _is_markdown_separator_row(cells):
            continue
        if len(cells) >= expected_columns:
            rows.append(cells[:expected_columns])
    return rows if found_header else None


def _is_markdown_separator_row(cells: tuple[str, ...]) -> bool:
    if not cells:
        return True
    return all(re.fullmatch(r"-{3,}", cell) is not None for cell in cells if cell)


def _split_baseline_findings(
    rows: list[tuple[str, ...]]
) -> tuple[tuple[PersonaFinding, ...], tuple[PersonaFinding, ...]]:
    closed: list[PersonaFinding] = []
    residual: list[PersonaFinding] = []
    for row in rows:
        entry = PersonaFinding(
            number=_normalize_finding_number(row[0]),
            severity=row[1],
            description=row[2],
        )
        status = row[3].strip().lower()
        if "closed" in status:
            closed.append(entry)
        elif status.startswith("residual"):
            residual.append(entry)
    return tuple(closed), tuple(residual)


def _parse_new_finding_rows(rows: list[tuple[str, ...]] | None) -> tuple[PersonaFinding, ...]:
    if rows is None:
        return ()
    findings: list[PersonaFinding] = []
    for row in rows:
        findings.append(
            PersonaFinding(
                number=_normalize_finding_number(row[0]),
                severity=row[1],
                description=row[2],
            )
        )
    return tuple(findings)


def _parse_residual_bullet_list(lines: list[str]) -> list[PersonaFinding]:
    residuals: list[PersonaFinding] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        match = re.match(r"-\s*(.+)$", stripped)
        if not match:
            continue
        payload = match.group(1).strip()
        number_match = re.match(r"(?P<number>#\S+)\s+(?P<rest>.+)", payload)
        if number_match:
            finding_number = number_match.group("number")
            rest = number_match.group("rest")
        else:
            finding_number = f"R{len(residuals) + 1}"
            rest = payload
        parts = rest.split(" ", 1)
        if len(parts) == 2:
            severity = parts[0].strip("()")
            description = parts[1]
        else:
            severity = "Unknown"
            description = rest
        residuals.append(
            PersonaFinding(
                number=_normalize_finding_number(finding_number),
                severity=severity,
                description=description,
            )
        )
    return residuals


def _normalize_finding_number(value: str) -> str:
    return value.strip()


def _extract_persona_monologues(lines: list[str]) -> list[PersonaMonologue]:
    monologues: list[PersonaMonologue] = []
    current_persona = "Unknown persona"
    in_persona_section = False
    for raw_line in lines:
        heading = _parse_markdown_heading(raw_line)
        if heading is not None:
            normalized_heading = _normalize_heading(heading)
            in_persona_section = "persona section" in normalized_heading
            if in_persona_section:
                if ":" in heading:
                    current_persona = heading.split(":", 1)[1].split("(")[0].strip()
            continue

        if not in_persona_section:
            continue

        outcome = re.match(r"^\s*Outcome:\s*(.+)$", raw_line, re.IGNORECASE)
        if outcome:
            text = outcome.group(1).strip().strip('"')
            if text:
                if all(
                    quote.persona != current_persona or quote.text != text
                    for quote in monologues
                ):
                    monologues.append(PersonaMonologue(persona=current_persona, text=text))
            continue

        for quote in re.findall(r'"([^"]+)"', raw_line):
            quote = quote.strip()
            if quote and len(quote) >= 12:
                monologues.append(PersonaMonologue(persona=current_persona, text=quote))

    if not monologues:
        monologues.append(
            PersonaMonologue(
                persona="Summary",
                text="The report did not include explicit quoted monologues.",
            )
        )
    return monologues


def _group_findings_by_severity(
    findings: Iterable[PersonaFinding],
) -> dict[str, list[PersonaFinding]]:
    grouped: dict[str, list[PersonaFinding]] = {}
    for finding in findings:
        grouped.setdefault(_normalize_severity(finding.severity), []).append(finding)
    return grouped


def _normalize_severity(value: str) -> str:
    return (value or "Unknown").strip()


def _persona_summary_paragraph(report: ParsedPersonaReport) -> str:
    closed_ids = [finding.number for finding in report.closed_baseline_findings]
    if closed_ids:
        closing = f"Closed baseline findings were confirmed in this run: {', '.join(closed_ids)}."
    else:
        closing = "No closed baseline findings were confirmed in this run."

    quotes = [f"{quote.persona}: \"{quote.text}\"" for quote in report.monologues]
    if quotes:
        return f"{closing} " + " ".join(quotes)
    return closing


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


def _designer_summaries(entries: Iterable[FrictionEntry]) -> list[dict[str, str | int]]:
    grouped: dict[str, list[FrictionEntry]] = {}
    labels: dict[str, str] = {}
    for entry in entries:
        key = entry.author_id or entry.author_email or entry.session_id
        label = entry.author_email or entry.author_id or entry.session_id
        grouped.setdefault(key, []).append(entry)
        labels.setdefault(key, label)

    summaries: list[dict[str, str | int]] = []
    for key in sorted(grouped, key=lambda value: labels[value]):
        designer_entries = grouped[key]
        summaries.append(
            {
                "label": labels[key],
                "count": len(designer_entries),
                "categories": _format_nonempty_counts(entry.category for entry in designer_entries),
                "sessions": ", ".join(
                    f"`{session}`" for session in _ordered_unique(entry.session_id for entry in designer_entries)
                ),
            }
        )
    return summaries


def _format_category_counts(by_category: dict[str, list[FrictionEntry]]) -> str:
    counts = [f"{category}={_category_count(by_category, category)}" for category in FRICTION_CATEGORIES]
    return ", ".join(counts)


def _format_nonempty_counts(values: Iterable[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return ", ".join(f"{value}={counts[value]}" for value in sorted(counts))


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


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
