import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.request import Request, urlopen

from overture.linear_webhook_receiver import create_linear_webhook_receiver
from overture.metrics_store import MetricsStore


class ReworkWebhookSmokeTests(unittest.TestCase):
    def test_linear_webhook_rework_chain_counts_per_author_without_false_positives(self) -> None:
        with TemporaryDirectory() as tmpdir, _running_receiver(Path(tmpdir) / "metrics.sqlite") as receiver:
            events = [
                _linear_issue_event(
                    "evt-forward-a",
                    author_id="designer-1",
                    author_email="designer-1@example.test",
                    issue_id="issue-a",
                    issue_identifier="ERI-101",
                    from_state="Todo",
                    to_state="In Progress",
                ),
                _linear_issue_event(
                    "evt-rework-a",
                    author_id="designer-1",
                    author_email="designer-1@example.test",
                    issue_id="issue-a",
                    issue_identifier="ERI-101",
                    from_state="Human Review",
                    to_state="In Progress",
                ),
                _linear_issue_event(
                    "evt-rework-b",
                    author_id="designer-2",
                    author_email="designer-2@example.test",
                    issue_id="issue-b",
                    issue_identifier="ERI-102",
                    from_state="Done",
                    to_state="Todo",
                ),
                _linear_issue_event(
                    "evt-forward-b",
                    author_id="designer-2",
                    author_email="designer-2@example.test",
                    issue_id="issue-b",
                    issue_identifier="ERI-102",
                    from_state="Todo",
                    to_state="Human Review",
                ),
                {
                    "webhookId": "evt-comment",
                    "type": "Comment",
                    "action": "create",
                    "actor": {"id": "designer-1", "email": "designer-1@example.test"},
                    "data": {"id": "comment-a"},
                },
            ]

            responses = [_post_json(receiver.base_url, "/linear/webhook", event) for event in events]

            self.assertEqual([response["rework_counted"] for response in responses], [False, True, True, False, False])
            store = MetricsStore(receiver.metrics_db_path)
            self.assertEqual(store.rework_counts_by_author(), {"designer-1": 1, "designer-2": 1})
            rows = list(store.iter_rework_metrics())
            self.assertEqual([(row.event_id, row.issue_identifier, row.from_state, row.to_state) for row in rows], [
                ("evt-rework-a", "ERI-101", "Human Review", "In Progress"),
                ("evt-rework-b", "ERI-102", "Done", "Todo"),
            ])


class _running_receiver:
    def __init__(self, metrics_db_path: Path) -> None:
        self.metrics_db_path = metrics_db_path
        self._server = create_linear_webhook_receiver(metrics_db_path, port=0)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"

    def __enter__(self) -> "_running_receiver":
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()


def _linear_issue_event(
    event_id: str,
    *,
    author_id: str,
    author_email: str,
    issue_id: str,
    issue_identifier: str,
    from_state: str,
    to_state: str,
) -> dict[str, object]:
    return {
        "webhookId": event_id,
        "type": "Issue",
        "action": "update",
        "createdAt": f"2026-05-07T14:00:{len(event_id):02d}.000000Z",
        "actor": {"id": author_id, "email": author_email},
        "data": {
            "id": issue_id,
            "identifier": issue_identifier,
            "state": {"name": to_state},
            "updatedAt": f"2026-05-07T14:00:{len(event_id):02d}.000000Z",
        },
        "updatedFrom": {"state": {"name": from_state}},
    }


def _post_json(base_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
