"""Classify Linear status transitions into normalized rework signals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


REWORK_STATUS_RULE = "status_entered_rework"
DONE_TO_NON_DONE_RULE = "done_to_non_done_within_7_days"
REOPENED_ACTION_RULE = "reopened_action"

HIGH_CONFIDENCE = "high"
MEDIUM_CONFIDENCE = "medium"
DONE_REOPEN_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class ReworkSignal:
    """Normalized signal emitted by a rework classifier rule."""

    issue_id: str
    source_event_id: str
    rule_name: str
    confidence: str
    occurred_at: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


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


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
