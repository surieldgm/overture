import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from overture.auth import AUTH_COOKIE_NAME
from overture.intake import load_intake_record
from overture.ui_host import (
    PEER_ONBOARDING_ROUTE,
    RESEARCH_APPROVAL_ROUTE,
    OvertureUiApp,
)
from tests.test_ui_intake_page import _merge_cookie, _request, _session_from_set_cookie


class PeerOnboardingPageTests(unittest.TestCase):
    def test_unauthenticated_peer_onboarding_redirects_to_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", PEER_ONBOARDING_ROUTE, authenticated=False)

        self.assertEqual(response.status, "302 Found")
        self.assertEqual(response.headers["Location"], f"/auth/login?next={PEER_ONBOARDING_ROUTE}")

    def test_peer_onboarding_route_renders_latest_second_generation_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", PEER_ONBOARDING_ROUTE)

        self.assertEqual(response.status, "200 OK")
        self.assertIn("Designer #1 + Designer #2 peer onboarding artifact for Designer #3", response.body)
        self.assertIn("Designer #1", response.body)
        self.assertIn("Designer #2", response.body)
        self.assertIn("Generation 2", response.body)
        self.assertIn("Generation 1", response.body)
        self.assertIn("Designer #1 peer onboarding artifact", response.body)
        self.assertIn("designer_3", response.body)
        self.assertIn("What intake worked", response.body)
        self.assertIn("What research approval looked like", response.body)
        self.assertIn("What to watch out for at each wizard step", response.body)
        self.assertIn("Sprint 5 observation patterns to carry forward", response.body)
        self.assertIn("Add idea persistence to Overture", response.body)
        self.assertIn("Original intake examples", response.body)
        self.assertIn('aria-label="Wizard context"', response.body)

    def test_filled_peer_onboarding_template_renders_in_schema_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", PEER_ONBOARDING_ROUTE)

        self.assertEqual(response.status, "200 OK")
        first = response.body.index("What intake worked")
        second = response.body.index("What research approval looked like")
        third = response.body.index("What to watch out for at each wizard step")
        fourth = response.body.index("Sprint 5 observation patterns to carry forward")
        self.assertLess(first, second)
        self.assertLess(second, third)
        self.assertLess(third, fourth)
        self.assertNotIn("Not filled yet.", response.body)
        self.assertIn("verb-led intake pattern still works", response.body)
        self.assertIn("source approval expectations must be stated before review", response.body)
        self.assertIn("losing the raw intake wording across transitions", response.body)
        self.assertIn('aria-label="Wizard context"', response.body)

    def test_designer_three_reads_latest_peer_artifact_and_reaches_research_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = OvertureUiApp(store_dir=tmpdir)
            designer_three_auth = app.auth_manager.issue_session("designer-3@example.test")
            designer_three_cookie = _merge_cookie(None, AUTH_COOKIE_NAME, designer_three_auth)

            viewer = _request(app, "GET", PEER_ONBOARDING_ROUTE, cookie=designer_three_cookie, authenticated=False)

            self.assertEqual(viewer.status, "200 OK")
            self.assertIn("Designer #1 + Designer #2 peer onboarding artifact for Designer #3", viewer.body)
            self.assertIn("verb-led intake pattern still works", viewer.body)
            self.assertIn("Sprint 5 observations from Designer #2", viewer.body)

            synthetic_intake = _synthetic_intake_from_peer_artifact(viewer.body)
            intake = _request(
                app,
                "POST",
                "/intake",
                {"idea": synthetic_intake},
                cookie=designer_three_cookie,
                authenticated=False,
            )

            self.assertEqual(intake.status, "303 See Other")
            self.assertEqual(intake.headers["Location"], RESEARCH_APPROVAL_ROUTE)

            session = _session_from_set_cookie(intake.headers["Set-Cookie"])
            self.assertEqual(session["user_id"], "designer-3@example.test")
            self.assertEqual(session["user_email"], "designer-3@example.test")
            self.assertEqual(session["designer_email"], "designer-3@example.test")
            intake_record = load_intake_record(Path(tmpdir) / "intake" / f"{session['intake_id']}.json")
            self.assertEqual(intake_record.author_id, "designer-3@example.test")
            self.assertEqual(intake_record.author_email, "designer-3@example.test")
            self.assertIn("Designer 3 can use the second-generation peer artifact", intake_record.raw_text)

            intake_cookie = _merge_cookie(intake.headers["Set-Cookie"], AUTH_COOKIE_NAME, designer_three_auth)
            approval = _request(app, "GET", RESEARCH_APPROVAL_ROUTE, cookie=intake_cookie, authenticated=False)
            self.assertEqual(approval.status, "200 OK")
            self.assertIn("Research approval", approval.body)
            self.assertIn(session["intake_id"], approval.body)
            self.assertIn("Approve", approval.body)
            self.assertIn("Reject", approval.body)


def _synthetic_intake_from_peer_artifact(body: str) -> str:
    visible_text = _visible_text(body)
    required_heuristics = [
        "Useful intake pattern",
        "Example prompts",
        "Wizard step notes",
        "Observation pattern summary",
        "Designer #1's verb-led intake pattern still works",
        "source approval expectations must be stated before review",
        "Turn every app-facing recommendation into a visible route check plus a unittest command",
    ]
    missing = [heuristic for heuristic in required_heuristics if heuristic not in visible_text]
    if missing:
        raise AssertionError(f"peer artifact did not yield passable first-intake heuristics: missing {missing!r}")

    return (
        "Validate the peer artifact handoff for Designer 3. "
        "Designer 3 can use the second-generation peer artifact to keep raw intake wording visible, "
        "state source approval expectations before review, and turn app-facing recommendations into a visible "
        "route check plus a unittest command. Scope the request to reaching research approval with local candidate "
        "sources visible."
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
