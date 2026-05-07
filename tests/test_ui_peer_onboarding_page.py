import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from overture.auth import AUTH_COOKIE_NAME
from overture.intake import load_intake_record
from overture.peer_onboarding import initialize_peer_onboarding_template
from overture.ui_host import (
    PEER_ONBOARDING_ROUTE,
    RESEARCH_APPROVAL_ROUTE,
    SESSION_PEER_ONBOARDING_TEMPLATE_KEY,
    OvertureUiApp,
)
from tests.test_ui_intake_page import _merge_cookie, _request, _session_cookie, _session_from_set_cookie


class PeerOnboardingPageTests(unittest.TestCase):
    def test_unauthenticated_peer_onboarding_redirects_to_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", PEER_ONBOARDING_ROUTE, authenticated=False)

        self.assertEqual(response.status, "302 Found")
        self.assertEqual(response.headers["Location"], f"/auth/login?next={PEER_ONBOARDING_ROUTE}")

    def test_peer_onboarding_route_initializes_empty_template_for_author(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", PEER_ONBOARDING_ROUTE)

        self.assertEqual(response.status, "200 OK")
        self.assertIn("Peer onboarding", response.body)
        self.assertIn("What intake worked", response.body)
        self.assertIn("What research approval looked like", response.body)
        self.assertIn("What to watch out for at each wizard step", response.body)
        self.assertIn("Not filled yet.", response.body)
        session = _session_from_set_cookie(response.headers["Set-Cookie"])
        template = json.loads(session[SESSION_PEER_ONBOARDING_TEMPLATE_KEY])
        self.assertEqual(template["author"]["email"], "designer@example.com")

    def test_filled_peer_onboarding_template_renders_in_schema_order(self) -> None:
        template = initialize_peer_onboarding_template("designer-1", "designer-1@example.test")
        template["sections"][0]["fields"][0]["value"] = "Start from a concrete customer-facing session."
        template["sections"][0]["fields"][1]["value"] = ["Use the shortest recent support quote."]
        template["sections"][1]["fields"][0]["value"] = "Approve sources only after checking the claim against the artifact."
        template["sections"][2]["fields"][0]["value"][0]["note"] = "Keep the intake under the text cap."
        cookie = _session_cookie({SESSION_PEER_ONBOARDING_TEMPLATE_KEY: json.dumps(template)})

        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", PEER_ONBOARDING_ROUTE, cookie=cookie)

        self.assertEqual(response.status, "200 OK")
        first = response.body.index("What intake worked")
        second = response.body.index("What research approval looked like")
        third = response.body.index("What to watch out for at each wizard step")
        self.assertLess(first, second)
        self.assertLess(second, third)
        self.assertIn("Start from a concrete customer-facing session.", response.body)
        self.assertIn("Use the shortest recent support quote.", response.body)
        self.assertIn("Approve sources only after checking the claim against the artifact.", response.body)
        self.assertIn("Keep the intake under the text cap.", response.body)
        self.assertIn('aria-label="Wizard context"', response.body)

    def test_non_author_designer_reads_peer_artifact_and_reaches_research_approval(self) -> None:
        artifact = _designer_one_filled_artifact()
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            designer_two_auth = app.auth_manager.issue_session("designer-2@example.test")
            designer_two_cookie = _designer_cookie(
                designer_two_auth,
                {SESSION_PEER_ONBOARDING_TEMPLATE_KEY: json.dumps(artifact, sort_keys=True, separators=(",", ":"))},
            )

            viewer = _request(app, "GET", PEER_ONBOARDING_ROUTE, cookie=designer_two_cookie, authenticated=False)

            self.assertEqual(viewer.status, "200 OK")
            self.assertIn("authored by <code>designer-1@example.test</code>", viewer.body)
            self.assertIn("Start with the active onboarding viewer session", viewer.body)

            synthetic_intake = _synthetic_intake_from_peer_artifact(viewer.body)
            viewer_cookie = _merge_cookie(viewer.headers["Set-Cookie"], AUTH_COOKIE_NAME, designer_two_auth)
            intake = _request(app, "POST", "/intake", {"idea": synthetic_intake}, cookie=viewer_cookie, authenticated=False)

            self.assertEqual(intake.status, "303 See Other")
            self.assertEqual(intake.headers["Location"], RESEARCH_APPROVAL_ROUTE)

            session = _session_from_set_cookie(intake.headers["Set-Cookie"])
            self.assertEqual(session["user_id"], "designer-2@example.test")
            self.assertEqual(session["user_email"], "designer-2@example.test")
            self.assertEqual(session["designer_email"], "designer-2@example.test")
            intake_record = load_intake_record(Path(tmpdir) / "intake" / f"{session['intake_id']}.json")
            self.assertEqual(intake_record.author_id, "designer-2@example.test")
            self.assertEqual(intake_record.author_email, "designer-2@example.test")
            self.assertIn("Start with the active onboarding viewer session", intake_record.raw_text)

            intake_cookie = _merge_cookie(intake.headers["Set-Cookie"], AUTH_COOKIE_NAME, designer_two_auth)
            approval = _request(app, "GET", RESEARCH_APPROVAL_ROUTE, cookie=intake_cookie, authenticated=False)
            self.assertEqual(approval.status, "200 OK")
            self.assertIn("Research approval", approval.body)
            self.assertIn(session["intake_id"], approval.body)
            self.assertIn("Approve", approval.body)
            self.assertIn("Reject", approval.body)


def _designer_one_filled_artifact() -> dict[str, object]:
    template = initialize_peer_onboarding_template("designer-1", "designer-1@example.test")
    template["sections"][0]["fields"][0]["value"] = (
        "Start with the active onboarding viewer session, name the designer handoff gap, "
        "and keep the first intake scoped to reaching research approval."
    )
    template["sections"][0]["fields"][1]["value"] = [
        "Validate that a second designer can turn the peer artifact into a first intake without founder narration.",
        "Use the viewer route notes as the source of truth before writing the intake.",
    ]
    template["sections"][1]["fields"][0]["value"] = (
        "The first pass should stop once suggested sources are visible for approval."
    )
    template["sections"][1]["fields"][1]["value"] = [
        "Sources should explain the artifact-to-intake handoff.",
        "Sources should stay local to the smoke run.",
    ]
    template["sections"][2]["fields"][0]["value"][0]["note"] = (
        "For Intake, write one concrete workflow request under the text limit and include the handoff gap."
    )
    template["sections"][2]["fields"][0]["value"][1]["note"] = (
        "For Research, confirm the approval page loads and candidate sources are present."
    )
    return template


def _designer_cookie(auth_token: str, session: dict[str, str]) -> str:
    return _merge_cookie(_session_cookie(session), AUTH_COOKIE_NAME, auth_token)


def _synthetic_intake_from_peer_artifact(body: str) -> str:
    visible_text = _visible_text(body)
    required_heuristics = [
        "Useful intake pattern",
        "Example prompts",
        "Wizard step notes",
        "Start with the active onboarding viewer session",
        "second designer can turn the peer artifact into a first intake",
        "For Intake, write one concrete workflow request",
        "For Research, confirm the approval page loads",
    ]
    missing = [heuristic for heuristic in required_heuristics if heuristic not in visible_text]
    if missing:
        raise AssertionError(f"peer artifact did not yield passable first-intake heuristics: missing {missing!r}")

    return (
        "Validate the peer artifact handoff for Designer 2. "
        "Start with the active onboarding viewer session, use the viewer route notes as the source of truth, "
        "and prove a second designer can turn the artifact into a first intake without founder narration. "
        "Scope the request to reaching research approval with local candidate sources visible."
    )


def _visible_text(body: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(body)
    return " ".join(parser.text_parts)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.text_parts.append(text)


if __name__ == "__main__":
    unittest.main()
