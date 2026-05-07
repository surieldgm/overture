"""Parse and validate ticket Markdown for Linear export.

Ticket files may start with an optional TOML frontmatter block delimited by
``---`` lines. The parser intentionally stays stdlib-only via ``tomllib`` and
supports only the metadata Linear export currently understands:
``sprint_label``, ``priority``, and ``milestone``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any, Mapping

from .fixture import validate_ticket_draft
from .ticket_writer import validate_linear_issue_payload


@dataclass(frozen=True)
class TicketMetadata:
    sprint_label: str | None = None
    priority: int | None = None
    milestone: str | None = None


@dataclass(frozen=True)
class ParsedTicket:
    title: str
    description: str
    metadata: TicketMetadata = TicketMetadata()


def parse_ticket_file(path: Path | str) -> ParsedTicket:
    ticket_path = Path(path)
    return parse_ticket_markdown(ticket_path.read_text(encoding="utf-8"))


def parse_ticket_markdown(markdown: str) -> ParsedTicket:
    """Parse and validate ticket Markdown using the export contract."""

    metadata, body = parse_ticket_frontmatter(markdown)
    body = _ticket_body_from_fixture_markdown(body)

    lines = body.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), "")
    description_start = next((index for index, line in enumerate(lines) if line.startswith("## ")), None)
    if not title:
        raise ValueError("ticket is missing a level-one title")
    if description_start is None:
        raise ValueError("ticket is missing section content")

    description = "\n".join(lines[description_start:]).strip() + "\n"
    errors = validate_linear_issue_payload(title, body)
    if errors:
        try:
            validate_ticket_draft(body)
        except ValueError:
            raise ValueError("; ".join(errors)) from None
    return ParsedTicket(title=title, description=description, metadata=metadata)


def _ticket_body_from_fixture_markdown(markdown: str) -> str:
    """Extract the embedded ticket draft from an intake example when present."""

    marker = "\n## Ticket\n"
    if marker not in markdown:
        return markdown
    return markdown.split(marker, 1)[1].lstrip()


def parse_ticket_frontmatter(markdown: str) -> tuple[TicketMetadata, str]:
    """Return parsed metadata and Markdown body after optional frontmatter."""

    if not markdown.startswith("---\n"):
        return TicketMetadata(), markdown

    closing = markdown.find("\n---", 4)
    if closing == -1:
        raise ValueError("invalid frontmatter: missing closing delimiter")
    delimiter_end = closing + len("\n---")
    if delimiter_end < len(markdown) and markdown[delimiter_end : delimiter_end + 1] not in ("\n", "\r"):
        raise ValueError("invalid frontmatter: closing delimiter must be on its own line")

    raw_frontmatter = markdown[4:closing]
    body = markdown[delimiter_end:].lstrip("\r\n")
    try:
        parsed = tomllib.loads(raw_frontmatter)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid frontmatter: {exc}") from None
    return _metadata_from_mapping(parsed), body


def _metadata_from_mapping(values: Mapping[str, Any]) -> TicketMetadata:
    supported = {"sprint_label", "priority", "milestone"}
    unknown = sorted(set(values) - supported)
    if unknown:
        raise ValueError("invalid frontmatter: unknown keys: " + ", ".join(unknown))

    sprint_label = _optional_text(values.get("sprint_label"), "sprint_label")
    milestone = _optional_text(values.get("milestone"), "milestone")
    priority = _optional_priority(values.get("priority"))
    return TicketMetadata(sprint_label=sprint_label, priority=priority, milestone=milestone)


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid frontmatter: {field} must be a non-empty string")
    return value.strip()


def _optional_priority(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 4:
        raise ValueError("invalid frontmatter: priority must be an integer from 0 to 4")
    return value
