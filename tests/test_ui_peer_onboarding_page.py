import json
import tempfile
import unittest

from overture.peer_onboarding import initialize_peer_onboarding_template
from overture.ui_host import (
    PEER_ONBOARDING_ROUTE,
    SESSION_PEER_ONBOARDING_TEMPLATE_KEY,
    OvertureUiApp,
)
from tests.test_ui_intake_page import _request, _session_cookie, _session_from_set_cookie


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


if __name__ == "__main__":
    unittest.main()
