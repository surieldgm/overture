"""Classify Linear events into normalized rework signals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


REWORK_STATUS_RULE = "status_entered_rework"
DONE_TO_NON_DONE_RULE = "done_to_non_done_within_7_days"
REOPENED_ACTION_RULE = "reopened_action"
BACKWARD_STATE_RULE = "backward_state_transition"

HIGH_CONFIDENCE = "high"
MEDIUM_CONFIDENCE = "medium"
DONE_REOPEN_WINDOW = timedelta(days=7)

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
    """Normalized signal emitted by a rework classifier rule."""

    issue_id: str
    source_event_id: str
    rule_name: str
    confidence: str
    occurred_at: str
    issue_identifier: str | None = None
    author_id: str | None = None
    author_email: str | None = None
    from_state: str | None = None
    to_state: str | None = None

    @property
    def event_id(self) -> str:
        return self.source_event_id

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def classify_linear_webhook(payload: Mapping[str, Any]) -> ReworkSignal | None:
    """Return a rework signal when a Linear issue webhook moves backward."""

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

    source_event_id = (
        _text(payload.get("webhookId"))
        or _text(payload.get("id"))
        or f"{issue_id}:{from_state}:{to_state}:{_text(payload.get('createdAt'))}"
    )
    return ReworkSignal(
        issue_id=issue_id,
        source_event_id=source_event_id,
        rule_name=BACKWARD_STATE_RULE,
        confidence=HIGH_CONFIDENCE,
        occurred_at=_text(payload.get("createdAt")) or _text(data.get("updatedAt")) or _text(data.get("createdAt")) or "",
        issue_identifier=_text(data.get("identifier")),
        author_id=author_id,
        author_email=_text(actor.get("email")),
        from_state=from_state,
        to_state=to_state,
    )


def classify_rework_events(events: Iterable[Mapping[str, Any]]) -> tuple[ReworkSignal, ...]:
    """Classify normalized Linear webhook events into rework signals."""

    sorted_events = sorted(events, key=_event_sort_key)
    last_done_by_issue: dict[str, datetime] = {}
    signals: list[ReworkSignal] = []

    for event in sorted_events:
        issue_id = _required_text(event, "issue_id")
        source_event_id = _required_text(event, "event_id")
        occurred_at = _required_text(event, "timestamp")
        occurred_dt = _parse_timestamp(occurred_at)
        previous_status = _canonical_status(event.get("previous_status"))
        new_status = _canonical_status(event.get("new_status"))

        if _is_reopened_action(event):
            signals.append(
                ReworkSignal(
                    issue_id=issue_id,
                    source_event_id=source_event_id,
                    rule_name=REOPENED_ACTION_RULE,
                    confidence=MEDIUM_CONFIDENCE,
                    occurred_at=occurred_at,
                )
            )

        if new_status == "rework":
            signals.append(
                ReworkSignal(
                    issue_id=issue_id,
                    source_event_id=source_event_id,
                    rule_name=REWORK_STATUS_RULE,
                    confidence=HIGH_CONFIDENCE,
                    occurred_at=occurred_at,
                )
            )

        if previous_status == "done" and new_status != "done":
            done_at = last_done_by_issue.get(issue_id)
            if done_at is None or occurred_dt - done_at <= DONE_REOPEN_WINDOW:
                signals.append(
                    ReworkSignal(
                        issue_id=issue_id,
                        source_event_id=source_event_id,
                        rule_name=DONE_TO_NON_DONE_RULE,
                        confidence=MEDIUM_CONFIDENCE,
                        occurred_at=occurred_at,
                    )
                )

        if new_status == "done":
            last_done_by_issue[issue_id] = occurred_dt

    return tuple(signals)


def rework_signals_payload(events: Iterable[Mapping[str, Any]]) -> tuple[dict[str, str], ...]:
    """Return classifier output in JSON-serializable form."""

    return tuple(signal.to_dict() for signal in classify_rework_events(events))


def _event_sort_key(event: Mapping[str, Any]) -> tuple[datetime, str]:
    timestamp = _parse_timestamp(_required_text(event, "timestamp"))
    return (timestamp, str(event.get("event_id") or ""))


def _required_text(event: Mapping[str, Any], field: str) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Linear transition event requires {field}")
    return value


def _canonical_status(value: object) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def _is_reopened_action(event: Mapping[str, Any]) -> bool:
    raw_event = event.get("raw_event")
    if not isinstance(raw_event, Mapping):
        return False
    action = str(raw_event.get("action") or "").strip().lower().replace("_", "-")
    return action in {"reopen", "reopened"}


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


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
