import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import overture.cli as cli
from overture.fixture import PipelineStageError, run_overture_fixture, validate_ticket_draft


class RunCliTests(unittest.TestCase):
    def test_run_command_prints_ticket_draft_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_cli(
                [
                    "run",
                    "Collapse designer intake into a Symphony-ready ticket",
                    "--output-dir",
                    tmpdir,
                ]
            )

            ticket_path = Path(result.stdout.strip())
            self.assertEqual(result.exit_code, 0)
            self.assertTrue(ticket_path.exists(), ticket_path)
            self.assertEqual(ticket_path.name, "symphony-ticket-draft.md")
            validate_ticket_draft(ticket_path.read_text(encoding="utf-8"))

    def test_run_command_reuses_fixture_pipeline_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ticket_path = Path(tmpdir) / "ticket" / "symphony-ticket-draft.md"
            with mock.patch.object(
                cli,
                "run_overture_fixture",
                return_value={"run_id": "run-1", "ticket_draft": ticket_path},
            ) as fixture:
                result = self._run_cli(["run", "Raw idea", "--output-dir", tmpdir])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), str(ticket_path))
        fixture.assert_called_once_with(Path(tmpdir), idea="Raw idea", stop_at_stage=None)

    def test_run_command_stop_at_stage_prints_stage_artifact_and_skips_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_cli(
                [
                    "run",
                    "Stop after synthesis for inspection",
                    "--output-dir",
                    tmpdir,
                    "--stop-at-stage",
                    "synthesis",
                ]
            )

            base_dir = Path(tmpdir)
            synthesis_path = base_dir / "synthesis" / "synthesis-brief.json"
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.stdout.strip(), str(synthesis_path))
            self.assertTrue(synthesis_path.exists())
            self.assertFalse((base_dir / "ticket" / "symphony-ticket-draft.md").exists())

    def test_run_command_stop_at_stage_accepts_ticket_draft_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_cli(
                [
                    "run",
                    "Stop at ticket draft",
                    "--output-dir",
                    tmpdir,
                    "--stop-at-stage",
                    "ticket-draft",
                ]
            )

            ticket_path = Path(tmpdir) / "ticket" / "symphony-ticket-draft.md"
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.stdout.strip(), str(ticket_path))
            self.assertTrue(ticket_path.exists())

    def test_run_command_export_flag_delegates_to_existing_export_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(cli, "_export_ticket", return_value=0) as export:
                result = self._run_cli(
                    [
                        "run",
                        "Export this ticket draft",
                        "--output-dir",
                        tmpdir,
                        "--export",
                        "--team-id",
                        "team-id",
                        "--project-id",
                        "project-id",
                        "--ledger-db",
                        str(Path(tmpdir) / "exports.sqlite"),
                    ]
                )

            ticket_path = Path(tmpdir) / "ticket" / "symphony-ticket-draft.md"

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), str(ticket_path))
        export.assert_called_once()
        export_args = export.call_args.args[0]
        self.assertEqual(export_args.ticket_path, ticket_path)
        self.assertEqual(export_args.team_id, "team-id")
        self.assertEqual(export_args.project_id, "project-id")

    def test_run_command_names_failing_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                cli,
                "run_overture_fixture",
                side_effect=PipelineStageError("research", "no approved sources"),
            ):
                result = self._run_cli(["run", "Raw idea", "--output-dir", tmpdir])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("run failed at research: no approved sources", result.stderr)

    def test_fixture_stop_at_stage_writes_only_upstream_artifacts(self) -> None:
        stop_expectations = {
            "intake": ("intake",),
            "research": ("intake", "research"),
            "graph": ("intake", "research", "graph"),
            "synthesis": ("intake", "research", "graph", "synthesis"),
            "ticket_draft": ("intake", "research", "graph", "synthesis", "ticket"),
        }
        expected_paths = {
            "research": Path("research") / "research-notes.json",
            "graph": Path("graph") / "graph-records.json",
            "synthesis": Path("synthesis") / "synthesis-brief.json",
            "ticket": Path("ticket") / "symphony-ticket-draft.md",
        }
        for stage, expected_dirs in stop_expectations.items():
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmpdir:
                artifacts = run_overture_fixture(tmpdir, stop_at_stage=stage)
                base_dir = Path(tmpdir)

                self.assertIn(stage, artifacts)
                for directory in expected_dirs:
                    self.assertTrue((base_dir / directory).exists(), directory)
                for directory in {"research", "graph", "synthesis", "ticket"} - set(expected_dirs):
                    self.assertFalse((base_dir / directory).exists(), directory)
                for directory, relative_path in expected_paths.items():
                    if directory in expected_dirs:
                        self.assertTrue((base_dir / relative_path).exists(), relative_path)
                    else:
                        self.assertFalse((base_dir / relative_path).exists(), relative_path)

                if stage == "intake":
                    intake_path = Path(artifacts["intake"])
                    self.assertEqual(json.loads(intake_path.read_text(encoding="utf-8"))["source_type"], "fixture")

    def _run_cli(self, argv: list[str]) -> "_CliResult":
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), mock.patch.dict(os.environ, {}, clear=True):
            exit_code = cli.main(argv)
        return _CliResult(exit_code=exit_code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


class _CliResult:
    def __init__(self, *, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


if __name__ == "__main__":
    unittest.main()
