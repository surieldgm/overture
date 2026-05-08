import io
import json
import tempfile
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from overture.auth import AUTH_COOKIE_NAME
from overture.graph_store import SqliteGraphStore
from overture.peer_onboarding import (
    DESIGNER_ONE_AUTHOR_EMAIL,
    load_latest_peer_onboarding_artifact,
    ordered_peer_onboarding_sections,
)
from overture.ui_host import (
    OvertureUiApp,
    PEER_ONBOARDING_EDITOR_ROUTE,
    PEER_ONBOARDING_ROUTE,
)
from tests.test_ui_peer_onboarding_page import _peer_onboarding_editor_payload


class DesignerOneAuthoringSmokeTests(unittest.TestCase):
    def test_designer_one_magic_link_authoring_path_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)

            sent = _request(
                app,
                "POST",
                "/auth/magic-link",
                {"email": DESIGNER_ONE_AUTHOR_EMAIL},
                authenticated=False,
            )
            self.assertEqual(sent.status, "200 OK")
            self.assertIn("Open the magic link locally", sent.body)

            outbox_path = Path(tmpdir) / "magic-links.jsonl"
            self.assertTrue(outbox_path.exists(), outbox_path)
            payload = json.loads(outbox_path.read_text(encoding="utf-8").splitlines()[-1])
            link = urlparse(str(payload["link"]))
            self.assertEqual(link.scheme, "http")
            self.assertIn("localhost", link.hostname or "")
            self.assertEqual(link.path, "/auth/consume")

            consumed = _request(app, "GET", f"{link.path}?{link.query}", authenticated=False)
            self.assertEqual(consumed.status, "200 OK")
            self.assertIn(AUTH_COOKIE_NAME, consumed.headers["Set-Cookie"])

            session_cookie = consumed.headers["Set-Cookie"]
            viewer = _request(app, "GET", PEER_ONBOARDING_ROUTE, cookie=session_cookie, authenticated=False)
            self.assertEqual(viewer.status, "200 OK")
            self.assertIn("Edit this artifact", viewer.body)

            edit_page = _request(
                app,
                "GET",
                PEER_ONBOARDING_EDITOR_ROUTE,
                cookie=session_cookie,
                authenticated=False,
            )
            self.assertEqual(edit_page.status, "200 OK")
            self.assertIn("Edit peer onboarding artifact", edit_page.body)

            artifact = load_latest_peer_onboarding_artifact(SqliteGraphStore(Path(tmpdir) / "graph.sqlite"))
            section_ids = {str(section.get("id", "")) for section in ordered_peer_onboarding_sections(artifact.template)}
            payload_overrides = {
                "intake_worked.summary": "Designer #1 keeps an intake summary with explicit constraints.",
                "intake_worked.example_prompts": "\n".join(
                    (
                        "Prompt A: Capture the full context before editing.",
                        "Prompt B: Preserve raw wording in the handoff.",
                    )
                ),
                "research_approval.approval_summary": "Designer #1 now requires sources with explicit quality checks.",
                "research_approval.approved_source_traits": "\n".join(
                    (
                        "source quality over novelty",
                        "cross-check examples in intake history",
                    )
                ),
                "wizard_watchouts.step_notes.0": "Keep initial raw wording visible before summarization.",
                "wizard_watchouts.step_notes.1": "Pause before final source gating decision.",
                "wizard_watchouts.step_notes.2": "Keep brief but complete candidate hypotheses visible.",
                "wizard_watchouts.step_notes.3": "Avoid silent truncation of accepted ticket drafts.",
                "wizard_watchouts.step_notes.4": "Run export validation before handoff.",
                "sprint5_observation_patterns.pattern_summary": "Keep explicit friction traces in context for handoff quality.",
                "sprint5_observation_patterns.handoff_adjustments": "\n".join(
                    (
                        "Shorten mandatory fields where possible.",
                        "Expose a one-click verify action in editor.",
                    )
                ),
            }
            payload = _peer_onboarding_editor_payload(artifact, payload_overrides)

            for section_id in section_ids:
                self.assertTrue(any(key.startswith(f"{section_id}.") for key in payload), f"missing payload for section {section_id}")

            saved = _request(
                app,
                "POST",
                PEER_ONBOARDING_EDITOR_ROUTE,
                payload,
                cookie=session_cookie,
                authenticated=False,
            )
            self.assertEqual(saved.status, "303 See Other")
            self.assertTrue(saved.headers["Location"].startswith(f"{PEER_ONBOARDING_ROUTE}?saved=1&"))
            self.assertIn("ts=", saved.headers["Location"])
            query = parse_qs(urlparse(saved.headers["Location"]).query)
            saved_timestamp = query.get("ts", [""])[0]
            self.assertTrue(saved_timestamp)

            updated = _request(app, "GET", saved.headers["Location"], cookie=session_cookie, authenticated=False)
            self.assertEqual(updated.status, "200 OK")
            self.assertIn("Saved successfully at", updated.body)
            self.assertIn(f"<time>{saved_timestamp}</time>", updated.body)
            self.assertIn("Designer #1 keeps an intake summary with explicit constraints.", updated.body)
            self.assertIn("Prompt A: Capture the full context before editing.", updated.body)
            self.assertIn("source quality over novelty", updated.body)
            self.assertIn("Keep initial raw wording visible before summarization.", updated.body)
            self.assertIn("Shorten mandatory fields where possible.", updated.body)


class Response:
    def __init__(self, status: str, headers: list[tuple[str, str]], body: str) -> None:
        self.status = status
        self.headers = dict(headers)
        self.body = body


def _request(
    app: OvertureUiApp,
    method: str,
    path: str,
    fields: dict[str, str] | None = None,
    *,
    cookie: str | None = None,
    authenticated: bool = True,
) -> Response:
    encoded = _encode_form(fields or {})
    captured: dict[str, object] = {}
    parsed = urlparse(path)

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    environ: dict[str, object] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": parsed.path,
        "QUERY_STRING": parsed.query,
        "CONTENT_LENGTH": str(len(encoded)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "wsgi.input": io.BytesIO(encoded),
    }

    request_cookie = cookie
    if authenticated and not request_cookie:
        request_cookie = _merge_cookie(request_cookie, AUTH_COOKIE_NAME, app.auth_manager.issue_session("designer@example.com"))
    if request_cookie:
        environ["HTTP_COOKIE"] = request_cookie

    body = b"".join(app(environ, start_response)).decode("utf-8")
    return Response(str(captured["status"]), list(captured["headers"]), body)


def _encode_form(fields: dict[str, str]) -> bytes:
    return urlencode(fields, doseq=True).encode("utf-8")


def _merge_cookie(cookie_header: str | None, name: str, value: str) -> str:
    jar = cookies.SimpleCookie()
    if cookie_header:
        jar.load(cookie_header)
    if name not in jar:
        jar[name] = value
    return jar.output(header="").strip()


if __name__ == "__main__":
    unittest.main()
