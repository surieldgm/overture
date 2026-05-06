import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from overture import cli
from overture.linear_client import CreatedIssue


EXAMPLE_TICKET = Path("examples/overture_mvp_linear_issue_draft.md")


class ExportCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_factory = cli._linear_client_factory

    def tearDown(self) -> None:
        cli._linear_client_factory = self._original_factory

    def test_dry_run_success_prints_title_and_body(self) -> None:
        result, stdout, stderr = self._run_cli(
            [
                "export",
                str(EXAMPLE_TICKET),
                "--team-id",
                "t",
                "--dry-run",
            ]
        )

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("would create: title=Add graph-context synthesis brief", stdout)
        self.assertIn("## Context", stdout)
        self.assertNotIn("# Add graph-context synthesis brief\n\n## Context", stdout)

    def test_validator_failure_prints_missing_section_error(self) -> None:
        malformed = EXAMPLE_TICKET.read_text(encoding="utf-8").replace(
            "## Graph provenance",
            "## Removed provenance",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "malformed.md"
            path.write_text(malformed, encoding="utf-8")

            result, stdout, stderr = self._run_cli(
                [
                    "export",
                    str(path),
                    "--team-id",
                    "t",
                    "--dry-run",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("required sections cannot be empty: ## Graph provenance", stderr)

    def test_missing_api_key_exits_two_and_names_variable(self) -> None:
        result, stdout, stderr = self._run_cli(
            [
                "export",
                str(EXAMPLE_TICKET),
                "--team-id",
                "t",
            ],
            env={"LINEAR_API_KEY": None},
        )

        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertIn("LINEAR_API_KEY", stderr)

    def test_dry_run_does_not_create_linear_client(self) -> None:
        calls = []

        def factory(api_key: str):
            calls.append(api_key)
            raise AssertionError("dry-run should not create a Linear client")

        cli._linear_client_factory = factory

        result, _stdout, _stderr = self._run_cli(
            [
                "export",
                str(EXAMPLE_TICKET),
                "--team-id",
                "t",
                "--dry-run",
            ],
            env={"LINEAR_API_KEY": "key"},
        )

        self.assertEqual(result, 0)
        self.assertEqual(calls, [])

    def test_successful_export_uses_stubbed_factory(self) -> None:
        calls = []

        class StubClient:
            def create_issue(self, **kwargs):
                calls.append(kwargs)
                return CreatedIssue(
                    id="issue-id",
                    identifier="ERI-99",
                    url="https://linear.app/eria/issue/ERI-99/exported",
                )

        def factory(api_key: str):
            calls.append({"api_key": api_key})
            return StubClient()

        cli._linear_client_factory = factory

        result, stdout, stderr = self._run_cli(
            [
                "export",
                str(EXAMPLE_TICKET),
                "--team-id",
                "team-id",
                "--project-id",
                "project-id",
            ],
            env={"LINEAR_API_KEY": "secret"},
        )

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.strip(), "https://linear.app/eria/issue/ERI-99/exported")
        self.assertEqual(calls[0], {"api_key": "secret"})
        self.assertEqual(calls[1]["team_id"], "team-id")
        self.assertEqual(calls[1]["title"], "Add graph-context synthesis brief")
        self.assertTrue(calls[1]["description"].startswith("## Context"))
        self.assertEqual(calls[1]["project_id"], "project-id")

    def _run_cli(
        self,
        argv: list[str],
        *,
        env: dict[str, str | None] | None = None,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        original_env = {key: os.environ.get(key) for key in (env or {})}
        try:
            for key, value in (env or {}).items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = cli.main(argv)
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        return result, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
