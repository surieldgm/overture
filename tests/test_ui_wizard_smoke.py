import http.client
import json
import tempfile
import threading
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import urlencode, urlparse

from overture.graph import GraphRecord
from overture.graph_store import SqliteGraphStore
from overture.intake import load_intake_record
from overture.synthesis import synthesize_graph_context
from overture.ui_host import (
    RESEARCH_APPROVAL_ROUTE,
    RESEARCH_COMPLETE_ROUTE,
    SESSION_COOKIE_NAME,
    SYNTHESIS_ROUTE,
    TICKET_REVIEW_ROUTE,
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

    def test_synthesis_page_renders_brief_and_advances_to_ticket_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            with _running_server(store_dir=store_dir, llm_client=_stub_llm_client) as base_url:
                research_cookie = _approved_research_cookie(base_url)

                synthesis_page = _get(base_url, SYNTHESIS_ROUTE, headers={"Cookie": research_cookie})
                self.assertEqual(synthesis_page.status, 200)
                expected_order = ["Problem", "User need", "Evidence", "Connected concepts", "Proposed capability", "Candidate ticket"]
                positions = [synthesis_page.body.index(text) for text in expected_order]
                self.assertEqual(positions, sorted(positions))
                self.assertIn("Current run", synthesis_page.body)
                self.assertIn("Continue to ticket review", synthesis_page.body)

                advance_response = _post(base_url, SYNTHESIS_ROUTE, {}, headers={"Cookie": synthesis_page.headers["Set-Cookie"]})
                ticket_page = _get(base_url, TICKET_REVIEW_ROUTE, headers={"Cookie": advance_response.headers["Set-Cookie"]})

            self.assertEqual(advance_response.status, 303)
            self.assertEqual(advance_response.headers["Location"], TICKET_REVIEW_ROUTE)
            advanced_session = _session_from_set_cookie(advance_response.headers["Set-Cookie"])
            self.assertEqual(advanced_session["next_route"], TICKET_REVIEW_ROUTE)
            self.assertEqual(advanced_session["synthesis_id"], advanced_session["intake_id"])
            self.assertIn("synthesis_brief", advanced_session)
            self.assertTrue((store_dir / "synthesis" / f"{advanced_session['intake_id']}.json").exists())
            self.assertEqual(ticket_page.status, 200)
            self.assertIn('<textarea id="ticket_markdown" name="ticket_markdown"', ticket_page.body)
            self.assertIn("# Draft ticket for Help designers validate synthesis before ticket drafting", ticket_page.body)

    def test_synthesis_page_distinguishes_prior_connected_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            SqliteGraphStore(store_dir / "graph.sqlite").upsert_record(
                GraphRecord(
                    kind="Idea",
                    key="idea_prior_run",
                    properties={"label": "Prior run discovery", "summary": "Prior synthesis found reusable context."},
                )
            )
            with _running_server(store_dir=store_dir, llm_client=_stub_llm_client) as base_url:
                research_cookie = _approved_research_cookie(base_url)
                synthesis_page = _get(base_url, SYNTHESIS_ROUTE, headers={"Cookie": research_cookie})

            self.assertEqual(synthesis_page.status, 200)
            self.assertIn("Current run", synthesis_page.body)
            self.assertIn("Prior run", synthesis_page.body)
            self.assertIn("Prior run discovery", synthesis_page.body)
            self.assertIn('class="concept-card prior"', synthesis_page.body)

    def test_synthesis_revisit_uses_cached_brief_without_recomputation(self) -> None:
        calls = 0

        def counting_synthesizer(context, *, prior_context=None):
            nonlocal calls
            calls += 1
            return synthesize_graph_context(context, prior_context=prior_context)

        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            with _running_server(
                store_dir=store_dir,
                llm_client=_stub_llm_client,
                synthesizer=counting_synthesizer,
            ) as base_url:
                research_cookie = _approved_research_cookie(base_url)
                first_page = _get(base_url, SYNTHESIS_ROUTE, headers={"Cookie": research_cookie})
                self.assertEqual(first_page.status, 200)
                advance_response = _post(base_url, SYNTHESIS_ROUTE, {}, headers={"Cookie": first_page.headers["Set-Cookie"]})
                revisit_page = _get(base_url, SYNTHESIS_ROUTE, headers={"Cookie": advance_response.headers["Set-Cookie"]})

            self.assertEqual(revisit_page.status, 200)
            self.assertIn("Cached brief", revisit_page.body)
            self.assertEqual(calls, 1)


def _running_server(*, store_dir: Path, llm_client, synthesizer=synthesize_graph_context) -> "_ServerContext":
    return _ServerContext(store_dir=store_dir, llm_client=llm_client, synthesizer=synthesizer)


class _ServerContext:
    def __init__(self, *, store_dir: Path, llm_client, synthesizer) -> None:
        self.store_dir = store_dir
        self.llm_client = llm_client
        self.synthesizer = synthesizer

    def __enter__(self) -> str:
        self.server = build_ui_server(
            port=0,
            store_dir=self.store_dir,
            llm_client=self.llm_client,
            synthesizer=self.synthesizer,
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

def _stub_llm_client(_prompt: str) -> str:
    return json.dumps(
        [
            {
                "title": "Designer synthesis workflow",
                "url": "https://example.test/designer-synthesis",
                "citation": None,
                "summary": "Designers need a synthesis review before committing to ticket drafts.",
                "evidence_claims": [
                    "Brief review surfaces misalignment before final ticket Markdown.",
                ],
                "inference_claims": [
                    "A read-only synthesis page should sit between research approval and ticket review.",
                ],
            }
        ]
    )


def _approved_research_cookie(base_url: str) -> str:
    intake_response = _post(base_url, "/intake", {"idea": "Help designers validate synthesis before ticket drafting"})
    approval_page = _get(base_url, RESEARCH_APPROVAL_ROUTE, headers={"Cookie": intake_response.headers["Set-Cookie"]})
    research_response = _post(
        base_url,
        RESEARCH_APPROVAL_ROUTE,
        {"decision-0": "approve:https://example.test/designer-synthesis"},
        headers={"Cookie": approval_page.headers["Set-Cookie"]},
    )
    return research_response.headers["Set-Cookie"]


if __name__ == "__main__":
    unittest.main()
