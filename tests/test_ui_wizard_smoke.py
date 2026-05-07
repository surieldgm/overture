import http.client
import json
import tempfile
import threading
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import urlencode, urlparse

from overture.intake import load_intake_record
from overture.ui_host import (
    RESEARCH_APPROVAL_ROUTE,
    RESEARCH_COMPLETE_ROUTE,
    SESSION_COOKIE_NAME,
    build_ui_server,
)


class WizardPhaseOneSmokeTests(unittest.TestCase):
    def test_http_wizard_persists_intake_research_and_points_session_to_synthesis(self) -> None:
        prompts: list[str] = []
        idea = "Help designers turn Overture intake into research-backed Symphony tickets"

        def stub_llm_client(prompt: str) -> str:
            prompts.append(prompt)
            return json.dumps(
                [
                    {
                        "title": "Designer intake research workflow",
                        "url": "https://example.test/designer-intake-research",
                        "citation": None,
                        "summary": (
                            "Designer intake workflows need suggested research sources, "
                            "manual approval, and persisted evidence for Symphony tickets."
                        ),
                        "evidence_claims": [
                            "Manual approval prevents unreviewed source suggestions from entering the pipeline.",
                            "Persisted research evidence can support Symphony-ready tickets.",
                        ],
                        "inference_claims": [
                            "HTTP-only approval can validate the wizard before JavaScript behavior is added.",
                        ],
                    }
                ]
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            with _running_server(store_dir=store_dir, llm_client=stub_llm_client) as base_url:
                intake_response = _post(base_url, "/intake", {"idea": idea})
                self.assertEqual(intake_response.status, 303)
                self.assertEqual(intake_response.headers["Location"], RESEARCH_APPROVAL_ROUTE)

                intake_cookie = intake_response.headers["Set-Cookie"]
                intake_session = _session_from_set_cookie(intake_cookie)
                intake_id = intake_session["intake_id"]

                approval_page = _get(base_url, RESEARCH_APPROVAL_ROUTE, headers={"Cookie": intake_cookie})
                self.assertEqual(approval_page.status, 200)
                self.assertIn(intake_id, approval_page.body)
                self.assertIn("Save approved sources", approval_page.body)
                self.assertIn("Designer intake research workflow", approval_page.body)

                research_response = _post(
                    base_url,
                    RESEARCH_APPROVAL_ROUTE,
                    {"decision-0": "approve:https://example.test/designer-intake-research"},
                    headers={"Cookie": approval_page.headers["Set-Cookie"]},
                )

            self.assertEqual(research_response.status, 303)
            self.assertEqual(research_response.headers["Location"], RESEARCH_COMPLETE_ROUTE)
            final_session = _session_from_set_cookie(research_response.headers["Set-Cookie"])
            self.assertEqual(final_session["intake_id"], intake_id)
            self.assertEqual(final_session["research_id"], intake_id)
            self.assertEqual(final_session["next_route"], "/synthesis")

            intake_path = store_dir / "intake" / f"{intake_id}.json"
            research_path = store_dir / "research" / f"{intake_id}.json"
            intake = load_intake_record(intake_path)
            research = json.loads(research_path.read_text(encoding="utf-8"))

        self.assertEqual(intake.raw_text, idea)
        self.assertEqual(intake.source_type, "ui")
        self.assertEqual(research["intake_id"], intake_id)
        self.assertEqual(len(research["items"]), 1)
        self.assertEqual(research["errors"], [])
        self.assertEqual(len(prompts), 1)
        self.assertIn(intake_id, prompts[0])


def _running_server(*, store_dir: Path, llm_client) -> "_ServerContext":
    return _ServerContext(store_dir=store_dir, llm_client=llm_client)


class _ServerContext:
    def __init__(self, *, store_dir: Path, llm_client) -> None:
        self.store_dir = store_dir
        self.llm_client = llm_client

    def __enter__(self) -> str:
        self.server = build_ui_server(port=0, store_dir=self.store_dir, llm_client=self.llm_client)
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
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        return _Response(
            status=response.status,
            headers={key: value for key, value in response.getheaders()},
            body=payload,
        )
    finally:
        connection.close()


def _session_from_set_cookie(header: str) -> dict[str, str]:
    jar = cookies.SimpleCookie()
    jar.load(header)
    return json.loads(jar[SESSION_COOKIE_NAME].value)


class _Response:
    def __init__(self, *, status: int, headers: dict[str, str], body: str) -> None:
        self.status = status
        self.headers = headers
        self.body = body


if __name__ == "__main__":
    unittest.main()
