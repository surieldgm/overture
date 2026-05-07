import re
import tempfile
import unittest
from pathlib import Path

from overture.auth import AuthenticatedUser
from overture.observation_log import ObservationLog


class ObservationLogTests(unittest.TestCase):
    def test_append_records_millisecond_timestamp_and_enforces_session_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = ObservationLog(
                Path(tmpdir) / "observation.sqlite",
                event_cap=2,
                now=lambda: "2026-05-07T23:59:01.123456Z",
            )
            actor = AuthenticatedUser(user_id="designer@example.test", email="designer@example.test")

            for index in range(3):
                log.append(
                    session_id="session-1",
                    event_type="page_transition",
                    route=f"/step-{index}",
                    action="view",
                    actor=actor,
                    request={"index": index},
                    response={"status": 200},
                )

            events = log.iter_session_events("session-1", user=actor)

        self.assertEqual([event.route for event in events], ["/step-1", "/step-2"])
        self.assertTrue(all(re.match(r"^2026-05-07T23:59:01\.123Z$", event.occurred_at) for event in events))

    def test_session_events_are_readable_by_author_and_founder_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = ObservationLog(Path(tmpdir) / "observation.sqlite")
            author = AuthenticatedUser(user_id="designer@example.test", email="designer@example.test")
            founder = AuthenticatedUser(user_id="founder@example.test", email="founder@example.test")
            other = AuthenticatedUser(user_id="other@example.test", email="other@example.test")

            log.append(
                session_id="session-1",
                event_type="form_submission",
                route="/intake",
                action="submit",
                actor=author,
                request={"fields": {"idea": "Captured input"}},
                response={"status": 303},
            )

            self.assertEqual(len(log.iter_session_events("session-1", user=author)), 1)
            self.assertEqual(len(log.iter_session_events("session-1", user=founder, founder_emails={"founder@example.test"})), 1)
            with self.assertRaises(PermissionError):
                log.iter_session_events("session-1", user=other, founder_emails={"founder@example.test"})


if __name__ == "__main__":
    unittest.main()
