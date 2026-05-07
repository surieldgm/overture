"""Peer onboarding template schema and initialization helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Mapping

PEER_ONBOARDING_SCHEMA_VERSION = "2026-05-07"

PEER_ONBOARDING_SCHEMA: tuple[dict[str, object], ...] = (
    {
        "id": "intake_worked",
        "order": 1,
        "title": "What intake worked",
        "description": "Capture the prompts, examples, and constraints that helped the first designer start cleanly.",
        "fields": (
            {
                "id": "summary",
                "label": "Useful intake pattern",
                "kind": "free_text",
                "required": False,
            },
            {
                "id": "example_prompts",
                "label": "Example prompts",
                "kind": "list_text",
                "required": False,
            },
        ),
    },
    {
        "id": "research_approval",
        "order": 2,
        "title": "What research approval looked like",
        "description": "Explain how sources were inspected and what made a source acceptable to carry forward.",
        "fields": (
            {
                "id": "approval_summary",
                "label": "Approval summary",
                "kind": "free_text",
                "required": False,
            },
            {
                "id": "approved_source_traits",
                "label": "Approved source traits",
                "kind": "list_text",
                "required": False,
            },
        ),
    },
    {
        "id": "wizard_watchouts",
        "order": 3,
        "title": "What to watch out for at each wizard step",
        "description": "Structured notes for each current wizard step so the next designer can keep context while running a session.",
        "fields": (
            {
                "id": "step_notes",
                "label": "Wizard step notes",
                "kind": "wizard_step_notes",
                "required": False,
                "steps": ("Intake", "Research", "Synthesis", "Ticket", "Export"),
            },
        ),
    },
)


def initialize_peer_onboarding_template(author_id: str, author_email: str) -> dict[str, object]:
    """Return an empty active-version peer onboarding template for an author."""

    return {
        "schema_version": PEER_ONBOARDING_SCHEMA_VERSION,
        "author": {
            "id": str(author_id),
            "email": str(author_email),
        },
        "sections": [_empty_section(section) for section in PEER_ONBOARDING_SCHEMA],
    }


def ordered_peer_onboarding_sections(template: Mapping[str, object]) -> list[dict[str, object]]:
    """Return template sections sorted by order while tolerating future extensions."""

    raw_sections = template.get("sections", [])
    if not isinstance(raw_sections, list):
        return []
    sections = [section for section in raw_sections if isinstance(section, dict)]
    return sorted(sections, key=_section_order)


def _empty_section(section_schema: Mapping[str, object]) -> dict[str, object]:
    section = {
        "id": section_schema["id"],
        "order": section_schema["order"],
        "title": section_schema["title"],
        "description": section_schema["description"],
        "fields": [],
    }
    for field_schema in section_schema.get("fields", ()):
        if not isinstance(field_schema, Mapping):
            continue
        field = deepcopy(dict(field_schema))
        field["value"] = _empty_value_for_kind(str(field.get("kind", "")), field)
        section["fields"].append(field)
    return section


def _empty_value_for_kind(kind: str, field: Mapping[str, object]) -> object:
    if kind == "list_text":
        return []
    if kind == "wizard_step_notes":
        steps = field.get("steps", ())
        if not isinstance(steps, tuple):
            steps = tuple(steps) if isinstance(steps, list) else ()
        return [{"step": str(step), "note": ""} for step in steps]
    return ""


def _section_order(section: Mapping[str, object]) -> int:
    try:
        return int(section.get("order", 10_000))
    except (TypeError, ValueError):
        return 10_000
