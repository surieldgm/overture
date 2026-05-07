import http.client
from http import cookies
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlparse

from overture.auth import AUTH_COOKIE_NAME, MagicLinkAuth
from overture.graph_store import SqliteGraphStore
from overture.peer_onboarding import (
    DESIGNER_ONE_AUTHOR_ID,
    FILLED_ARTIFACT_NODE_ID,
    INTAKE_STAGE_NODE_ID,
    PEER_ONBOARDING_ROUTE,
    TEMPLATE_NODE_ID,
    designer_one_peer_onboarding_artifact,
    load_designer_one_peer_onboarding_artifact,
    seed_designer_one_peer_onboarding_artifact,
    ordered_peer_onboarding_sections,
    validate_designer_one_peer_onboarding_artifact,
)
from overture.ui_host import build_ui_server


TEST_AUTH = MagicLinkAuth(secret="peer-onboarding-test")


class PeerOnboardingSmokeTests(unittest.TestCase):
    def test_filled_artifact_content_is_non_empty_and_links_original_intakes(self) -> None:
        artifact = designer_one_peer_onboarding_artifact()
        errors = validate_designer_one_peer_onboarding_artifact(artifact)

        self.assertEqual(errors, [])
        self.assertEqual(artifact.author_id, DESIGNER_ONE_AUTHOR_ID)
        self.assertGreaterEqual(len(artifact.intake_examples), 3)
        self.assertTrue(all(Path(example["href"]).exists() for example in artifact.intake_examples))
        self.assertTrue(all(section.get("title") for section in ordered_peer_onboarding_sections(artifact.template)))
        for section in ordered_peer_onboarding_sections(artifact.template):
            for field in section["fields"]:
                self.assertTrue(field["value"], f"empty field: {section['id']}.{field['id']}")

    def test_filled_artifact_is_stored_as_graph_node_with_provenance_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SqliteGraphStore(Path(tmpdir) / "graph.sqlite")
            artifact = seed_designer_one_peer_onboarding_artifact(store)
            loaded = load_designer_one_peer_onboarding_artifact(store)

            self.assertEqual(artifact.id, FILLED_ARTIFACT_NODE_ID)
            self.assertEqual(loaded.template_id, TEMPLATE_NODE_ID)
            nodes = {node["id"]: node for node in store.list_nodes()}
            edges = {(edge["from"], edge["kind"], edge["to"]) for edge in store.list_edges()}

        self.assertIn(FILLED_ARTIFACT_NODE_ID, nodes)
        self.assertEqual(nodes[FILLED_ARTIFACT_NODE_ID]["author_id"], DESIGNER_ONE_AUTHOR_ID)
        self.assertIn((FILLED_ARTIFACT_NODE_ID, "instantiates", TEMPLATE_NODE_ID), edges)
        self.assertIn((FILLED_ARTIFACT_NODE_ID, "embeds", INTAKE_STAGE_NODE_ID), edges)

    def test_authenticated_viewer_route_renders_designer_one_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, _running_server(Path(tmpdir)) as base_url:
            response = _get(base_url, PEER_ONBOARDING_ROUTE)

        self.assertEqual(response.status, 200)
        self.assertIn("Designer #1 peer onboarding artifact", response.body)
        self.assertIn("designer_1", response.body)
        self.assertIn("component_peer_onboarding_template", response.body)
        self.assertIn("examples/intake_examples/feature-idea-persistence.md", response.body)
        self.assertIn("examples/intake_examples/bug-research-approval-latency.md", response.body)
        self.assertIn("examples/intake_examples/integration-linear-export-dry-run.md", response.body)


class _running_server:
    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir

    def __enter__(self) -> str:
        self.server = build_ui_server(port=0, store_dir=self.store_dir, auth_manager=TEST_AUTH)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


def _get(base_url: str, path: str) -> "_Response":
    parsed = urlparse(base_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        token = TEST_AUTH.issue_session("designer2@example.com")
        jar = cookies.SimpleCookie()
        jar[AUTH_COOKIE_NAME] = token
        connection.request("GET", path, headers={"Cookie": jar.output(header="").strip()})
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        return _Response(status=response.status, body=body)
    finally:
        connection.close()


class _Response:
    def __init__(self, *, status: int, body: str) -> None:
        self.status = status
        self.body = body


if __name__ == "__main__":
    unittest.main()
