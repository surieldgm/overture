import http.client
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http import cookies
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode, urlparse

from overture.auth import AUTH_COOKIE_NAME, MagicLinkAuth
from overture.graph_http import SharedGraphBackend
from overture.graph import GraphRecord
from overture.graph_store import SqliteGraphStore
from overture.intake import load_intake_record
from overture.export import parse_ticket_file
from overture.linear_client import CreatedIssue
from overture.synthesis import synthesize_graph_context
from overture.ui_host import (
    RESEARCH_APPROVAL_ROUTE,
    RESEARCH_COMPLETE_ROUTE,
    SESSION_COOKIE_NAME,
    SYNTHESIS_ROUTE,
    TICKET_REVIEW_ROUTE,
    build_ui_server,
)

TEST_AUTH = MagicLinkAuth(secret="ui-wizard-smoke-test")


class WizardPhaseOneSmokeTests(unittest.TestCase):
    def test_http_wizard_drives_intake_to_export_with_stubbed_clients(self) -> None:
        linear_calls: list[dict[str, object]] = []

        class StubLinearClient:
            def create_issue(
                self,
                *,
                team_id,
                title,
                description,
                project_id=None,
                priority=None,
                sprint_label=None,
                milestone=None,
            ):
                linear_calls.append(
                    {
                        "team_id": team_id,
                        "title": title,
                        "description": description,
                        "project_id": project_id,
                        "priority": priority,
                        "sprint_label": sprint_label,
                        "milestone": milestone,
                    }
                )
                return CreatedIssue(
                    id="stubbed-issue-id",
                    identifier="ERI-123",
                    url="https://linear.app/eria/issue/ERI-123/full-wizard-smoke",
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            with mock.patch.dict(
                "os.environ",
                {"LINEAR_API_KEY": "stubbed-key", "LINEAR_TEAM_ID": "stubbed-ui-team"},
            ):
                server = _running_server(
                    store_dir=store_dir,
                    llm_client=_stub_llm_client,
                    linear_client_factory=StubLinearClient,
                )
                with server as base_url:
                    intake_response = _post(
                        base_url,
                        "/intake",
                        {"idea": "Validate the complete wizard path through Linear export"},
                    )
                    self.assertEqual(intake_response.status, 303)
                    self.assertEqual(intake_response.headers["Location"], RESEARCH_APPROVAL_ROUTE)
                    intake_session = _session_from_set_cookie(intake_response.headers["Set-Cookie"])
                    intake_id = intake_session["intake_id"]

                    approval_page = _get(base_url, RESEARCH_APPROVAL_ROUTE, headers={"Cookie": intake_response.headers["Set-Cookie"]})
                    self.assertEqual(approval_page.status, 200)
                    research_response = _post(
                        base_url,
                        RESEARCH_APPROVAL_ROUTE,
                        {"decision-0": "approve:https://example.test/designer-synthesis"},
                        headers={"Cookie": approval_page.headers["Set-Cookie"]},
                    )
                    self.assertEqual(research_response.status, 303)
                    self.assertEqual(research_response.headers["Location"], RESEARCH_COMPLETE_ROUTE)

                    synthesis_page = _get(base_url, SYNTHESIS_ROUTE, headers={"Cookie": research_response.headers["Set-Cookie"]})
                    self.assertEqual(synthesis_page.status, 200)
                    self.assertIn("Continue to ticket review", synthesis_page.body)

                    synthesis_response = _post(base_url, SYNTHESIS_ROUTE, {}, headers={"Cookie": synthesis_page.headers["Set-Cookie"]})
                    self.assertEqual(synthesis_response.status, 303)
                    self.assertEqual(synthesis_response.headers["Location"], TICKET_REVIEW_ROUTE)

                    ticket_page = _get(base_url, TICKET_REVIEW_ROUTE, headers={"Cookie": synthesis_response.headers["Set-Cookie"]})
                    self.assertEqual(ticket_page.status, 200)
                    self.assertIn('<textarea id="ticket_markdown" name="ticket_markdown"', ticket_page.body)

                    ticket_session = _session_from_set_cookie(ticket_page.headers["Set-Cookie"])
                    ticket_response = _post(
                        base_url,
                        TICKET_REVIEW_ROUTE,
                        {"ticket_markdown": ticket_session["ticket_markdown"]},
                        headers={"Cookie": ticket_page.headers["Set-Cookie"]},
                    )
                    self.assertEqual(ticket_response.status, 303)
                    self.assertEqual(ticket_response.headers["Location"], "/export")

                    export_page = _get(base_url, "/export", headers={"Cookie": ticket_response.headers["Set-Cookie"]})
                    self.assertEqual(export_page.status, 200)
                    self.assertIn('name="action" value="export"', export_page.body)

                    export_response = _post(
                        base_url,
                        "/export",
                        {"action": "export"},
                        headers={"Cookie": export_page.headers["Set-Cookie"]},
                    )
                    self.assertEqual(export_response.status, 200)
                    self.assertIn("https://linear.app/eria/issue/ERI-123/full-wizard-smoke", export_response.body)

            intake_path = store_dir / "intake" / f"{intake_id}.json"
            research_path = store_dir / "research" / f"{intake_id}.json"
            synthesis_path = store_dir / "synthesis" / f"{intake_id}.json"
            ticket_path = store_dir / "ticket" / f"{intake_id}-export.md"

            self.assertTrue(intake_path.exists(), intake_path)
            self.assertTrue(research_path.exists(), research_path)
            self.assertTrue(synthesis_path.exists(), synthesis_path)
            self.assertTrue(ticket_path.exists(), ticket_path)
            parsed_ticket = parse_ticket_file(ticket_path)

        self.assertEqual(len(linear_calls), 1)
        self.assertEqual(linear_calls[0]["team_id"], "stubbed-ui-team")
        self.assertEqual(linear_calls[0]["title"], parsed_ticket.title)
        self.assertTrue(str(linear_calls[0]["description"]).startswith("## Context"))

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

    def test_shared_wizard_cookie_is_scoped_by_authenticated_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            with _running_server(store_dir=store_dir, llm_client=_stub_llm_client) as base_url:
                first = _post(
                    base_url,
                    "/intake",
                    {"idea": "Designer one session state"},
                    headers={"Cookie": _auth_header("designer-1")},
                )
                second = _post(
                    base_url,
                    "/intake",
                    {"idea": "Designer two session state"},
                    headers={"Cookie": f'{first.headers["Set-Cookie"]}; {_auth_header("designer-2")}'},
                )

            first_session = _session_from_set_cookie(first.headers["Set-Cookie"])
            second_session = _session_from_set_cookie(second.headers["Set-Cookie"])
            intake_file_count = len(list((store_dir / "intake").glob("*.json")))

        self.assertEqual(first.status, 303)
        self.assertEqual(second.status, 303)
        self.assertEqual(first_session["user_id"], "designer-1@example.test")
        self.assertEqual(second_session["user_id"], "designer-2@example.test")
        self.assertNotEqual(first_session["intake_id"], second_session["intake_id"])
        self.assertEqual(intake_file_count, 2)

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
            self.assertIn("# Add ticket for Help designers validate synthesis before ticket drafting", ticket_page.body)

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

    def test_concurrent_authenticated_users_complete_wizard_against_shared_backend(self) -> None:
        """Smoke the full two-user wizard path against the shared backend.

        This boots the shared graph backend in-process and injects it into the
        socket-backed UI server. The same scenario can be run as an
        HTTP-loopback backend variant by replacing the injected backend with a
        `GraphHttpClient` pointed at `create_graph_http_server(..., port=0)`;
        that variant exercises transport behavior while keeping external
        services stubbed.
        """

        auth = MagicLinkAuth()
        linear_calls: list[dict[str, object]] = []
        linear_lock = threading.Lock()

        class StubLinearClient:
            def create_issue(
                self,
                *,
                team_id,
                title,
                description,
                project_id=None,
                priority=None,
                sprint_label=None,
                milestone=None,
            ):
                with linear_lock:
                    index = len(linear_calls) + 1
                    linear_calls.append(
                        {
                            "team_id": team_id,
                            "title": title,
                            "description": description,
                            "project_id": project_id,
                            "priority": priority,
                            "sprint_label": sprint_label,
                            "milestone": milestone,
                        }
                    )
                return CreatedIssue(
                    id=f"stubbed-issue-{index}",
                    identifier=f"ERI-{index}",
                    url=f"https://linear.app/eria/issue/ERI-{index}/multi-user-smoke",
                )

        def llm_client(prompt: str) -> str:
            if "Avery" in prompt:
                return _stub_llm_payload(
                    title="Avery research workflow",
                    url="https://example.test/avery-research",
                    summary="Avery needs isolated research evidence for a concurrent wizard run.",
                )
            if "Blake" in prompt:
                return _stub_llm_payload(
                    title="Blake synthesis workflow",
                    url="https://example.test/blake-synthesis",
                    summary="Blake needs isolated synthesis evidence for a concurrent wizard run.",
                )
            raise AssertionError(f"unexpected prompt: {prompt}")

        users = (
            {"email": "avery@example.test", "name": "Avery", "source": "https://example.test/avery-research"},
            {"email": "blake@example.test", "name": "Blake", "source": "https://example.test/blake-synthesis"},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            graph_backend = SharedGraphBackend(SqliteGraphStore(store_dir / "graph.sqlite"))
            with mock.patch.dict(
                "os.environ",
                {"LINEAR_API_KEY": "stubbed-key", "LINEAR_TEAM_ID": "stubbed-ui-team"},
            ):
                with _running_server(
                    store_dir=store_dir,
                    llm_client=llm_client,
                    linear_client_factory=StubLinearClient,
                    auth_manager=auth,
                    graph_backend=graph_backend,
                ) as base_url:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        results = tuple(executor.map(lambda user: _complete_authenticated_wizard(base_url, auth, user), users))

            by_email = {result["author_email"]: result for result in results}
            self.assertEqual(set(by_email), {user["email"] for user in users})
            self.assertEqual(len({result["intake_id"] for result in results}), 2)

            for user in users:
                result = by_email[user["email"]]
                author_id = str(result["author_id"])
                intake_id = str(result["intake_id"])
                intake = load_intake_record(store_dir / "intake" / f"{intake_id}.json")
                research = json.loads((store_dir / "research" / f"{intake_id}.json").read_text(encoding="utf-8"))
                synthesis = json.loads((store_dir / "synthesis" / f"{intake_id}.json").read_text(encoding="utf-8"))
                ticket = (store_dir / "ticket" / f"{intake_id}-export.md").read_text(encoding="utf-8")

                self.assertEqual(intake.author_id, author_id)
                self.assertEqual(intake.author_email, user["email"])
                self.assertEqual(research["author_id"], author_id)
                self.assertEqual(research["author_email"], user["email"])
                self.assertEqual(synthesis["author_id"], author_id)
                self.assertEqual(synthesis["author_email"], user["email"])
                self.assertIn(f"<!-- author_id: {author_id} -->", ticket)
                self.assertIn(f"<!-- author_email: {user['email']} -->", ticket)
                self.assertIn(user["name"], intake.raw_text)
                self.assertNotIn("Blake" if user["name"] == "Avery" else "Avery", intake.raw_text)

            nodes = graph_backend.list_nodes()
            edges = graph_backend.list_edges()
            counts = graph_backend.table_counts()
            self.assertEqual(counts, {"nodes": len(nodes), "edges": len(edges)})
            self.assertEqual(counts["nodes"], 14)
            self.assertEqual(counts["edges"], 14)
            authors_by_email = {user["email"]: by_email[user["email"]]["author_id"] for user in users}
            for user in users:
                author_nodes = [node for node in nodes if node.get("author_email") == user["email"]]
                author_edges = [edge for edge in edges if edge.get("author_email") == user["email"]]
                self.assertEqual(len(author_nodes), 7)
                self.assertEqual(len(author_edges), 7)
                self.assertTrue(all(node.get("author_id") == authors_by_email[user["email"]] for node in author_nodes))
                self.assertTrue(all(edge.get("author_id") == authors_by_email[user["email"]] for edge in author_edges))

        self.assertEqual(len(linear_calls), 2)
        self.assertEqual({call["team_id"] for call in linear_calls}, {"stubbed-ui-team"})

    def test_synthesis_persists_graph_records_with_authenticated_author(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir)
            with _running_server(store_dir=store_dir, llm_client=_stub_llm_client) as base_url:
                research_cookie = _approved_research_cookie(base_url, user_id="designer-2")
                synthesis_page = _get(
                    base_url,
                    SYNTHESIS_ROUTE,
                    headers={"Cookie": f'{research_cookie}; {_auth_header("designer-2")}'},
                )

            graph = SqliteGraphStore(store_dir / "graph.sqlite")
            nodes = graph.list_nodes()
            edges = graph.list_edges()

        self.assertEqual(synthesis_page.status, 200)
        self.assertTrue(nodes)
        self.assertTrue(edges)
        self.assertTrue(all(node["author_id"] == "designer-2@example.test" for node in nodes))
        self.assertTrue(all(edge["author_id"] == "designer-2@example.test" for edge in edges))


def _running_server(
    *,
    store_dir: Path,
    llm_client,
    synthesizer=synthesize_graph_context,
    linear_client_factory=None,
    auth_manager=None,
    graph_backend=None,
) -> "_ServerContext":
    return _ServerContext(
        store_dir=store_dir,
        llm_client=llm_client,
        synthesizer=synthesizer,
        linear_client_factory=linear_client_factory,
        auth_manager=auth_manager,
        graph_backend=graph_backend,
    )


class _ServerContext:
    def __init__(self, *, store_dir: Path, llm_client, synthesizer, linear_client_factory, auth_manager, graph_backend) -> None:
        self.store_dir = store_dir
        self.llm_client = llm_client
        self.synthesizer = synthesizer
        self.linear_client_factory = linear_client_factory
        self.auth_manager = auth_manager
        self.graph_backend = graph_backend

    def __enter__(self) -> str:
        self.server = build_ui_server(
            port=0,
            store_dir=self.store_dir,
            llm_client=self.llm_client,
            synthesizer=self.synthesizer,
            linear_client_factory=self.linear_client_factory,
            auth_manager=self.auth_manager or TEST_AUTH,
            graph_backend=self.graph_backend,
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
        if AUTH_COOKIE_NAME not in request_headers.get("Cookie", ""):
            auth_header = _auth_header("designer-1")
            request_headers["Cookie"] = (
                f'{request_headers["Cookie"]}; {auth_header}'
                if "Cookie" in request_headers
                else auth_header
            )
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        return _Response(
            status=response.status,
            headers=response.getheaders(),
            body=payload,
        )
    finally:
        connection.close()


def _session_from_set_cookie(header: str) -> dict[str, str]:
    jar = cookies.SimpleCookie()
    jar.load(header)
    return json.loads(jar[SESSION_COOKIE_NAME].value)


def _complete_authenticated_wizard(base_url: str, auth: MagicLinkAuth, user: dict[str, str]) -> dict[str, str]:
    auth_token = auth.issue_session(user["email"])
    auth_header = _merge_cookie(None, AUTH_COOKIE_NAME, auth_token)
    idea = f"{user['name']} needs a concurrent wizard run with isolated artifacts"

    intake_response = _post(base_url, "/intake", {"idea": idea}, headers={"Cookie": auth_header})
    assert intake_response.status == 303
    intake_session = _session_from_set_cookie(intake_response.headers["Set-Cookie"])
    intake_id = intake_session["intake_id"]
    intake_cookie = _merge_cookie(intake_response.headers["Set-Cookie"], AUTH_COOKIE_NAME, auth_token)

    approval_page = _get(base_url, RESEARCH_APPROVAL_ROUTE, headers={"Cookie": intake_cookie})
    assert approval_page.status == 200
    approval_cookie = _merge_cookie(approval_page.headers["Set-Cookie"], AUTH_COOKIE_NAME, auth_token)
    research_response = _post(
        base_url,
        RESEARCH_APPROVAL_ROUTE,
        {"decision-0": f"approve:{user['source']}"},
        headers={"Cookie": approval_cookie},
    )
    assert research_response.status == 303
    research_cookie = _merge_cookie(research_response.headers["Set-Cookie"], AUTH_COOKIE_NAME, auth_token)

    synthesis_page = _get(base_url, SYNTHESIS_ROUTE, headers={"Cookie": research_cookie})
    assert synthesis_page.status == 200
    synthesis_cookie = _merge_cookie(synthesis_page.headers["Set-Cookie"], AUTH_COOKIE_NAME, auth_token)
    synthesis_response = _post(base_url, SYNTHESIS_ROUTE, {}, headers={"Cookie": synthesis_cookie})
    assert synthesis_response.status == 303
    synthesis_advance_cookie = _merge_cookie(synthesis_response.headers["Set-Cookie"], AUTH_COOKIE_NAME, auth_token)

    ticket_page = _get(base_url, TICKET_REVIEW_ROUTE, headers={"Cookie": synthesis_advance_cookie})
    assert ticket_page.status == 200
    ticket_session = _session_from_set_cookie(ticket_page.headers["Set-Cookie"])
    ticket_cookie = _merge_cookie(ticket_page.headers["Set-Cookie"], AUTH_COOKIE_NAME, auth_token)
    ticket_response = _post(
        base_url,
        TICKET_REVIEW_ROUTE,
        {"ticket_markdown": ticket_session["ticket_markdown"]},
        headers={"Cookie": ticket_cookie},
    )
    assert ticket_response.status == 303
    ticket_review_cookie = _merge_cookie(ticket_response.headers["Set-Cookie"], AUTH_COOKIE_NAME, auth_token)

    export_page = _get(base_url, "/export", headers={"Cookie": ticket_review_cookie})
    assert export_page.status == 200
    export_cookie = _merge_cookie(export_page.headers["Set-Cookie"], AUTH_COOKIE_NAME, auth_token)
    export_response = _post(
        base_url,
        "/export",
        {"action": "export"},
        headers={"Cookie": export_cookie},
    )
    assert export_response.status == 200
    return {
        "author_id": intake_session["user_id"],
        "author_email": intake_session["user_email"],
        "intake_id": intake_id,
    }


def _merge_cookie(cookie_header: str | None, name: str, value: str) -> str:
    jar = cookies.SimpleCookie()
    if cookie_header:
        jar.load(cookie_header)
    if name not in jar:
        jar[name] = value
    return jar.output(header="").strip()


class _Response:
    def __init__(self, *, status: int, headers: list[tuple[str, str]], body: str) -> None:
        self.status = status
        self.all_headers = headers
        self.headers = dict(headers)
        self.body = body

    def header_values(self, name: str) -> list[str]:
        return [value for key, value in self.all_headers if key.lower() == name.lower()]

def _stub_llm_client(_prompt: str) -> str:
    return _stub_llm_payload(
        title="Designer synthesis workflow",
        url="https://example.test/designer-synthesis",
        summary="Designers need a synthesis review before committing to ticket drafts.",
    )


def _stub_llm_payload(*, title: str, url: str, summary: str) -> str:
    return json.dumps(
        [
            {
                "title": title,
                "url": url,
                "citation": None,
                "summary": summary,
                "evidence_claims": [
                    "Brief review surfaces misalignment before final ticket Markdown.",
                ],
                "inference_claims": [
                    "A read-only synthesis page should sit between research approval and ticket review.",
                ],
            }
        ]
    )


def _auth_header(user_id: str) -> str:
    return _merge_cookie(None, AUTH_COOKIE_NAME, TEST_AUTH.issue_session(f"{user_id}@example.test"))


def _approved_research_cookie(base_url: str, *, user_id: str = "designer-1") -> str:
    auth_header = _auth_header(user_id)
    intake_response = _post(
        base_url,
        "/intake",
        {"idea": "Help designers validate synthesis before ticket drafting"},
        headers={"Cookie": auth_header},
    )
    approval_page = _get(base_url, RESEARCH_APPROVAL_ROUTE, headers={"Cookie": f'{intake_response.headers["Set-Cookie"]}; {auth_header}'})
    research_response = _post(
        base_url,
        RESEARCH_APPROVAL_ROUTE,
        {"decision-0": "approve:https://example.test/designer-synthesis"},
        headers={"Cookie": f'{approval_page.headers["Set-Cookie"]}; {auth_header}'},
    )
    return research_response.headers["Set-Cookie"]


if __name__ == "__main__":
    unittest.main()
