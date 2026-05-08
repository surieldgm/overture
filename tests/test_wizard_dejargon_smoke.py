import http.client
import json
import re
import tempfile
import threading
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import urlencode, urlparse

from overture.auth import AUTH_COOKIE_NAME, MagicLinkAuth
from overture.ui_host import (
    RESEARCH_APPROVAL_ROUTE,
    SESSION_COOKIE_NAME,
    SYNTHESIS_ROUTE,
    TICKET_REVIEW_ROUTE,
    build_ui_server,
)

TEST_AUTH = MagicLinkAuth(secret="ui-wizard-dejargon-smoke")


class WizardDejargonReadabilitySmokeTests(unittest.TestCase):
    def test_dejargon_smoke_checks_three_persona_reading_targets(self) -> None:
        """Validate persona report findings #14, #15, and #17 from docs/user-tests/2026-05-07-personas.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with _running_server(store_dir=Path(tmpdir), llm_client=_stub_llm_client) as base_url:
                login = _get(base_url, "/auth/login")
                self.assertEqual(login.status, 200)
                self.assertIn("<h2>Sign in to Overture</h2>", login.body)
                self.assertNotIn("Designer sign in", login.body)

                magic_link = _post(
                    base_url,
                    "/auth/magic-link",
                    {"email": "designer@example.com"},
                )
                self.assertEqual(magic_link.status, 200)
                self.assertNotIn("Open development magic link", magic_link.body)
                details_index = magic_link.body.find("<details")
                default_render = magic_link.body[:details_index] if details_index != -1 else magic_link.body
                self.assertNotIn("Development outbox", default_render)
                self.assertNotIn("<details open", magic_link.body)

                research_cookie = _approved_research_cookie(base_url)
                synthesis = _get(base_url, SYNTHESIS_ROUTE, headers={"Cookie": research_cookie})
                self.assertEqual(synthesis.status, 200)
                synthesis_advance = _post(base_url, SYNTHESIS_ROUTE, {}, headers={"Cookie": synthesis.headers["Set-Cookie"]})
                self.assertEqual(synthesis_advance.status, 303)

                ticket = _get(base_url, TICKET_REVIEW_ROUTE, headers={"Cookie": synthesis_advance.headers["Set-Cookie"]})
                self.assertEqual(ticket.status, 200)
                self.assertNotIn("Ticket Markdown", ticket.body)

                intake = _get(base_url, "/intake", headers={"Cookie": synthesis_advance.headers["Set-Cookie"]})
                self.assertEqual(intake.status, 200)
                self.assertIn("your idea", intake.body.lower())

                for page, body in {
                    "sign_in": login.body,
                    "magic_link": magic_link.body,
                    "intake": intake.body,
                    "synthesis": synthesis.body,
                    "ticket": ticket.body,
                }.items():
                    _assert_disclosures_collapsed(self, page, body)


def _running_server(
    *,
    store_dir: Path,
    llm_client,
    linear_client_factory=None,
    auth_manager=None,
) -> "_ServerContext":
    return _ServerContext(
        store_dir=store_dir,
        llm_client=llm_client,
        linear_client_factory=linear_client_factory,
        auth_manager=auth_manager,
    )


class _ServerContext:
    def __init__(self, *, store_dir: Path, llm_client, linear_client_factory, auth_manager) -> None:
        self.store_dir = store_dir
        self.llm_client = llm_client
        self.linear_client_factory = linear_client_factory
        self.auth_manager = auth_manager or TEST_AUTH

    def __enter__(self) -> str:
        self.server = build_ui_server(
            port=0,
            store_dir=self.store_dir,
            llm_client=self.llm_client,
            linear_client_factory=self.linear_client_factory,
            auth_manager=self.auth_manager,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


def _get(base_url: str, path: str, *, headers: dict[str, str] | None = None) -> "_Response":
    return _request(base_url, "GET", path, headers=headers)


def _post(
    base_url: str,
    path: str,
    fields: dict[str, str],
    *,
    headers: dict[str, str] | None = None,
) -> "_Response":
    body = urlencode(fields)
    request_headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
    return _request(base_url, "POST", path, body=body, headers=request_headers)


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: str = "",
    headers: dict[str, str] | None = None,
) -> "_Response":
    parsed = urlparse(base_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    request_headers = dict(headers or {})
    if AUTH_COOKIE_NAME not in request_headers.get("Cookie", ""):
        auth_cookie = f"{AUTH_COOKIE_NAME}={TEST_AUTH.issue_session('designer-1@example.com')}"
        request_headers["Cookie"] = (
            f'{request_headers["Cookie"]}; {auth_cookie}'
            if request_headers.get("Cookie")
            else auth_cookie
        )
    connection.request(method, path, body=body, headers=request_headers)
    response = connection.getresponse()
    payload = response.read().decode("utf-8")
    response_headers = dict(response.getheaders())
    connection.close()
    return _Response(
        status=response.status,
        headers=response_headers,
        body=payload,
    )


def _approved_research_cookie(base_url: str) -> str:
    auth_cookie = f"{AUTH_COOKIE_NAME}={TEST_AUTH.issue_session('designer-1@example.com')}"
    intake = _post(base_url, "/intake", {"idea": "Validate de-jargoned wizard copy"}, headers={"Cookie": auth_cookie})
    intake_cookie = intake.headers.get("Set-Cookie", "")
    approval = _get(base_url, RESEARCH_APPROVAL_ROUTE, headers={"Cookie": f"{intake_cookie}; {auth_cookie}"})
    research = _post(
        base_url,
        RESEARCH_APPROVAL_ROUTE,
        {"decision-0": "approve:https://example.test/designer-synthesis"},
        headers={"Cookie": f'{approval.headers.get("Set-Cookie", "")}; {auth_cookie}'},
    )
    return research.headers.get("Set-Cookie", "")


def _assert_disclosures_collapsed(test: unittest.TestCase, page_name: str, body: str) -> None:
    for match in re.finditer(r"<details\\b[^>]*>", body):
        tag = match.group(0).lower()
        test.assertNotIn(" open", tag, msg=f"{page_name}: disclosure is expanded by default")


def _stub_llm_client(_prompt: str) -> str:
    return json.dumps(
        [
            {
                "title": "Designer synthesis workflow",
                "url": "https://example.test/designer-synthesis",
                "citation": None,
                "summary": "Designers need a plain-language synthesis review before draft ticket creation.",
                "evidence_claims": [
                    "Synthesis preview surfaces are enough to validate research direction.",
                ],
                "inference_claims": [
                    "A read-only synthesis step can reduce rushed ticket drafting.",
                ],
            }
        ]
    )


class _Response:
    def __init__(self, *, status: int, headers: dict[str, str], body: str) -> None:
        self.status = status
        self.headers = headers
        self.body = body


if __name__ == "__main__":
    unittest.main()
