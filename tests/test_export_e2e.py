import contextlib
import importlib
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from overture.fixture import run_overture_fixture
from overture.linear_client import CreatedIssue, LinearClient


class StubLinearClient:
    def __init__(self) -> None:
        self.calls = []

    def create_issue(self, *, team_id, title, description, project_id=None):
        self.calls.append(
            {
                "team_id": team_id,
                "title": title,
                "description": description,
                "project_id": project_id,
            }
        )
        return CreatedIssue(
            id="issue-1",
            identifier="ERI-999",
            url="https://linear.app/eria/issue/ERI-999/export-smoke",
        )


class ExportE2ETests(unittest.TestCase):
    def test_export_fixture_ticket_creates_ledger_row_and_is_idempotent(self) -> None:
        from overture import cli

        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            run_overture_fixture(temp / "run", idea="Sprint 2 export smoke test")
            ticket_path = temp / "run" / "ticket" / "symphony-ticket-draft.md"
            ledger_path = temp / ".overture" / "exports.sqlite"
            stub = StubLinearClient()

            with mock.patch.dict(os.environ, {"OVERTURE_HOME": str(temp)}):
                with mock.patch.object(cli, "_linear_client_factory", return_value=stub):
                    first_stdout = io.StringIO()
                    with contextlib.redirect_stdout(first_stdout):
                        first_exit_code = cli.main(["export", str(ticket_path), "--team-id", "team-1"])

                    self.assertEqual(first_exit_code, 0, "first export CLI exit code should be 0")
                    self.assertEqual(len(stub.calls), 1, "stub should be called exactly once on first export")
                    self.assertEqual(
                        stub.calls[0]["title"],
                        "Add Overture end-to-end fixture",
                        "export should pass the parsed ticket title to Linear",
                    )
                    self.assertTrue(
                        stub.calls[0]["description"].startswith("## Context"),
                        "export description should begin with the Context section",
                    )
                    self.assertTrue(ledger_path.exists(), "export ledger DB should be created under OVERTURE_HOME")
                    self.assertIn(
                        "https://linear.app/eria/issue/ERI-999/export-smoke",
                        first_stdout.getvalue(),
                        "first export stdout should include the created Linear URL",
                    )

                    rows = _ledger_rows(ledger_path)
                    self.assertEqual(len(rows), 1, "ledger should contain exactly one export row")
                    self.assertEqual(
                        rows[0]["linear_url"],
                        "https://linear.app/eria/issue/ERI-999/export-smoke",
                        "ledger linear_url should match the created issue URL",
                    )

                    second_stdout = io.StringIO()
                    with contextlib.redirect_stdout(second_stdout):
                        second_exit_code = cli.main(["export", str(ticket_path), "--team-id", "team-1"])

                    self.assertEqual(second_exit_code, 0, "second export CLI exit code should be 0")
                    self.assertEqual(
                        len(stub.calls),
                        1,
                        "stub call count should remain unchanged when ticket was already exported",
                    )
                    self.assertIn(
                        "already exported",
                        second_stdout.getvalue(),
                        "second export stdout should explain that the ticket was already exported",
                    )

    def test_default_linear_client_factory_returns_real_client(self) -> None:
        from overture import cli

        fresh_cli = importlib.reload(cli)
        with mock.patch.dict(os.environ, {"LINEAR_API_KEY": "test-key"}):
            self.assertIsInstance(
                fresh_cli._linear_client_factory(),
                LinearClient,
                "default CLI factory should return a real LinearClient when not overridden",
            )


def _ledger_rows(path: Path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute("SELECT * FROM exports"))
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
