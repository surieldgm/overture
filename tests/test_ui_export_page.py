import http.client
import json
import os
import tempfile
import threading
import unittest
from dataclasses import dataclass
from http import cookies
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode, urlparse

from overture.auth import AUTH_COOKIE_NAME, MagicLinkAuth
from overture.linear_client import CreatedIssue
from overture.ui_host import SESSION_COOKIE_NAME, build_ui_server

TEST_AUTH = MagicLinkAuth(secret="ui-export-test")


class ExportPageTests(unittest.TestCase):
    def test_export_page_renders_session_ticket_summary_and_missing_key_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            ticket_path = _write_ticket(store_dir)
            cookie = _session_cookie({"ticket_path": str(ticket_path)})
            with mock.patch.dict(os.environ, {}, clear=True):
                with _running_server(store_dir=store_dir, linear_client_factory=_StubLinearClient) as base_url:
                    response = _get(base_url, "/export", headers={"Cookie": cookie})

        self.assertEqual(response.status, 200)
        self.assertIn("Add graph-context synthesis brief", response.body)
        self.assertIn("## Context", response.body)
        self.assertIn("idea-to-research-to-graph-to-ticket flow", response.body)
        self.assertIn("LINEAR_API_KEY is not set", response.body)

    def test_dry_run_renders_existing_export_output_without_creating_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            ticket_path = _write_ticket(store_dir)
            stub = _StubLinearClient()
            cookie = _session_cookie({"ticket_path": str(ticket_path)})
            with mock.patch.dict(os.environ, {}, clear=True):
                with _running_server(store_dir=store_dir, linear_client_factory=lambda: stub) as base_url:
                    response = _post(base_url, "/export", {"action": "dry-run"}, headers={"Cookie": cookie})

        self.assertEqual(response.status, 200)
        self.assertIn("would create: title=Add graph-context synthesis brief", response.body)
        self.assertIn("## Context", response.body)
        self.assertEqual(stub.calls, [])

    def test_export_creates_issue_then_reclick_surfaces_already_exported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            ticket_path = _write_ticket(store_dir)
            stub = _StubLinearClient()
            cookie = _session_cookie({"ticket_path": str(ticket_path)})
            env = {"LINEAR_API_KEY": "test-key", "LINEAR_TEAM_ID": "team-1", "LINEAR_PROJECT_ID": "project-1"}
            with mock.patch.dict(os.environ, env, clear=True):
                with _running_server(store_dir=store_dir, linear_client_factory=lambda: stub) as base_url:
                    first = _post(base_url, "/export", {"action": "export"}, headers={"Cookie": cookie})
                    second = _post(base_url, "/export", {"action": "export"}, headers={"Cookie": cookie})

        self.assertEqual(first.status, 200)
        self.assertIn("https://linear.app/eria/issue/ERI-999/export-smoke", first.body)
        self.assertEqual(second.status, 200)
        self.assertIn("already exported", second.body)
        self.assertIn("https://linear.app/eria/issue/ERI-999/export-smoke", second.body)
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(stub.calls[0]["team_id"], "team-1")


@dataclass
class _StubLinearClient:
    calls: list[dict[str, object]]

    def __init__(self) -> None:
        self.calls = []

    def create_issue(self, **kwargs: object) -> CreatedIssue:
        self.calls.append(kwargs)
        return CreatedIssue(
            id="issue-999",
            identifier="ERI-999",
            url="https://linear.app/eria/issue/ERI-999/export-smoke",
        )


def _write_ticket(store_dir: Path) -> Path:
    ticket_dir = store_dir / "ticket"
    ticket_dir.mkdir(parents=True)
    source = Path("examples") / "overture_mvp_linear_issue_draft.md"
    target = ticket_dir / "session-ticket.md"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _running_server(*, store_dir: Path, linear_client_factory) -> "_ServerContext":
    return _ServerContext(store_dir=store_dir, linear_client_factory=linear_client_factory)


class _ServerContext:
    def __init__(self, *, store_dir: Path, linear_client_factory) -> None:
        self.store_dir = store_dir
        self.linear_client_factory = linear_client_factory

    def __enter__(self) -> str:
        self.server = build_ui_server(
            port=0,
            store_dir=self.store_dir,
            linear_client_factory=self.linear_client_factory,
            auth_manager=TEST_AUTH,
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
    try:
        request_headers = dict(headers or {})
        request_headers["Cookie"] = _merge_cookie(
            request_headers.get("Cookie"),
            AUTH_COOKIE_NAME,
            TEST_AUTH.issue_session("designer@example.com"),
        )
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        return _Response(
            status=response.status,
            headers={key: value for key, value in response.getheaders()},
            body=payload,
        )
    finally:
        connection.close()


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
    def __init__(self, *, status: int, headers: dict[str, str], body: str) -> None:
        self.status = status
        self.headers = headers
        self.body = body


if __name__ == "__main__":
    unittest.main()
