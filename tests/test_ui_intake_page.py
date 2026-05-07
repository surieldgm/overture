import io
import json
import tempfile
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import urlencode

from overture.intake import load_intake_record
from overture.ui_host import (
    INTAKE_TEXT_MAX_CHARS,
    RESEARCH_APPROVAL_ROUTE,
    SESSION_COOKIE_NAME,
    OvertureUiApp,
    session_from_environ,
)


class IntakePageTests(unittest.TestCase):
    def test_intake_page_renders_form_and_curated_examples_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", "/intake")

        self.assertEqual(response.status, "200 OK")
        self.assertIn('<textarea id="idea" name="idea"', response.body)
        self.assertIn("Start research approval", response.body)
        self.assertIn('href="/examples/intake_examples/"', response.body)
        self.assertIn(f"{INTAKE_TEXT_MAX_CHARS:,}", response.body)

    def test_non_empty_submit_creates_intake_persists_session_and_advances(self) -> None:
        idea = "Build a page that starts Overture without opening a terminal"
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            response = _request(app, "POST", "/intake", {"idea": idea})

            self.assertEqual(response.status, "303 See Other")
            self.assertEqual(response.headers["Location"], RESEARCH_APPROVAL_ROUTE)
            intake_files = list((Path(tmpdir) / "intake").glob("*.json"))
            self.assertEqual(len(intake_files), 1)
            record = load_intake_record(intake_files[0])
            self.assertEqual(record.raw_text, idea)
            self.assertEqual(record.source_type, "ui")

            cookie_header = response.headers["Set-Cookie"]
            session = _session_from_set_cookie(cookie_header)
            self.assertEqual(session["intake_id"], record.id)

            approval = _request(
                app,
                "GET",
                RESEARCH_APPROVAL_ROUTE,
                cookie=cookie_header,
            )
            self.assertEqual(approval.status, "200 OK")
            self.assertIn(record.id, approval.body)

    def test_empty_submit_shows_inline_validation_without_creating_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "POST", "/intake", {"idea": "   "})

            self.assertEqual(response.status, "400 Bad Request")
            self.assertIn("Enter an idea before continuing.", response.body)
            self.assertNotIn("Location", response.headers)
            self.assertEqual(list((Path(tmpdir) / "intake").glob("*.json")), [])

    def test_above_cap_submit_rejects_without_truncating_or_creating_record(self) -> None:
        idea = "x" * (INTAKE_TEXT_MAX_CHARS + 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "POST", "/intake", {"idea": idea})

            self.assertEqual(response.status, "400 Bad Request")
            self.assertIn(f"Idea text must be {INTAKE_TEXT_MAX_CHARS:,} characters or fewer.", response.body)
            self.assertIn(idea, response.body)
            self.assertEqual(list((Path(tmpdir) / "intake").glob("*.json")), [])

    def test_session_parser_recovers_intake_id(self) -> None:
        jar = cookies.SimpleCookie()
        jar[SESSION_COOKIE_NAME] = json.dumps({"intake_id": "idea_123"}, separators=(",", ":"))
        environ = {
            "HTTP_COOKIE": jar.output(header="").strip(),
        }

        self.assertEqual(session_from_environ(environ), {"intake_id": "idea_123"})


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
) -> Response:
    encoded = urlencode(fields or {}).encode("utf-8")
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    environ: dict[str, object] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(encoded)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "wsgi.input": io.BytesIO(encoded),
    }
    if cookie:
        environ["HTTP_COOKIE"] = cookie

    body = b"".join(app(environ, start_response)).decode("utf-8")
    return Response(str(captured["status"]), list(captured["headers"]), body)


def _session_from_set_cookie(header: str) -> dict[str, str]:
    jar = cookies.SimpleCookie()
    jar.load(header)
    return json.loads(jar[SESSION_COOKIE_NAME].value)


if __name__ == "__main__":
    unittest.main()
