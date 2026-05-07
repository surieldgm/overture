import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples" / "intake_examples"
EXAMPLE_FILES = (
    EXAMPLES_DIR / "feature-idea-persistence.md",
    EXAMPLES_DIR / "bug-research-approval-latency.md",
    EXAMPLES_DIR / "integration-linear-export-dry-run.md",
)
REQUIRED_SECTIONS = (
    "## Raw Intake",
    "## Research Summary",
    "## Brief",
    "## Ticket",
)


class IntakeExamplesTests(unittest.TestCase):
    def test_curated_intake_examples_exist_and_are_readable(self) -> None:
        for path in EXAMPLE_FILES:
            with self.subTest(path=path.name):
                self.assertTrue(path.exists(), f"missing example file: {path}")
                text = path.read_text(encoding="utf-8")
                self.assertGreater(len(text.strip()), 0)
                for section in REQUIRED_SECTIONS:
                    self.assertIn(section, text)

    def test_curated_intake_examples_cover_distinct_shapes(self) -> None:
        shapes: set[str] = set()
        for path in EXAMPLE_FILES:
            text = path.read_text(encoding="utf-8")
            match = re.search(r"^\*\*Idea shape:\*\*\s*(?P<shape>.+)$", text, re.MULTILINE)
            self.assertIsNotNone(match, f"missing idea shape marker in {path.name}")
            shapes.add(match.group("shape").strip())

        self.assertGreaterEqual(len(shapes), 3)

    def test_curated_intake_examples_include_complete_ticket_drafts(self) -> None:
        ticket_sections = (
            "## Context",
            "## Problem",
            "## Proposed change",
            "## Acceptance criteria",
            "## Validation plan",
            "## Sources / evidence",
            "## Graph provenance",
        )
        for path in EXAMPLE_FILES:
            text = path.read_text(encoding="utf-8")
            ticket = text.split("## Ticket", 1)[1]
            with self.subTest(path=path.name):
                for section in ticket_sections:
                    self.assertIn(section, ticket)


if __name__ == "__main__":
    unittest.main()

