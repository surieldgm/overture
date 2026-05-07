import unittest

from overture.rework_classifier import (
    DONE_TO_NON_DONE_RULE,
    HIGH_CONFIDENCE,
    MEDIUM_CONFIDENCE,
    REOPENED_ACTION_RULE,
    REWORK_STATUS_RULE,
    classify_rework_events,
    rework_signals_payload,
)


class ReworkClassifierTests(unittest.TestCase):
    def test_emits_when_ticket_enters_rework_status(self) -> None:
        signals = classify_rework_events(
            (
                _event(
                    "event-rework",
                    previous_status="Merging",
                    new_status="Rework",
                    timestamp="2026-05-07T18:00:00.000Z",
                ),
            )
        )

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.source_event_id, "event-rework")
        self.assertEqual(signal.rule_name, REWORK_STATUS_RULE)
        self.assertEqual(signal.confidence, HIGH_CONFIDENCE)
        self.assertEqual(signal.issue_id, "issue-1")

    def test_emits_when_ticket_leaves_done_within_seven_days(self) -> None:
        signals = classify_rework_events(
            (
                _event(
                    "event-done",
                    previous_status="Merging",
                    new_status="Done",
                    timestamp="2026-05-01T18:00:00.000Z",
                ),
                _event(
                    "event-out-of-done",
                    previous_status="Done",
                    new_status="In Progress",
                    timestamp="2026-05-06T18:00:00.000Z",
                ),
            )
        )

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.source_event_id, "event-out-of-done")
        self.assertEqual(signal.rule_name, DONE_TO_NON_DONE_RULE)
        self.assertEqual(signal.confidence, MEDIUM_CONFIDENCE)

    def test_does_not_emit_for_normal_forward_progress(self) -> None:
        signals = classify_rework_events(
            (
                _event("event-todo", previous_status="Backlog", new_status="Todo", timestamp="2026-05-01T18:00:00.000Z"),
                _event("event-progress", previous_status="Todo", new_status="In Progress", timestamp="2026-05-02T18:00:00.000Z"),
                _event("event-merging", previous_status="In Progress", new_status="Merging", timestamp="2026-05-03T18:00:00.000Z"),
                _event("event-done", previous_status="Merging", new_status="Done", timestamp="2026-05-04T18:00:00.000Z"),
            )
        )

        self.assertEqual(signals, ())

    def test_reopened_followup_surfaces_with_medium_confidence(self) -> None:
        signals = classify_rework_events(
            (
                _event(
                    "event-followup-reopen",
                    previous_status="Done",
                    new_status="Todo",
                    timestamp="2026-05-20T18:00:00.000Z",
                    raw_event={"action": "reopened", "reason": "legitimate follow-up"},
                ),
            )
        )

        self.assertEqual(len(signals), 2)
        by_rule = {signal.rule_name: signal for signal in signals}
        self.assertEqual(by_rule[REOPENED_ACTION_RULE].source_event_id, "event-followup-reopen")
        self.assertEqual(by_rule[REOPENED_ACTION_RULE].confidence, MEDIUM_CONFIDENCE)
        self.assertEqual(by_rule[DONE_TO_NON_DONE_RULE].confidence, MEDIUM_CONFIDENCE)

    def test_does_not_emit_when_leaving_done_after_window_with_known_done_time(self) -> None:
        signals = classify_rework_events(
            (
                _event(
                    "event-done",
                    previous_status="Merging",
                    new_status="Done",
                    timestamp="2026-05-01T18:00:00.000Z",
                ),
                _event(
                    "event-old-reopen",
                    previous_status="Done",
                    new_status="Todo",
                    timestamp="2026-05-20T18:00:00.000Z",
                ),
            )
        )

        self.assertEqual(signals, ())

    def test_payload_contains_source_event_id_and_rule_name(self) -> None:
        payload = rework_signals_payload(
            (
                _event(
                    "event-rework",
                    previous_status="Merging",
                    new_status="Rework",
                    timestamp="2026-05-07T18:00:00.000Z",
                ),
            )
        )

        self.assertEqual(payload[0]["source_event_id"], "event-rework")
        self.assertEqual(payload[0]["rule_name"], REWORK_STATUS_RULE)


def _event(
    event_id: str,
    *,
    previous_status: str,
    new_status: str,
    timestamp: str,
    raw_event: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "issue_id": "issue-1",
        "previous_status": previous_status,
        "new_status": new_status,
        "actor": {"id": "user-1"},
        "raw_event": raw_event or {"action": "update"},
        "received_at": timestamp,
    }


if __name__ == "__main__":
    unittest.main()
