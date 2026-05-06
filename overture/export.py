"""Parse and validate ticket Markdown for Linear export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .fixture import validate_ticket_draft
from .ticket_writer import validate_linear_issue_payload


@dataclass(frozen=True)
class ParsedTicket:
    title: str
    description: str


def parse_ticket_file(path: Path | str) -> ParsedTicket:
    ticket_path = Path(path)
    markdown = ticket_path.read_text(encoding="utf-8")

    lines = markdown.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), "")
    description_start = next((index for index, line in enumerate(lines) if line.startswith("## ")), None)
    if not title:
        raise ValueError("ticket is missing a level-one title")
    if description_start is None:
        raise ValueError("ticket is missing section content")

    description = "\n".join(lines[description_start:]).strip() + "\n"
    errors = validate_linear_issue_payload(title, markdown)
    if errors:
        try:
            validate_ticket_draft(markdown)
        except ValueError:
            raise ValueError("; ".join(errors)) from None
    return ParsedTicket(title=title, description=description)
