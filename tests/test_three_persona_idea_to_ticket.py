import html
import re
import http.client
import tempfile
import threading
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import urlencode, urlparse

from overture.auth import AUTH_COOKIE_NAME, MagicLinkAuth
from overture.research_llm import fake_llm_client
from overture.ui_host import (
    RESEARCH_APPROVAL_ROUTE,
    SYNTHESIS_ROUTE,
    TICKET_REVIEW_ROUTE,
    build_ui_server,
)


class ThreePersonaIdeaToTicketSmokeTests(unittest.TestCase):
    def test_three_personas_complete_flow_and_export_summary(self) -> None:
        personas = (
            (
                "Carla",
                "carla@dogfood.test",
                (
                    "Add session metadata to the peer onboarding template so "
                    "Designer #1 can leave timestamps, tools used, and example "
                    "screen recordings for Designer #2 instead of handing off a "
                    "generic empty form."
                ),
                "Add ticket for Add session metadata to the peer onboarding template so",
                "Add session metadata to the peer onboarding template so",
            ),
            (
                "Tomás",
                "tomas@overture.test",
                (
                    "Show a sidebar of recent intakes on the wizard so I can reuse "
                    "phrasing from past ideas instead of starting from a blank page "
                    "every time."
                ),
                "Add ticket for Show a sidebar of recent intakes on the wizard",
                "Show a sidebar of recent intakes on the wizard so",
            ),
            (
                "Rocío",
                "rocio@startup.test",
                (
                    "Send a weekly digest email to onboarded users summarizing their "
                    "activity. The digest should highlight 2-3 specific things they "
                    "did and gently remind them of the next step in onboarding."
                ),
                "Add ticket for Send a weekly digest email to onboarded users summarizing",
                "Send a weekly digest email to onboarded users summarizing",
            ),
        )

        for persona, email, idea, expected_title, expected_body_fragment in personas:
            with self.subTest(persona=persona):
                with tempfile.TemporaryDirectory() as tmpdir:
                    store_dir = Path(tmpdir)
                    auth = MagicLinkAuth(secret="three-persona-smoke")
                    auth_cookie = _auth_cookie(auth, email)
                    with _running_server(
                        store_dir=store_dir,
                        llm_client=fake_llm_client,
                        auth_manager=auth,
                    ) as base_url:
                        intake_response = _post(
                            base_url,
                            "/intake",
                            {"idea": idea},
                            headers={"Cookie": auth_cookie},
                        )
                        self.assertEqual(intake_response.status, 303)
                        self.assertEqual(intake_response.headers["Location"], RESEARCH_APPROVAL_ROUTE)

                        approval_cookie = _merge_cookie(
                            intake_response.headers["Set-Cookie"],
                            AUTH_COOKIE_NAME,
                            auth.issue_session(email),
                        )
                        approval_response = _get(
                            base_url,
                            RESEARCH_APPROVAL_ROUTE,
                            headers={"Cookie": approval_cookie},
                        )
                        self.assertEqual(approval_response.status, 200)

                        research_response = _post(
                            base_url,
                            RESEARCH_APPROVAL_ROUTE,
                            {"decision-0": "approve:https://example.test/symphony-ticket-evidence"},
                            headers={"Cookie": _merge_cookie(
                                approval_response.headers["Set-Cookie"],
                                AUTH_COOKIE_NAME,
                                auth.issue_session(email),
                            )},
                        )
                        self.assertEqual(research_response.status, 303)
                        self.assertEqual(research_response.headers["Location"], "/research/complete")

                        synthesis_response = _post(
                            base_url,
                            SYNTHESIS_ROUTE,
                            {},
                            headers={"Cookie": _merge_cookie(
                                research_response.headers["Set-Cookie"],
                                AUTH_COOKIE_NAME,
                                auth.issue_session(email),
                            )},
                        )
                        self.assertEqual(synthesis_response.status, 303)
                        self.assertEqual(synthesis_response.headers["Location"], TICKET_REVIEW_ROUTE)

                        ticket_response = _get(
                            base_url,
                            TICKET_REVIEW_ROUTE,
                            headers={"Cookie": _merge_cookie(
                                synthesis_response.headers["Set-Cookie"],
                                AUTH_COOKIE_NAME,
                                auth.issue_session(email),
                            )},
                        )
                        self.assertEqual(ticket_response.status, 200)

                        ticket_markdown = _extract_textarea(ticket_response.body)
                        self.assertTrue(ticket_markdown)

                        ticket_submit = _post(
                            base_url,
                            TICKET_REVIEW_ROUTE,
                            {"ticket_markdown": ticket_markdown},
                            headers={"Cookie": _merge_cookie(
                                ticket_response.headers["Set-Cookie"],
                                AUTH_COOKIE_NAME,
                                auth.issue_session(email),
                            )},
                        )
                        self.assertEqual(ticket_submit.status, 303)
                        self.assertEqual(ticket_submit.headers["Location"], "/export")

                        export_response = _get(
                            base_url,
                            "/export",
                            headers={"Cookie": _merge_cookie(
                                ticket_submit.headers["Set-Cookie"],
                                AUTH_COOKIE_NAME,
                                auth.issue_session(email),
                            )},
                        )
                        self.assertEqual(export_response.status, 200)
                        title, body_preview = _extract_export_summary(export_response.body)

                        self.assertEqual(title, expected_title)
                        self.assertTrue(body_preview)
                        self.assertIn("## Context", body_preview)
                        self.assertIn(expected_body_fragment, body_preview)


def _running_server(*, store_dir: Path, llm_client, auth_manager: MagicLinkAuth) -> "_ServerContext":
    return _ServerContext(store_dir=store_dir, llm_client=llm_client, auth_manager=auth_manager)


class _ServerContext:
    def __init__(self, *, store_dir: Path, llm_client, auth_manager: MagicLinkAuth) -> None:
        self.store_dir = store_dir
        self.llm_client = llm_client
        self.auth_manager = auth_manager

    def __enter__(self) -> str:
        self.server = build_ui_server(
            port=0,
            store_dir=self.store_dir,
            llm_client=self.llm_client,
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


class _Response:
    def __init__(self, *, status: int, headers: dict[str, str], body: str) -> None:
        self.status = status
        self.headers = headers
        self.body = body


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: str = "",
    headers: dict[str, str] | None = None,
) -> _Response:
    parsed = urlparse(base_url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        request_headers = dict(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        return _Response(status=response.status, headers=dict(response.getheaders()), body=payload)
    finally:
        connection.close()


def _get(base_url: str, path: str, *, headers: dict[str, str] | None = None) -> _Response:
    return _request(base_url, "GET", path, headers=headers)


def _post(
    base_url: str,
    path: str,
    fields: dict[str, str],
    *,
    headers: dict[str, str] | None = None,
) -> _Response:
    body = urlencode(fields)
    request_headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
    return _request(base_url, "POST", path, body=body, headers=request_headers)


def _merge_cookie(cookie_header: str | None, name: str, value: str) -> str:
    jar = cookies.SimpleCookie()
    if cookie_header:
        jar.load(cookie_header)
    if name not in jar:
        jar[name] = value
    return jar.output(header="").strip()


def _auth_cookie(auth: MagicLinkAuth, email: str) -> str:
    return _merge_cookie(None, AUTH_COOKIE_NAME, auth.issue_session(email))


def _extract_textarea(page: str) -> str:
    match = re.search(r'<textarea id="ticket_markdown" name="ticket_markdown"[^>]*>(.*?)</textarea>', page, re.S)
    if not match:
        return ""
    return html.unescape(match.group(1))


def _extract_export_summary(page: str) -> tuple[str, str]:
    title_match = re.search(r"<dt>Title</dt>\s*<dd>(.*?)</dd>", page, re.S)
    body_match = re.search(r"<dt>Body preview</dt>\s*<dd>(.*?)</dd>", page, re.S)
    title = title_match.group(1).strip() if title_match else ""
    body = body_match.group(1).strip() if body_match else ""
    return title, body


if __name__ == "__main__":
    unittest.main()
