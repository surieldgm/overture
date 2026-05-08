import http.client
import json
import tempfile
import unittest
from dataclasses import dataclass
from http import cookies
from pathlib import Path
from urllib.parse import urlencode, urlparse

from overture.auth import AUTH_COOKIE_NAME, FileMagicLinkSender, MagicLinkAuth
from overture.ui_host import RESEARCH_APPROVAL_ROUTE, SESSION_COOKIE_NAME
from tests.test_ui_wizard_smoke import _running_server


BROWSER_COOKIE_LIMIT_BYTES = 4096


class ResearchApprovalSessionReproTests(unittest.TestCase):
    def test_research_approval_400_analysis_doc_exists(self) -> None:
        path = Path("docs/user-tests/research-approval-400-analysis.md")
        self.assertTrue(path.exists(), f"Missing analysis doc: {path}")
        self.assertGreater(path.stat().st_size, 200, f"Analysis doc looks too small: {path}")

    def test_browser_like_cookie_storage_reproduces_research_approval_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            browser = BrowserLikeClient()

            auth = _test_auth(store_dir)
            with _running_server(store_dir=store_dir, llm_client=_five_large_source_client, auth_manager=auth) as base_url:
                _login_with_magic_link(browser, base_url, store_dir, "designer@example.test")
                intake = browser.post(
                    base_url,
                    "/intake",
                    {"idea": "Add session metadata to the peer onboarding template"},
                )
                approval = browser.get(base_url, RESEARCH_APPROVAL_ROUTE)
                evidence = browser.post_with_evidence(
                    base_url,
                    RESEARCH_APPROVAL_ROUTE,
                    {"decision-0": "approve:https://example.test/source-0"},
                )

            self.assertEqual(intake.status, 303)
            self.assertEqual(approval.status, 200)
            self.assertGreater(evidence.rejected_cookie_sizes[SESSION_COOKIE_NAME], BROWSER_COOKIE_LIMIT_BYTES)
            self.assertEqual(evidence.status, 400)
            self.assertIn("No suggested sources are available for this intake.", evidence.response_body)
            self.assertIn("decision-0=approve%3Ahttps%3A%2F%2Fexample.test%2Fsource-0", evidence.request_body)
            self.assertIn(AUTH_COOKIE_NAME, evidence.cookie_state)
            self.assertIn(SESSION_COOKIE_NAME, evidence.cookie_state)
            self.assertNotIn("research_candidates", evidence.cookie_state[SESSION_COOKIE_NAME])
            self.assertEqual(list((store_dir / "research").glob("*.json")), [])

    @unittest.expectedFailure
    def test_browser_like_cookie_storage_can_submit_approval_after_session_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            browser = BrowserLikeClient()

            auth = _test_auth(store_dir)
            with _running_server(store_dir=store_dir, llm_client=_five_large_source_client, auth_manager=auth) as base_url:
                _login_with_magic_link(browser, base_url, store_dir, "designer@example.test")
                browser.post(
                    base_url,
                    "/intake",
                    {"idea": "Add session metadata to the peer onboarding template"},
                )
                browser.get(base_url, RESEARCH_APPROVAL_ROUTE)
                response = browser.post(
                    base_url,
                    RESEARCH_APPROVAL_ROUTE,
                    {"decision-0": "approve:https://example.test/source-0"},
                )

            self.assertEqual(response.status, 303)
            self.assertTrue(list((store_dir / "research").glob("*.json")))


@dataclass(frozen=True)
class Response:
    status: int
    headers: list[tuple[str, str]]
    body: str

    @property
    def header_map(self) -> dict[str, str]:
        return dict(self.headers)


@dataclass(frozen=True)
class FailureEvidence:
    status: int
    request_body: str
    response_body: str
    cookie_state: dict[str, str]
    rejected_cookie_sizes: dict[str, int]


class BrowserLikeClient:
    def __init__(self, *, cookie_limit_bytes: int = BROWSER_COOKIE_LIMIT_BYTES) -> None:
        self.cookie_limit_bytes = cookie_limit_bytes
        self.cookies: dict[str, str] = {}
        self.rejected_cookie_sizes: dict[str, int] = {}

    def get(self, base_url: str, path: str) -> Response:
        return self.request(base_url, "GET", path)

    def post(self, base_url: str, path: str, fields: dict[str, str]) -> Response:
        return self.request(base_url, "POST", path, urlencode(fields))

    def post_with_evidence(self, base_url: str, path: str, fields: dict[str, str]) -> FailureEvidence:
        body = urlencode(fields)
        response = self.request(base_url, "POST", path, body)
        return FailureEvidence(
            status=response.status,
            request_body=body,
            response_body=response.body,
            cookie_state=dict(self.cookies),
            rejected_cookie_sizes=dict(self.rejected_cookie_sizes),
        )

    def request(self, base_url: str, method: str, path: str, body: str = "") -> Response:
        parsed = urlparse(base_url)
        headers = {"Cookie": self.cookie_header()}
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={key: value for key, value in headers.items() if value},
            )
            response = connection.getresponse()
            payload = response.read().decode("utf-8")
            headers_list = response.getheaders()
        finally:
            connection.close()
        self.store_response_cookies(headers_list)
        return Response(status=response.status, headers=headers_list, body=payload)

    def cookie_header(self) -> str:
        return "; ".join(f"{name}={value}" for name, value in sorted(self.cookies.items()))

    def store_response_cookies(self, headers: list[tuple[str, str]]) -> None:
        for name, value in headers:
            if name.lower() != "set-cookie":
                continue
            jar = cookies.SimpleCookie()
            jar.load(value)
            for cookie_name, morsel in jar.items():
                if len(value.encode("utf-8")) > self.cookie_limit_bytes:
                    self.rejected_cookie_sizes[cookie_name] = len(value.encode("utf-8"))
                    continue
                self.cookies[cookie_name] = morsel.coded_value


def _login_with_magic_link(browser: BrowserLikeClient, base_url: str, store_dir: Path, email: str) -> None:
    requested = browser.post(base_url, "/auth/magic-link", {"email": email})
    assert requested.status == 200
    outbox = store_dir / "magic-links.jsonl"
    payload = json.loads(outbox.read_text(encoding="utf-8").splitlines()[-1])
    parsed_link = urlparse(payload["link"])
    consumed = browser.get(base_url, parsed_link.path + "?" + parsed_link.query)
    assert consumed.status == 200


def _test_auth(store_dir: Path) -> MagicLinkAuth:
    return MagicLinkAuth(
        secret="research-approval-session-repro-test",
        sender=FileMagicLinkSender(store_dir / "magic-links.jsonl"),
    )


def _five_large_source_client(_prompt: str) -> str:
    summary = " ".join(["research evidence with detailed context"] * 45)
    claim = " ".join(["specific acceptance validation evidence"] * 18)
    return json.dumps(
        [
            {
                "title": f"Relevant source {index}",
                "url": f"https://example.test/source-{index}",
                "citation": None,
                "summary": f"{summary} {index}",
                "evidence_claims": [f"{claim} {index}a", f"{claim} {index}b"],
                "inference_claims": [f"{claim} {index}c"],
            }
            for index in range(5)
        ]
    )


if __name__ == "__main__":
    unittest.main()
