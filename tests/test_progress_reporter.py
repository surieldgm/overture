import contextlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from overture import fixture
from overture.fixture import PipelineStageError, StageTransition, run_overture_fixture
from overture.metrics_store import MetricsStore
from overture.research import ResearchError, ResearchResult


EXPECTED_STAGES = ("intake", "research", "graph", "synthesis", "ticket_draft")


class ProgressReporterTests(unittest.TestCase):
    def test_default_fixture_run_emits_started_and_completed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            metrics_db_path = Path(tmpdir) / "metrics.sqlite"

            run_overture_fixture(
                Path(tmpdir) / "fixture",
                metrics_db_path=metrics_db_path,
                progress_stream=stderr,
            )

            lines = stderr.getvalue().splitlines()
            self.assertEqual(len(lines), 10)
            self.assertEqual(lines[::2], [f"{stage} started" for stage in EXPECTED_STAGES])
            for line, stage in zip(lines[1::2], EXPECTED_STAGES):
                self.assertRegex(line, rf"^{stage} completed \d+ms$")

            rows = list(MetricsStore(metrics_db_path).iter_stages())
            self.assertEqual([row.stage_name for row in rows], list(EXPECTED_STAGES))
            self.assertEqual({row.status for row in rows}, {"success"})

    def test_quiet_progress_suppresses_stderr_without_affecting_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            metrics_db_path = Path(tmpdir) / "metrics.sqlite"

            run_overture_fixture(
                Path(tmpdir) / "fixture",
                metrics_db_path=metrics_db_path,
                quiet_progress=True,
                progress_stream=stderr,
            )

            self.assertEqual(stderr.getvalue(), "")
            rows = list(MetricsStore(metrics_db_path).iter_stages())
            self.assertEqual(len(rows), 5)
            self.assertEqual([row.stage_name for row in rows], list(EXPECTED_STAGES))
            self.assertEqual({row.status for row in rows}, {"success"})

    def test_stage_failure_emits_failed_line_and_failure_metric(self) -> None:
        def failed_research(_intake):
            return ResearchResult(
                intake_id="ignored",
                errors=(ResearchError(code="adapter_failure", message="research adapter failed"),),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            metrics_db_path = Path(tmpdir) / "metrics.sqlite"

            with patch.object(fixture, "_research_overture", failed_research):
                with self.assertRaises(PipelineStageError):
                    run_overture_fixture(
                        Path(tmpdir) / "fixture",
                        metrics_db_path=metrics_db_path,
                        progress_stream=stderr,
                    )

            lines = stderr.getvalue().splitlines()
            self.assertEqual(lines[0], "intake started")
            self.assertRegex(lines[1], r"^intake completed \d+ms$")
            self.assertEqual(lines[2], "research started")
            self.assertRegex(
                lines[3],
                r"^research failed \d+ms: adapter_failure: research adapter failed$",
            )

            rows = list(MetricsStore(metrics_db_path).iter_stages())
            self.assertEqual([row.stage_name for row in rows], ["intake", "research"])
            self.assertEqual(rows[0].status, "success")
            self.assertEqual(rows[1].status, "failure")
            self.assertIn("adapter_failure: research adapter failed", rows[1].error_message or "")

    def test_progress_reporter_overhead_stays_small(self) -> None:
        stream = io.StringIO()
        observer = fixture._emit_progress(stream)
        started = time.perf_counter()

        with contextlib.redirect_stderr(io.StringIO()):
            for index in range(1000):
                observer(
                    StageTransition(
                        run_id="run",
                        intake_id=None,
                        stage_name=f"stage_{index}",
                        state="started",
                        started_at="2026-01-01T00:00:00.000000Z",
                    )
                )

        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.25)
        self.assertEqual(len(stream.getvalue().splitlines()), 1000)


if __name__ == "__main__":
    unittest.main()
