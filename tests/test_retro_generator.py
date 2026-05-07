import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

import overture.cli as cli
from overture.friction_log import FrictionLog
from overture.metrics_store import MetricsStore, StageMetric
from overture.retro_generator import generate_retro_document


class RetroGeneratorTests(unittest.TestCase):
    def test_empty_friction_log_produces_obviously_empty_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            output_path = Path(tmpdir) / "retro.md"
            MetricsStore(db_path).record(
                _metric(
                    run_id="run-1",
                    stage_name="research",
                    started_at="2026-05-01T10:00:00.000000Z",
                    duration_ms=100,
                    status="success",
                )
            )

            generated = generate_retro_document(
                db_path=db_path,
                output_path=output_path,
                milestone="M1",
                started_at="2026-05-01T00:00:00.000000Z",
                completed_at="2026-05-02T00:00:00.000000Z",
            )
            text = generated.read_text(encoding="utf-8")

        self.assertEqual(generated, output_path)
        self.assertIn("# M1 Retrospective", text)
        self.assertIn("Friction entries in window: 0", text)
        self.assertIn("_No entries._", text)
        self.assertIn("Dependency: this artifact only reflects frictions and metrics captured", text)

    def test_populated_friction_log_is_scoped_to_milestone_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            output_path = Path(tmpdir) / "retro.md"
            log = FrictionLog(db_path)
            log.append(
                session_id="m1-day-1",
                run_id="run-in-window",
                category="slow",
                note="research approval paused long enough to lose context",
                created_at="2026-05-01T10:00:00.000000Z",
            )
            log.append(
                session_id="m0",
                run_id="run-outside",
                category="broken",
                note="older issue should not appear",
                created_at="2026-04-30T23:59:00.000000Z",
            )

            generate_retro_document(
                db_path=db_path,
                output_path=output_path,
                milestone="M1",
                started_at="2026-05-01T00:00:00.000000Z",
                completed_at="2026-05-02T00:00:00.000000Z",
            )
            text = output_path.read_text(encoding="utf-8")

        self.assertIn("research approval paused long enough to lose context", text)
        self.assertIn("session `m1-day-1` run `run-in-window`", text)
        self.assertNotIn("older issue should not appear", text)

    def test_mixed_success_failure_metrics_are_scoped_and_summarized(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            output_path = Path(tmpdir) / "retro.md"
            metrics = MetricsStore(db_path)
            metrics.record(
                _metric(
                    run_id="run-1",
                    stage_name="ticket_draft",
                    started_at="2026-05-01T10:00:00.000000Z",
                    duration_ms=100,
                    status="success",
                )
            )
            metrics.record(
                _metric(
                    run_id="run-2",
                    stage_name="ticket_draft",
                    started_at="2026-05-01T11:00:00.000000Z",
                    duration_ms=300,
                    status="failure",
                    error_message="export shape invalid",
                )
            )
            metrics.record(
                _metric(
                    run_id="run-0",
                    stage_name="ticket_draft",
                    started_at="2026-04-30T11:00:00.000000Z",
                    duration_ms=900,
                    status="success",
                )
            )

            generate_retro_document(
                db_path=db_path,
                output_path=output_path,
                milestone="M1",
                started_at="2026-05-01T00:00:00.000000Z",
                completed_at="2026-05-02T00:00:00.000000Z",
            )
            text = output_path.read_text(encoding="utf-8")

        self.assertIn("| ticket_draft | 2 | 200 | 290 | 0.50 |", text)
        self.assertNotIn("900", text)

    def test_cli_writes_default_stable_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            db_path = workspace / "metrics.sqlite"
            MetricsStore(db_path).record(
                _metric(
                    run_id="run-1",
                    stage_name="research",
                    started_at="2026-05-01T10:00:00.000000Z",
                    duration_ms=120,
                    status="success",
                )
            )

            result = _run_cli(
                [
                    "retro",
                    "--db-path",
                    str(db_path),
                    "--milestone",
                    "M1",
                    "--started-at",
                    "2026-05-01T00:00:00.000000Z",
                    "--completed-at",
                    "2026-05-02T00:00:00.000000Z",
                ],
                cwd=workspace,
            )

            output_path = workspace / ".overture" / "retros" / "milestone-retro.md"
            output_text = output_path.read_text(encoding="utf-8")

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.stdout, ".overture/retros/milestone-retro.md\n")
            self.assertTrue(output_path.exists())
            self.assertIn("| research | 1 | 120 | 120 | 1.00 |", output_text)


def _metric(
    *,
    run_id: str,
    stage_name: str,
    started_at: str,
    duration_ms: int,
    status: str,
    error_message: str | None = None,
) -> StageMetric:
    return StageMetric(
        run_id=run_id,
        intake_id="intake-1",
        stage_name=stage_name,
        started_at=started_at,
        completed_at=started_at,
        duration_ms=duration_ms,
        status=status,
        error_message=error_message,
    )


def _run_cli(argv: list[str], *, cwd: Path) -> "_CliResult":
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_cwd = Path.cwd()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            os.chdir(cwd)
            exit_code = cli.main(argv)
    finally:
        os.chdir(previous_cwd)
    return _CliResult(exit_code=exit_code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


class _CliResult:
    def __init__(self, *, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


if __name__ == "__main__":
    unittest.main()
