"""Persona smoke test for research approval persistence.

Cited report context:
- docs/user-tests/2026-05-07-personas.md
- docs/user-tests/2026-05-08-personas-with-codex.md

This test validates that the three persona-intake paths reach research complete
without manual intervention in a single POST cycle using deterministic LLM output.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

from overture.ui_host import RESEARCH_APPROVAL_ROUTE, RESEARCH_COMPLETE_ROUTE
from tests.test_research_approval_session import (
    BrowserLikeClient,
    _five_large_source_client,
    _login_with_magic_link,
    _session_cookie_payload,
    _test_auth,
)
from tests.test_ui_wizard_smoke import _running_server


class ThreePersonaResearchSaveSmokeTests(unittest.TestCase):
    personas = (
        {
            "name": "Carla",
            "email": "carla@dogfood.test",
            "idea": "Add session metadata to the peer onboarding template so Designer #1 can leave timestamps, tools used, and example screen recordings for Designer #2 instead of handing off a generic empty form.",
        },
        {
            "name": "Tomás",
            "email": "tomas@overture.test",
            "idea": "Show a sidebar of recent intakes on the wizard so I can reuse phrasing from past ideas instead of starting from a blank page every time.",
        },
        {
            "name": "Rocío",
            "email": "rocio@startup.test",
            "idea": "Send a weekly digest email to onboarded users summarizing what they did in the product that week. The digest should highlight 2-3 specific things they did and gently remind them of the next step in onboarding.",
        },
    )

    def test_persona_smoke_get_post_research_approval_save(self) -> None:
        summary: list[dict[str, object]] = []
        for persona in self.personas:
            with self.subTest(persona=persona["name"]), tempfile.TemporaryDirectory() as tmpdir:
                store_dir = Path(tmpdir)
                browser = BrowserLikeClient(cookie_limit_bytes=999_999)
                auth = _test_auth(store_dir)
                with _running_server(store_dir=store_dir, llm_client=_five_large_source_client, auth_manager=auth) as base_url:
                    _login_with_magic_link(browser, base_url, store_dir, persona["email"])
                    intake = browser.post(
                        base_url,
                        "/intake",
                        {"idea": persona["idea"]},
                    )
                    self.assertEqual(intake.status, 303)
                    approval = browser.get(base_url, RESEARCH_APPROVAL_ROUTE)
                    self.assertEqual(approval.status, 200)
                    self.assertIn('class="source-list"', approval.body)

                    approved_fields = {
                        name: f"approve:{value}"
                        for name, value in re.findall(r'name="(decision-\d+)" value="approve:([^"]+)"', approval.body)
                    }
                    self.assertTrue(approved_fields)
                    response = browser.post(base_url, RESEARCH_APPROVAL_ROUTE, approved_fields)
                    self.assertEqual(response.status, 303)
                    self.assertEqual(response.header_map["Location"], RESEARCH_COMPLETE_ROUTE)

                    complete = browser.get(base_url, RESEARCH_COMPLETE_ROUTE)
                    self.assertEqual(complete.status, 200)
                    self.assertIn("Research saved", complete.body)

                intake_session = _session_cookie_payload(intake.header_map["Set-Cookie"])
                intake_id = str(intake_session["intake_id"])
                research_path = store_dir / "research" / f"{intake_id}.json"
                self.assertTrue(research_path.exists())
                research = json.loads(research_path.read_text(encoding="utf-8"))
                items = research.get("items", [])
                self.assertTrue(items, f"No persisted research items for {persona['name']}")

                summary.append(
                    {
                        "persona": persona["name"],
                        "intake_id": intake_id,
                        "saved_items": len(items),
                        "research_file": str(research_path),
                        "status": response.header_map["Location"],
                    }
                )

        print(
            "THREE_PERSONA_RESEARCH_SAVE_SUMMARY="
            + json.dumps(summary, sort_keys=True)
        )


if __name__ == "__main__":
    unittest.main()
