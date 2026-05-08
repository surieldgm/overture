import io
import json
import tempfile
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import urlencode

from overture.auth import AUTH_COOKIE_NAME
from overture.intake import create_intake_record
from overture.ui_host import (
    RESEARCH_APPROVAL_ROUTE,
    RESEARCH_COMPLETE_ROUTE,
    SESSION_COOKIE_NAME,
    SYNTHESIS_ROUTE,
    TICKET_REVIEW_ROUTE,
    OvertureUiApp,
)


TECHNICAL_ERROR_STRINGS = (
    "Research result not found",
    "No synthesis brief is stored in this session",
)


class WizardSkipStepSmokeTests(unittest.TestCase):
    def test_skip_step_paths_render_guidance_without_persona_report_technical_errors(self) -> None:
        """Validate persona report findings #6, #12, and #13 stay fixed on premature wizard visits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            intake, _path = create_intake_record(
                "Validate wizard skip-step guidance",
                Path(tmpdir) / "intake",
                author_email="designer@example.com",
            )
            intake_cookie = _session_cookie({"intake_id": intake.id, "author_email": "designer@example.com"})

            synthesis = _request(app, "GET", SYNTHESIS_ROUTE, cookie=intake_cookie)
            self.assertEqual(synthesis.status, "200 OK")
            self.assertIn("Complete research approval first", synthesis.body)
            self.assertIn(f'href="{RESEARCH_APPROVAL_ROUTE}"', synthesis.body)
            self.assertIn("Go to research approval", synthesis.body)
            _assert_technical_errors_absent(self, synthesis.body)

            ticket = _request(app, "GET", TICKET_REVIEW_ROUTE, cookie=intake_cookie)
            self.assertEqual(ticket.status, "200 OK")
            self.assertIn("Complete synthesis review first", ticket.body)
            self.assertIn(f'href="{SYNTHESIS_ROUTE}"', ticket.body)
            self.assertIn("Go to synthesis", ticket.body)
            _assert_technical_errors_absent(self, ticket.body)

            research_cookie = _session_cookie(
                {
                    "intake_id": intake.id,
                    "author_email": "designer@example.com",
                    "research_id": intake.id,
                    "research_result": json.dumps(
                        {
                            "intake_id": intake.id,
                            "items": [
                                {
                                    "title": "Wizard skip-step guidance",
                                    "url": "https://example.test/wizard-skip-guidance",
                                    "summary": "Guidance should replace technical errors on premature visits.",
                                    "evidence_claims": [],
                                    "inference_claims": [],
                                }
                            ],
                            "errors": [],
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
            research_complete = _request(app, "GET", RESEARCH_COMPLETE_ROUTE, cookie=research_cookie)
            self.assertEqual(research_complete.status, "200 OK")
            self.assertIn("Continue to synthesis", research_complete.body)
            self.assertIn(f'href="{SYNTHESIS_ROUTE}"', research_complete.body)
            _assert_technical_errors_absent(self, research_complete.body)

            top_nav_ticket = _request(
                app,
                "GET",
                TICKET_REVIEW_ROUTE,
                cookie=research_complete.headers["Set-Cookie"],
            )
            self.assertEqual(top_nav_ticket.status, "200 OK")
            self.assertIn("Complete synthesis review first", top_nav_ticket.body)
            self.assertIn(f'href="{SYNTHESIS_ROUTE}"', top_nav_ticket.body)
            _assert_technical_errors_absent(self, top_nav_ticket.body)


def _assert_technical_errors_absent(test: unittest.TestCase, body: str) -> None:
    for message in TECHNICAL_ERROR_STRINGS:
        test.assertNotIn(message, body)


def _request(
    app: OvertureUiApp,
    method: str,
    path: str,
    fields: dict[str, str] | None = None,
    *,
    cookie: str | None = None,
) -> "_Response":
    encoded = urlencode(fields or {}, doseq=True).encode("utf-8")
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    request_cookie = _merge_cookie(cookie, AUTH_COOKIE_NAME, app.auth_manager.issue_session("designer@example.com"))
    environ: dict[str, object] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(encoded)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "HTTP_COOKIE": request_cookie,
        "wsgi.input": io.BytesIO(encoded),
    }
    body = b"".join(app(environ, start_response)).decode("utf-8")
    return _Response(str(captured["status"]), list(captured["headers"]), body)


def _session_cookie(session: dict[str, str]) -> str:
    jar = cookies.SimpleCookie()
    jar[SESSION_COOKIE_NAME] = json.dumps(session, sort_keys=True, separators=(",", ":"))
    return jar.output(header="").strip()


def _merge_cookie(cookie_header: str | None, name: str, value: str) -> str:
    jar = cookies.SimpleCookie()
    if cookie_header:
        jar.load(cookie_header)
    if name not in jar:
        jar[name] = value
    return jar.output(header="").strip()


class _Response:
    def __init__(self, status: str, headers: list[tuple[str, str]], body: str) -> None:
        self.status = status
        self.all_headers = headers
        self.headers = dict(headers)
        self.body = body

