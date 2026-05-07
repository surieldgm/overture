import io
import json
import tempfile
import unittest
from http import cookies
from pathlib import Path
from urllib.parse import urlencode

from overture.auth import auth_cookie
from overture.intake import load_intake_record
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
        self.assertEqual(response.headers["Location"], "/login?next=/intake")

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
        self.assertIn('<textarea id="ticket_markdown" name="ticket_markdown"', response.body)
        self.assertIn("# Add ticket review surface", response.body)
        self.assertIn("## Acceptance criteria", response.body)
        session = _session_from_set_cookie(response.headers["Set-Cookie"])
        self.assertIn(SESSION_TICKET_MARKDOWN_KEY, session)

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
        self.assertIn("required sections must appear in canonical order", response.body)
        self.assertIn('role="alert"', response.body)
        self.assertIn("## Acceptance notes", response.body)

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
        self.headers = dict(headers)
        self.body = body


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
    if authenticated:
        environ["HTTP_COOKIE"] = _with_auth_cookie(cookie)
    elif cookie:
        environ["HTTP_COOKIE"] = cookie

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


def _with_auth_cookie(cookie: str | None, user_id: str = "designer-1") -> str:
    login_cookie = auth_cookie(user_id, email=f"{user_id}@example.test")
    return f"{cookie}; {login_cookie}" if cookie else login_cookie


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
