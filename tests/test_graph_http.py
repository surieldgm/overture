import hashlib
import hmac
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from overture.fixture import run_overture_fixture
from overture.graph import GraphRecord
from overture.graph_http import GraphHttpClient, create_graph_http_server, migrate_graph_store
from overture.graph_store import SqliteGraphStore


class GraphHttpTests(unittest.TestCase):
    def test_http_read_write_for_nodes_edges_claims_and_evidence(self) -> None:
        with _running_server() as server:
            base_url = server.base_url

            _post_json(base_url, "/nodes", {"id": "idea_shared", "kind": "Idea", "summary": "Shared context"})
            _post_json(base_url, "/claims", {"id": "claim_shared", "statement": "Claims are shared"})
            _post_json(base_url, "/evidence", {"id": "evidence_shared", "summary": "Evidence is shared"})
            _post_json(base_url, "/edges", {"from": "evidence_shared", "to": "claim_shared", "kind": "supports"})

            nodes = _get_json(base_url, "/nodes")["nodes"]
            claims = _get_json(base_url, "/claims")["claims"]
            evidence = _get_json(base_url, "/evidence")["evidence"]
            edges = _get_json(base_url, "/edges")["edges"]
            context = _get_json(base_url, "/context?limit=10")["context"]

            self.assertEqual({node["id"] for node in nodes}, {"idea_shared", "claim_shared", "evidence_shared"})
            self.assertEqual([claim["id"] for claim in claims], ["claim_shared"])
            self.assertEqual([item["id"] for item in evidence], ["evidence_shared"])
            self.assertEqual([(edge["from"], edge["to"], edge["kind"]) for edge in edges], [("evidence_shared", "claim_shared", "supports")])
            self.assertEqual(len(context["nodes"]), 3)
            self.assertEqual(len(context["edges"]), 1)

    def test_fixture_can_write_to_http_graph_store(self) -> None:
        with TemporaryDirectory() as tmpdir, _running_server(Path(tmpdir) / "shared.sqlite") as server:
            artifacts = run_overture_fixture(
                Path(tmpdir) / "fixture",
                graph_store_base_path=server.base_url,
                quiet_progress=True,
            )

            self.assertTrue(Path(str(artifacts["graph"])).exists())
            counts = GraphHttpClient(server.base_url).table_counts()
            self.assertGreater(counts["nodes"], 0)
            self.assertGreater(counts["edges"], 0)

    def test_migration_imports_existing_local_store(self) -> None:
        with TemporaryDirectory() as tmpdir, _running_server(Path(tmpdir) / "target.sqlite") as server:
            source_db = Path(tmpdir) / "source.sqlite"
            store = SqliteGraphStore(source_db)
            store.upsert_record(GraphRecord(kind="Evidence", key="evidence_local", properties={"summary": "Local"}))
            store.upsert_record(GraphRecord(kind="Claim", key="claim_local", properties={"statement": "Migrated"}))
            store.upsert_record(GraphRecord(kind="supports", key="evidence_local:supports:claim_local", properties={"from": "evidence_local", "to": "claim_local"}))

            result = migrate_graph_store(source_db, server.base_url)

            self.assertEqual(result["source_records"], 3)
            self.assertEqual(result["accepted"], 3)
            self.assertEqual(result["target_nodes"], 2)
            self.assertEqual(result["target_edges"], 1)

    def test_concurrent_writers_do_not_lose_rows(self) -> None:
        with _running_server() as server:
            base_url = server.base_url

            def write_records(client_id: int) -> None:
                client = GraphHttpClient(base_url)
                for index in range(50):
                    client.upsert_record(
                        GraphRecord(
                            kind="Evidence",
                            key=f"evidence_{client_id}_{index}",
                            properties={"summary": f"client {client_id} item {index}"},
                        )
                    )

            with ThreadPoolExecutor(max_workers=2) as executor:
                list(executor.map(write_records, (1, 2)))

            counts = GraphHttpClient(base_url).table_counts()
            self.assertEqual(counts["nodes"], 100)
            self.assertEqual(counts["edges"], 0)

            with sqlite3.connect(server.db_path) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM nodes").fetchone()[0], 100)

    def test_linear_webhook_rejects_missing_signature(self) -> None:
        with _running_server(linear_webhook_secret="secret") as server:
            with self.assertRaises(HTTPError) as raised:
                _post_json(server.base_url, "/linear/webhook", _linear_issue_payload())

            self.assertEqual(raised.exception.code, 401)
            events = _get_json(server.base_url, "/linear/webhook/events")["events"]
            self.assertEqual(events, [])

    def test_linear_webhook_rejects_wrong_signature(self) -> None:
        with _running_server(linear_webhook_secret="secret") as server:
            with self.assertRaises(HTTPError) as raised:
                _post_linear_webhook(server.base_url, _linear_issue_payload(), signature="bad")

            self.assertEqual(raised.exception.code, 401)
            events = _get_json(server.base_url, "/linear/webhook/events")["events"]
            self.assertEqual(events, [])

    def test_linear_webhook_accepts_signature_and_persists_normalized_shape(self) -> None:
        with _running_server(linear_webhook_secret="secret") as server:
            response = _post_linear_webhook(server.base_url, _linear_issue_payload(), secret="secret")

            self.assertEqual(response, {"accepted": 1, "duplicate": False})
            events = _get_json(server.base_url, "/linear/webhook/events")["events"]
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event["event_id"], "delivery-1")
            self.assertEqual(event["timestamp"], "2026-05-07T18:00:00.000Z")
            self.assertEqual(event["issue_id"], "issue-1")
            self.assertEqual(event["previous_status"], "Todo")
            self.assertEqual(event["new_status"], "In Progress")
            self.assertEqual(event["actor"]["id"], "user-1")
            self.assertEqual(event["actor"]["name"], "Designer")
            self.assertEqual(event["raw_event"]["action"], "update")

    def test_linear_webhook_deduplicates_retries_without_raising(self) -> None:
        with _running_server(linear_webhook_secret="secret") as server:
            first = _post_linear_webhook(server.base_url, _linear_issue_payload(), secret="secret")
            second = _post_linear_webhook(
                server.base_url,
                _linear_issue_payload(delivery_id="delivery-retry"),
                secret="secret",
                delivery_id="delivery-retry",
            )

            self.assertEqual(first, {"accepted": 1, "duplicate": False})
            self.assertEqual(second, {"accepted": 0, "duplicate": True})
            events = _get_json(server.base_url, "/linear/webhook/events")["events"]
            self.assertEqual(len(events), 1)

    def test_linear_rework_signals_classify_persisted_webhook_events(self) -> None:
        with _running_server(linear_webhook_secret="secret") as server:
            _post_linear_webhook(
                server.base_url,
                _linear_issue_payload(
                    delivery_id="delivery-done",
                    previous_status="Merging",
                    new_status="Done",
                    created_at="2026-05-01T18:00:00.000Z",
                ),
                secret="secret",
                delivery_id="delivery-done",
            )
            _post_linear_webhook(
                server.base_url,
                _linear_issue_payload(
                    delivery_id="delivery-rework",
                    previous_status="Done",
                    new_status="Rework",
                    created_at="2026-05-03T18:00:00.000Z",
                ),
                secret="secret",
                delivery_id="delivery-rework",
            )

            signals = _get_json(server.base_url, "/linear/rework-signals")["signals"]

            self.assertEqual({signal["rule_name"] for signal in signals}, {"done_to_non_done_within_7_days", "status_entered_rework"})
            self.assertEqual({signal["source_event_id"] for signal in signals}, {"delivery-rework"})


class _running_server:
    def __init__(self, db_path: Path | None = None, *, linear_webhook_secret: str | None = None) -> None:
        self._tempdir: TemporaryDirectory[str] | None = None
        if db_path is None:
            self._tempdir = TemporaryDirectory()
            db_path = Path(self._tempdir.name) / "graph.sqlite"
        self.db_path = db_path
        self._server = create_graph_http_server(db_path, port=0, linear_webhook_secret=linear_webhook_secret)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"

    def __enter__(self) -> "_running_server":
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()
        if self._tempdir is not None:
            self._tempdir.cleanup()


def _post_json(base_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_linear_webhook(
    base_url: str,
    payload: dict[str, object],
    *,
    secret: str | None = None,
    signature: str | None = None,
    delivery_id: str = "delivery-1",
) -> dict[str, object]:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    if signature is None:
        if secret is None:
            raise ValueError("secret or signature is required")
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    request = Request(
        f"{base_url}/linear/webhook",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Linear-Delivery": delivery_id,
            "Linear-Event": "Issue",
            "Linear-Signature": signature,
        },
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(base_url: str, path: str) -> dict[str, object]:
    with urlopen(f"{base_url}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _linear_issue_payload(
    *,
    delivery_id: str = "delivery-1",
    previous_status: str = "Todo",
    new_status: str = "In Progress",
    created_at: str = "2026-05-07T18:00:00.000Z",
) -> dict[str, object]:
    return {
        "action": "update",
        "createdAt": created_at,
        "data": {
            "id": "issue-1",
            "identifier": "ERI-65",
            "state": {"id": "state-new", "name": new_status},
        },
        "updatedFrom": {"state": {"id": "state-previous", "name": previous_status}},
        "actor": {"id": "user-1", "name": "Designer"},
        "webhookTimestamp": 1778176800000,
        "id": delivery_id,
    }


if __name__ == "__main__":
    unittest.main()
