import tempfile
import unittest

from overture.ui_host import (
    PEER_ONBOARDING_ROUTE,
    OvertureUiApp,
)
from tests.test_ui_intake_page import _request


class PeerOnboardingPageTests(unittest.TestCase):
    def test_unauthenticated_peer_onboarding_redirects_to_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", PEER_ONBOARDING_ROUTE, authenticated=False)

        self.assertEqual(response.status, "302 Found")
        self.assertEqual(response.headers["Location"], f"/auth/login?next={PEER_ONBOARDING_ROUTE}")

    def test_peer_onboarding_route_renders_designer_one_filled_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            response = _request(OvertureUiApp(store_dir=tmpdir), "GET", PEER_ONBOARDING_ROUTE)

        self.assertEqual(response.status, "200 OK")
        self.assertIn("Designer #1 peer onboarding artifact", response.body)
        self.assertIn("designer_1", response.body)
        self.assertIn("What intake worked", response.body)
        self.assertIn("What research approval looked like", response.body)
        self.assertIn("What to watch out for at each wizard step", response.body)
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
        self.assertLess(first, second)
        self.assertLess(second, third)
        self.assertNotIn("Not filled yet.", response.body)
        self.assertIn("Start from the smallest verb-led intake sentence", response.body)
        self.assertIn("Approve only sources that make the ticket easier to validate", response.body)
        self.assertIn('aria-label="Wizard context"', response.body)


if __name__ == "__main__":
    unittest.main()
