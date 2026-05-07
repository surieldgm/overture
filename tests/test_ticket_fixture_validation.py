import contextlib
from io import StringIO
from pathlib import Path
import tempfile
import time
import unittest

from overture.cli import main
from overture.export import parse_ticket_file
from overture.ticket_fixture_validation import (
    default_ticket_fixture_paths,
    render_ticket_fixture_errors,
    validate_ticket_fixture_paths,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class TicketFixtureValidationTests(unittest.TestCase):
    def test_default_fixture_set_validates_with_parse_ticket_file_under_ci_budget(self) -> None:
        paths = default_ticket_fixture_paths(REPO_ROOT)

        started = time.perf_counter()
        errors = validate_ticket_fixture_paths(paths)
        elapsed = time.perf_counter() - started

        self.assertEqual(errors, [])
        self.assertLess(elapsed, 30.0)
        self.assertIn(REPO_ROOT / "examples" / "overture_mvp_linear_issue_draft.md", paths)
        self.assertEqual(
            sorted(path.name for path in paths if path.parent.name == "intake_examples"),
            [
                "bug-research-approval-latency.md",
                "feature-idea-persistence.md",
                "integration-linear-export-dry-run.md",
            ],
        )

    def test_parse_ticket_file_accepts_embedded_intake_example_ticket(self) -> None:
        parsed = parse_ticket_file(
            REPO_ROOT / "examples" / "intake_examples" / "feature-idea-persistence.md"
        )

        self.assertEqual(parsed.title, "Add idea persistence to Overture")
        self.assertTrue(parsed.description.startswith("## Context\n"))

    def test_intentionally_invalid_fixture_reports_path_and_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalid_path = Path(tmp) / "invalid-ticket.md"
            invalid_path.write_text(
                "\n".join(
                    [
                        "# Missing canonical body",
                        "",
                        "## Context",
                        "",
                        "This fixture omits required ticket sections.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            errors = validate_ticket_fixture_paths([invalid_path])
            rendered = render_ticket_fixture_errors(errors)

        self.assertEqual(len(errors), 1)
        self.assertIn("invalid-ticket.md", rendered)
        self.assertIn("required sections", rendered)

    def test_validate_ticket_fixtures_command_fails_with_offending_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalid_path = Path(tmp) / "invalid-ticket.md"
            invalid_path.write_text("# Bad\n\n## Context\n\nIncomplete.\n", encoding="utf-8")
            stderr = StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = main(["validate-ticket-fixtures", str(invalid_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid-ticket.md", stderr.getvalue())
        self.assertIn("required sections", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
