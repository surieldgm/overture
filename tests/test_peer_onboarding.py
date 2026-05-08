import unittest

from overture.peer_onboarding import (
    PEER_ONBOARDING_SCHEMA,
    PEER_ONBOARDING_SCHEMA_VERSION,
    initialize_peer_onboarding_template,
    ordered_peer_onboarding_sections,
)


class PeerOnboardingTemplateTests(unittest.TestCase):
    def test_initialize_empty_template_for_author(self) -> None:
        template = initialize_peer_onboarding_template("designer-1", "designer-1@example.test")

        self.assertEqual(template["schema_version"], PEER_ONBOARDING_SCHEMA_VERSION)
        self.assertEqual(template["author"], {"id": "designer-1", "email": "designer-1@example.test"})
        self.assertEqual([section["id"] for section in template["sections"]], [section["id"] for section in PEER_ONBOARDING_SCHEMA])
        intake_section = template["sections"][0]
        self.assertEqual(intake_section["title"], "What intake worked")
        self.assertEqual(intake_section["fields"][0]["kind"], "free_text")
        self.assertEqual(intake_section["fields"][0]["value"], "")
        self.assertEqual(intake_section["fields"][1]["kind"], "list_text")
        self.assertEqual(intake_section["fields"][1]["value"], [])

        watchouts = template["sections"][2]["fields"][0]
        self.assertEqual(watchouts["kind"], "wizard_step_notes")
        self.assertEqual([item["step"] for item in watchouts["value"]], ["Intake", "Research", "Synthesis", "Ticket", "Export"])
        self.assertTrue(all(item["note"] == "" for item in watchouts["value"]))
        sprint5 = template["sections"][3]
        self.assertEqual(sprint5["id"], "sprint5_observation_patterns")
        self.assertEqual(sprint5["fields"][0]["source_node"], "component_observation_log")

    def test_ordered_sections_tolerates_future_extension(self) -> None:
        template = initialize_peer_onboarding_template("designer-1", "designer-1@example.test")
        template["sections"].append(
            {
                "id": "future_visual_references",
                "order": 5,
                "title": "Future visual references",
                "description": "A later schema can add optional screenshots.",
                "fields": [{"id": "links", "label": "Links", "kind": "list_text", "value": ["mockup.png"]}],
            }
        )

        ordered = ordered_peer_onboarding_sections(template)

        self.assertEqual(ordered[-1]["id"], "future_visual_references")
        self.assertEqual(len(ordered), 5)


if __name__ == "__main__":
    unittest.main()
