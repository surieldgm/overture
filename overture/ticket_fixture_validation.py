"""Validate repository Markdown ticket fixtures for CI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .export import parse_ticket_file


DEFAULT_INTAKE_EXAMPLES_DIR = Path("examples") / "intake_examples"
DEFAULT_STANDALONE_TICKET = Path("examples") / "overture_mvp_linear_issue_draft.md"


@dataclass(frozen=True)
class TicketFixtureValidationError:
    path: Path
    message: str


def default_ticket_fixture_paths(workspace: Path | str = ".") -> tuple[Path, ...]:
    root = Path(workspace)
    intake_examples = sorted(
        path
        for path in (root / DEFAULT_INTAKE_EXAMPLES_DIR).glob("*.md")
        if path.name != "README.md"
    )
    return tuple(intake_examples + [root / DEFAULT_STANDALONE_TICKET])


def validate_ticket_fixture_paths(
    paths: Iterable[Path | str],
) -> list[TicketFixtureValidationError]:
    errors: list[TicketFixtureValidationError] = []
    for path_value in paths:
        path = Path(path_value)
        try:
            parse_ticket_file(path)
        except Exception as exc:
            errors.append(TicketFixtureValidationError(path=path, message=str(exc)))
    return errors


def render_ticket_fixture_errors(errors: Sequence[TicketFixtureValidationError]) -> str:
    return "\n".join(f"{error.path}: {error.message}" for error in errors)
