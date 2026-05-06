import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import overture.cli as cli
from overture.fixture import run_overture_fixture
from overture.linear_client import CreatedIssue


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_TICKET = REPO_ROOT / "examples" / "overture_mvp_linear_issue_draft.md"


class StubLinearClient:
    created_issues: list[dict[str, str | None]] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def create_issue(
        self,
        *,
        team_id: str,
        title: str,
        description: str,
        project_id: str | None = None,
    ) -> CreatedIssue:
        issue_number = len(self.created_issues) + 1
        url = f"https://linear.app/eria/issue/ERI-{issue_number}/exported"
        self.created_issues.append(
            {
                "api_key": self.api_key,
                "team_id": team_id,
                "title": title,
                "description": description,
                "project_id": project_id,
                "url": url,
            }
        )
        return CreatedIssue(id=f"issue-id-{issue_number}", identifier=f"ERI-{issue_number}", url=url)


class ExportCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_factory = cli._linear_client_factory
        StubLinearClient.created_issues = []

    def tearDown(self) -> None:
        cli._linear_client_factory = self._original_factory

    def test_dry_run_success_prints_title_and_body_without_network_call(self) -> None:
        cli._linear_client_factory = StubLinearClient

        result = self._run_cli(
            [
                "export",
                str(EXAMPLE_TICKET),
                "--team-id",
                "t",
                "--dry-run",
            ]
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("would create: title=Add graph-context synthesis brief", result.stdout)
        self.assertIn("## Context", result.stdout)
        self.assertNotIn("# Add graph-context synthesis brief", result.stdout)
        self.assertEqual(StubLinearClient.created_issues, [])

    def test_validator_failure_prints_error_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ticket = Path(tmpdir) / "bad.md"
            ticket.write_text("# Add malformed ticket\n\n## Context\n\nOnly context.\n", encoding="utf-8")

            result = self._run_cli(["export", str(ticket), "--team-id", "t", "--dry-run"], cwd=Path(tmpdir))

        self.assertEqual(result.exit_code, 1)
        self.assertIn("required sections must appear in canonical order", result.stderr)

    def test_dry_run_accepts_generated_fixture_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = run_overture_fixture(Path(tmpdir) / "fixture")

            result = self._run_cli(
                [
                    "export",
                    str(artifacts["ticket_draft"]),
                    "--team-id",
                    "team-id",
                    "--dry-run",
                ],
                cwd=Path(tmpdir),
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("would create: title=Add Overture end-to-end fixture", result.stdout)

    def test_missing_ticket_path_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.md"

            result = self._run_cli(["export", str(missing), "--team-id", "t", "--dry-run"], cwd=Path(tmpdir))

        self.assertEqual(result.exit_code, 2)
        self.assertIn("ticket file not found:", result.stderr)

    def test_missing_api_key_exits_2_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ticket = self._copy_example(Path(tmpdir))

            result = self._run_cli(["export", str(ticket), "--team-id", "t"], cwd=Path(tmpdir), env={})

        self.assertEqual(result.exit_code, 2)
        self.assertIn("LINEAR_API_KEY", result.stderr)

    def test_successful_export_uses_stubbed_factory_and_records_ledger_row(self) -> None:
        cli._linear_client_factory = StubLinearClient
        with tempfile.TemporaryDirectory() as tmpdir:
            ticket = self._copy_example(Path(tmpdir))

            result = self._run_cli(
                ["export", str(ticket), "--team-id", "team-id", "--project-id", "project-id"],
                cwd=Path(tmpdir),
                env={"LINEAR_API_KEY": "key"},
            )
            rows = self._ledger_rows(Path(tmpdir))

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "https://linear.app/eria/issue/ERI-1/exported")
        self.assertEqual(len(StubLinearClient.created_issues), 1)
        self.assertEqual(StubLinearClient.created_issues[0]["team_id"], "team-id")
        self.assertEqual(StubLinearClient.created_issues[0]["project_id"], "project-id")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "issue-id-1")

    def test_unmodified_rerun_exits_0_without_new_linear_call(self) -> None:
        cli._linear_client_factory = StubLinearClient
        with tempfile.TemporaryDirectory() as tmpdir:
            ticket = self._copy_example(Path(tmpdir))
            self._run_cli(["export", str(ticket), "--team-id", "t"], cwd=Path(tmpdir), env={"LINEAR_API_KEY": "key"})

            result = self._run_cli(["export", str(ticket), "--team-id", "t"], cwd=Path(tmpdir), env={"LINEAR_API_KEY": "key"})
            rows = self._ledger_rows(Path(tmpdir))

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "already exported: https://linear.app/eria/issue/ERI-1/exported")
        self.assertEqual(len(StubLinearClient.created_issues), 1)
        self.assertEqual(len(rows), 1)

    def test_changed_ticket_exits_3_without_force_recreate(self) -> None:
        cli._linear_client_factory = StubLinearClient
        with tempfile.TemporaryDirectory() as tmpdir:
            ticket = self._copy_example(Path(tmpdir))
            self._run_cli(["export", str(ticket), "--team-id", "t"], cwd=Path(tmpdir), env={"LINEAR_API_KEY": "key"})
            ticket.write_text(ticket.read_text(encoding="utf-8") + "\n<!-- changed -->\n", encoding="utf-8")

            result = self._run_cli(["export", str(ticket), "--team-id", "t"], cwd=Path(tmpdir), env={"LINEAR_API_KEY": "key"})

        self.assertEqual(result.exit_code, 3)
        self.assertIn("ticket changed since last export: https://linear.app/eria/issue/ERI-1/exported", result.stderr)
        self.assertEqual(len(StubLinearClient.created_issues), 1)

    def test_force_recreate_after_change_overwrites_ledger_row(self) -> None:
        cli._linear_client_factory = StubLinearClient
        with tempfile.TemporaryDirectory() as tmpdir:
            ticket = self._copy_example(Path(tmpdir))
            self._run_cli(["export", str(ticket), "--team-id", "t"], cwd=Path(tmpdir), env={"LINEAR_API_KEY": "key"})
            ticket.write_text(ticket.read_text(encoding="utf-8") + "\n<!-- changed -->\n", encoding="utf-8")

            result = self._run_cli(
                ["export", str(ticket), "--team-id", "t", "--force-recreate"],
                cwd=Path(tmpdir),
                env={"LINEAR_API_KEY": "key"},
            )
            rows = self._ledger_rows(Path(tmpdir))

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "https://linear.app/eria/issue/ERI-2/exported")
        self.assertEqual(len(StubLinearClient.created_issues), 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "issue-id-2")
        self.assertEqual(rows[0][3], "https://linear.app/eria/issue/ERI-2/exported")

    def _copy_example(self, tmpdir: Path) -> Path:
        ticket = tmpdir / "ticket.md"
        ticket.write_text(EXAMPLE_TICKET.read_text(encoding="utf-8"), encoding="utf-8")
        return ticket

    def _ledger_rows(self, tmpdir: Path) -> list[tuple[str, str, str, str]]:
        with sqlite3.connect(tmpdir / ".overture" / "exports.sqlite") as connection:
            return list(
                connection.execute(
                    "SELECT ticket_path, ticket_hash, linear_issue_id, linear_url FROM exports ORDER BY ticket_path"
                )
            )

    def _run_cli(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> "_CliResult":
        stdout = io.StringIO()
        stderr = io.StringIO()
        original_cwd = Path.cwd()
        patch_env = patch.dict(os.environ, env if env is not None else {}, clear=env is not None)
        try:
            if cwd is not None:
                os.chdir(cwd)
            with patch_env, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = cli.main(argv)
        finally:
            os.chdir(original_cwd)
        return _CliResult(exit_code=exit_code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


class _CliResult:
    def __init__(self, *, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


if __name__ == "__main__":
    unittest.main()
