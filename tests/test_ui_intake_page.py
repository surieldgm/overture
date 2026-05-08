import io
import json
import tempfile
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import urlencode
from urllib.parse import urlparse

from overture.auth import AUTH_COOKIE_NAME
from overture.intake import create_intake_record, load_intake_record
from overture.ui_host import (
    INTAKE_TEXT_MAX_CHARS,
    RESEARCH_COMPLETE_ROUTE,
    RESEARCH_APPROVAL_ROUTE,
    SESSION_COOKIE_NAME,
    SESSION_SYNTHESIS_BRIEF_KEY,
    SESSION_TICKET_MARKDOWN_KEY,
    OvertureUiApp,
    session_from_environ,
)


class IntakePageTests(unittest.TestCase):
    def test_unauthenticated_intake_redirects_to_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", "/intake", authenticated=False)

        self.assertEqual(response.status, "302 Found")
        self.assertEqual(response.headers["Location"], "/auth/login?next=/intake")

    def test_unauthenticated_backend_write_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(
                OvertureUiApp(store_dir=tmpdir),
                "POST",
                "/intake",
                {"idea": "Anonymous writes must be rejected"},
                authenticated=False,
            )

            self.assertEqual(response.status, "302 Found")
            self.assertEqual(response.headers["Location"], "/auth/login?next=/intake")
            self.assertEqual(list((Path(tmpdir) / "intake").glob("*.json")), [])

    def test_login_page_uses_role_neutral_overture_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", "/auth/login", authenticated=False)

        self.assertEqual(response.status, "200 OK")
        self.assertIn("Sign in to Overture", response.body)
        self.assertNotIn("Designer sign in", response.body)

    def test_magic_link_flow_establishes_refreshed_designer_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            sent = _request(app, "POST", "/auth/magic-link", {"email": "Designer@Example.COM"}, authenticated=False)

            self.assertEqual(sent.status, "200 OK")
            self.assertIn("designer@example.com", sent.body)
            self.assertIn("Open the magic link locally", sent.body)
            self.assertNotIn("Open development magic link", sent.body)
            outbox = Path(tmpdir) / "magic-links.jsonl"
            self.assertIn("<summary>Local development details</summary>", sent.body)
            self.assertNotIn("<details open", sent.body)
            action_index = sent.body.index("Open the magic link locally")
            details_index = sent.body.index("<details")
            self.assertLess(action_index, details_index)
            default_render = sent.body[:details_index]
            self.assertNotIn("Development outbox", default_render)
            self.assertNotIn(str(outbox), default_render)
            details_markup = sent.body[details_index:]
            self.assertIn("Development outbox", details_markup)
            self.assertIn(str(outbox), details_markup)
            payload = json.loads(outbox.read_text(encoding="utf-8").splitlines()[-1])
            link_path = urlparse(payload["link"]).path + "?" + urlparse(payload["link"]).query

            consumed = _request(app, "GET", link_path, authenticated=False)
            self.assertEqual(consumed.status, "200 OK")
            self.assertNotIn("Location", consumed.headers)
            self.assertIn(AUTH_COOKIE_NAME, consumed.headers["Set-Cookie"])
            self.assertIn("Continue to intake", consumed.body)
            self.assertIn('href="/intake"', consumed.body)

            page = _request(app, "GET", "/intake", cookie=consumed.headers["Set-Cookie"], authenticated=False)
            self.assertEqual(page.status, "200 OK")
            self.assertIn("Signed in as <code>designer@example.com</code>", page.body)
            self.assertTrue(any(AUTH_COOKIE_NAME in value for value in page.header_values("Set-Cookie")))

    def test_expired_auth_token_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            expired = app.auth_manager.issue_session("designer@example.com", ttl_seconds=-1)
            response = _request(
                app,
                "POST",
                "/intake",
                {"idea": "Expired token should fail"},
                cookie=f"{AUTH_COOKIE_NAME}={expired}",
                authenticated=False,
            )

        self.assertEqual(response.status, "302 Found")
        self.assertEqual(response.headers["Location"], "/auth/login?next=/intake")

    def test_intake_page_renders_form_and_curated_examples_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            auth_cookie = _merge_cookie(None, AUTH_COOKIE_NAME, app.auth_manager.issue_session("operator@example.com"))
            response = _request(app, "GET", "/intake", cookie=auth_cookie, authenticated=False)

        self.assertEqual(response.status, "200 OK")
        self.assertIn('<textarea id="idea" name="idea"', response.body)
        self.assertIn("Describe your idea before starting research.", response.body)
        self.assertIn("Start research approval", response.body)
        self.assertIn('href="/examples/intake_examples/"', response.body)
        self.assertIn(f"{INTAKE_TEXT_MAX_CHARS:,}", response.body)
        self.assertNotIn("Capture the designer idea before research starts.", response.body)
        self.assertNotIn("designer", response.body.lower())

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
            self.assertEqual(session["designer_email"], "designer@example.com")

            approval = _request(
                app,
                "GET",
                RESEARCH_APPROVAL_ROUTE,
                cookie=cookie_header,
            )
            self.assertEqual(approval.status, "200 OK")
            self.assertIn(record.id, approval.body)
            self.assertIn("Symphony-ready ticket evidence contract", approval.body)
            self.assertIn("Designer-led intake research workflow", approval.body)
            self.assertIn("Approve", approval.body)
            self.assertIn("Reject", approval.body)

    def test_research_submit_persists_approved_subset_and_advances(self) -> None:
        idea = "Build designer-led research approval for Overture"
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            intake = _request(app, "POST", "/intake", {"idea": idea})
            approval = _request(app, "GET", RESEARCH_APPROVAL_ROUTE, cookie=intake.headers["Set-Cookie"])

            response = _request(
                app,
                "POST",
                RESEARCH_APPROVAL_ROUTE,
                {
                    "decision-0": "approve:https://example.test/symphony-ticket-evidence",
                    "decision-1": "reject:https://example.test/designer-intake-research",
                },
                cookie=approval.headers["Set-Cookie"],
            )

            self.assertEqual(response.status, "303 See Other")
            self.assertEqual(response.headers["Location"], RESEARCH_COMPLETE_ROUTE)
            session = _session_from_set_cookie(response.headers["Set-Cookie"])
            intake_id = session["intake_id"]
            payload = json.loads((Path(tmpdir) / "research" / f"{intake_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["intake_id"], intake_id)
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(payload["items"][0]["source"]["title"], "Symphony-ready ticket evidence contract")
            self.assertIn("research_result", session)

            complete = _request(app, "GET", RESEARCH_COMPLETE_ROUTE, cookie=response.headers["Set-Cookie"])
            self.assertEqual(complete.status, "200 OK")
            self.assertIn("Continue to synthesis", complete.body)
            self.assertIn('href="/synthesis"', complete.body)
            synthesis = _request(app, "GET", "/synthesis", cookie=response.headers["Set-Cookie"])
            self.assertEqual(synthesis.status, "200 OK")
            self.assertIn("Continue to ticket review", synthesis.body)

    def test_research_submit_with_zero_approvals_stays_on_page_with_inline_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            intake = _request(app, "POST", "/intake", {"idea": "Review all sources before approval"})
            approval = _request(app, "GET", RESEARCH_APPROVAL_ROUTE, cookie=intake.headers["Set-Cookie"])

            response = _request(
                app,
                "POST",
                RESEARCH_APPROVAL_ROUTE,
                {
                    "decision-0": "reject:https://example.test/symphony-ticket-evidence",
                    "decision-1": "reject:https://example.test/designer-intake-research",
                },
                cookie=approval.headers["Set-Cookie"],
            )

            self.assertEqual(response.status, "400 Bad Request")
            self.assertIn("Approve at least one source before continuing.", response.body)
            self.assertNotIn("Location", response.headers)
            self.assertEqual(list((Path(tmpdir) / "research").glob("*.json")), [])

    def test_research_revisit_shows_previously_approved_selection_for_same_intake(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            intake = _request(app, "POST", "/intake", {"idea": "Persist source approval state"})
            approval = _request(app, "GET", RESEARCH_APPROVAL_ROUTE, cookie=intake.headers["Set-Cookie"])
            submit = _request(
                app,
                "POST",
                RESEARCH_APPROVAL_ROUTE,
                {
                    "decision-0": "reject:https://example.test/symphony-ticket-evidence",
                    "decision-1": "approve:https://example.test/designer-intake-research",
                },
                cookie=approval.headers["Set-Cookie"],
            )

            revisit = _request(app, "GET", RESEARCH_APPROVAL_ROUTE, cookie=submit.headers["Set-Cookie"])

            self.assertEqual(revisit.status, "200 OK")
            self.assertIn('value="reject:https://example.test/symphony-ticket-evidence" checked', revisit.body)
            self.assertIn('value="approve:https://example.test/designer-intake-research" checked', revisit.body)

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

    def test_ticket_page_prefills_generated_draft_from_synthesis_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(
                OvertureUiApp(store_dir=tmpdir),
                "GET",
                "/ticket",
                cookie=_session_cookie({SESSION_SYNTHESIS_BRIEF_KEY: json.dumps(_synthesis_brief())}),
            )

        self.assertEqual(response.status, "200 OK")
        self.assertIn('<label for="ticket_markdown">Ticket draft</label>', response.body)
        self.assertIn('<textarea id="ticket_markdown" name="ticket_markdown"', response.body)
        self.assertIn("# Add ticket review surface", response.body)
        self.assertIn("## Acceptance criteria", response.body)
        self.assertIn(">Advance to export<", response.body)
        session = _session_from_set_cookie(response.headers["Set-Cookie"])
        self.assertIn(SESSION_TICKET_MARKDOWN_KEY, session)

    def test_synthesis_without_research_result_renders_prerequisite_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            record, _path = create_intake_record(
                "Build useful wizard empty states",
                Path(tmpdir) / "intake",
                author_email="designer@example.com",
            )

            response = _request(
                OvertureUiApp(store_dir=tmpdir),
                "GET",
                "/synthesis",
                cookie=_session_cookie({"intake_id": record.id, "author_email": "designer@example.com"}),
            )

        self.assertEqual(response.status, "200 OK")
        self.assertIn("Complete research approval first", response.body)
        self.assertIn(f'href="{RESEARCH_APPROVAL_ROUTE}"', response.body)
        self.assertIn("Go to research approval", response.body)
        self.assertNotIn("Research result not found", response.body)
        self.assertNotIn("Placeholder for synthesis brief review.", response.body)

    def test_ticket_without_synthesis_brief_renders_prerequisite_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", "/ticket")

        self.assertEqual(response.status, "303 See Other")
        self.assertEqual(response.headers["Location"], "/synthesis")

    def test_ticket_valid_edit_advances_to_export_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            page = _request(
                app,
                "GET",
                "/ticket",
                cookie=_session_cookie({SESSION_SYNTHESIS_BRIEF_KEY: json.dumps(_synthesis_brief())}),
            )
            draft = _session_from_set_cookie(page.headers["Set-Cookie"])[SESSION_TICKET_MARKDOWN_KEY]
            edited = draft.replace("Ticket review page shows generated draft.", "Ticket review page shows edited draft.")

            response = _request(app, "POST", "/ticket", {"ticket_markdown": edited}, cookie=page.headers["Set-Cookie"])

        self.assertEqual(response.status, "303 See Other")
        self.assertEqual(response.headers["Location"], "/export")
        session = _session_from_set_cookie(response.headers["Set-Cookie"])
        self.assertEqual(session[SESSION_TICKET_MARKDOWN_KEY], edited)
        self.assertEqual(session["ticket_title"], "Add ticket review surface")
        self.assertEqual(session["next_route"], "/export")
        self.assertIn('name="action" value="advance"', page.body)
        self.assertNotIn('disabled="disabled"', page.body)

    def test_ticket_invalid_edit_blocks_advance_with_inline_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            page = _request(
                app,
                "GET",
                "/ticket",
                cookie=_session_cookie({SESSION_SYNTHESIS_BRIEF_KEY: json.dumps(_synthesis_brief())}),
            )
            draft = _session_from_set_cookie(page.headers["Set-Cookie"])[SESSION_TICKET_MARKDOWN_KEY]
            broken = draft.replace("## Acceptance criteria", "## Acceptance notes")

            response = _request(app, "POST", "/ticket", {"ticket_markdown": broken}, cookie=page.headers["Set-Cookie"])

        self.assertEqual(response.status, "400 Bad Request")
        self.assertNotIn("Location", response.headers)
        self.assertIn("Use the required section order for this draft", response.body)
        self.assertIn('role="alert"', response.body)
        self.assertIn("## Acceptance notes", response.body)
        self.assertIn('name="action" value="advance" disabled', response.body)

    def test_ticket_invalid_draft_stays_disabled_and_hints_persist_on_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            page = _request(
                app,
                "GET",
                "/ticket",
                cookie=_session_cookie({SESSION_SYNTHESIS_BRIEF_KEY: json.dumps(_synthesis_brief())}),
            )
            draft = _session_from_set_cookie(page.headers["Set-Cookie"])[SESSION_TICKET_MARKDOWN_KEY]
            broken = draft.replace("## Acceptance criteria", "## Acceptance notes")
            invalid = _request(app, "POST", "/ticket", {"ticket_markdown": broken}, cookie=page.headers["Set-Cookie"])
            refreshed = _request(app, "GET", "/ticket", cookie=invalid.headers["Set-Cookie"])

        self.assertEqual(invalid.status, "400 Bad Request")
        self.assertIn('name="action" value="advance" disabled', invalid.body)
        self.assertIn("Use the required section order for this draft", invalid.body)
        self.assertEqual(refreshed.status, "200 OK")
        self.assertIn('name="action" value="advance" disabled', refreshed.body)
        self.assertIn("Use the required section order for this draft", refreshed.body)

    def test_ticket_edits_persist_across_refreshes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            page = _request(
                app,
                "GET",
                "/ticket",
                cookie=_session_cookie({SESSION_SYNTHESIS_BRIEF_KEY: json.dumps(_synthesis_brief())}),
            )
            draft = _session_from_set_cookie(page.headers["Set-Cookie"])[SESSION_TICKET_MARKDOWN_KEY]
            broken = draft.replace("## Validation plan", "## Validation notes")
            invalid = _request(app, "POST", "/ticket", {"ticket_markdown": broken}, cookie=page.headers["Set-Cookie"])

            refreshed = _request(app, "GET", "/ticket", cookie=invalid.headers["Set-Cookie"])

        self.assertEqual(refreshed.status, "200 OK")
        self.assertIn("## Validation notes", refreshed.body)
        self.assertNotIn("## Validation plan", refreshed.body)


class Response:
    def __init__(self, status: str, headers: list[tuple[str, str]], body: str) -> None:
        self.status = status
        self.all_headers = headers
        self.headers = dict(headers)
        self.body = body

    def header_values(self, name: str) -> list[str]:
        return [value for key, value in self.all_headers if key.lower() == name.lower()]


def _request(
    app: OvertureUiApp,
    method: str,
    path: str,
    fields: dict[str, str] | None = None,
    *,
    cookie: str | None = None,
    authenticated: bool = True,
) -> Response:
    encoded = urlencode(fields or {}, doseq=True).encode("utf-8")
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
    if authenticated:
        request_cookie = _merge_cookie(request_cookie, AUTH_COOKIE_NAME, app.auth_manager.issue_session("designer@example.com"))
    if request_cookie:
        environ["HTTP_COOKIE"] = request_cookie

    body = b"".join(app(environ, start_response)).decode("utf-8")
    return Response(str(captured["status"]), list(captured["headers"]), body)


def _session_from_set_cookie(header: str) -> dict[str, str]:
    jar = cookies.SimpleCookie()
    jar.load(header)
    return json.loads(jar[SESSION_COOKIE_NAME].value)


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


def _synthesis_brief() -> dict[str, object]:
    return {
        "problem": "Designers need to review generated ticket Markdown before export.",
        "user_need": "Designers need a fast correction loop inside the wizard.",
        "relevant_evidence": {
            "evidence": [
                {
                    "id": "evidence_ticket_page",
                    "summary": "Ticket review page shows generated draft.",
                    "source_refs": ["node:capability_ticket_draft"],
                }
            ],
            "evidence_backed_claims": [
                {
                    "id": "claim_inline_editing",
                    "statement": "Inline editing prevents context switching.",
                    "confidence": "high",
                    "source_refs": ["node:need_inline_ticket_editing"],
                }
            ],
            "assumptions": [],
        },
        "connected_concepts": [
            {
                "id": "component_ui_ticket_page",
                "type": "Component",
                "label": "Ticket page",
                "summary": "Editable ticket review page.",
                "relationships": ["component_ui_ticket_page -> uses -> capability_ticket_validation"],
            }
        ],
        "proposed_capability": "Render and validate editable ticket Markdown.",
        "risks_uncertainty": ["Validation errors must be visible inline."],
        "open_questions": [],
        "candidate_ticket_breakdown": [
            {
                "id": "ticketcandidate_ticket_review_surface",
                "title": "Add ticket review surface",
                "scope": "Add a textarea-backed ticket review page that validates edits before export.",
                "validation_plan": ["Run `python -m unittest tests.test_ui_intake_page`."],
                "source_node_ids": ["component_ui_ticket_page"],
                "readiness": "ready",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
