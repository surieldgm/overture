"""Classify Linear webhook payloads for issue rework signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_STATE_RANKS = {
    "triage": 0,
    "backlog": 0,
    "todo": 1,
    "in progress": 2,
    "in review": 3,
    "review": 3,
    "human review": 3,
    "merging": 4,
    "done": 5,
    "completed": 5,
    "canceled": 5,
    "cancelled": 5,
}


@dataclass(frozen=True)
class ReworkSignal:
    event_id: str
    issue_id: str
    issue_identifier: str | None
    author_id: str
    author_email: str | None
    from_state: str
    to_state: str
    occurred_at: str


def classify_linear_webhook(payload: Mapping[str, Any]) -> ReworkSignal | None:
    """Return a rework signal when a Linear issue moves backward in workflow."""

    if str(payload.get("type") or "").lower() != "issue":
        return None
    if str(payload.get("action") or "").lower() not in {"update", "updated"}:
        return None

    data = _mapping(payload.get("data"))
    updated_from = _mapping(payload.get("updatedFrom"))
    from_state = _state_name(updated_from.get("state"))
    to_state = _state_name(data.get("state"))
    if not from_state or not to_state:
        return None
    if _state_rank(to_state) >= _state_rank(from_state):
        return None

    actor = _mapping(payload.get("actor"))
    author_id = _text(actor.get("id")) or _text(actor.get("email"))
    if not author_id:
        return None

    issue_id = _text(data.get("id"))
    if not issue_id:
        return None

    return ReworkSignal(
        event_id=_text(payload.get("webhookId")) or _text(payload.get("id")) or f"{issue_id}:{from_state}:{to_state}:{_text(payload.get('createdAt'))}",
        issue_id=issue_id,
        issue_identifier=_text(data.get("identifier")),
        author_id=author_id,
        author_email=_text(actor.get("email")),
        from_state=from_state,
        to_state=to_state,
        occurred_at=_text(payload.get("createdAt")) or _text(data.get("updatedAt")) or _text(data.get("createdAt")) or "",
    )


def _state_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _text(value.get("name") or value.get("type"))
    return _text(value)


def _state_rank(value: str) -> int:
    return _STATE_RANKS.get(value.strip().lower(), -1)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
