import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from overture import fixture
from overture.fixture import PipelineStageError, run_overture_fixture
from overture.metrics_store import MetricsStore
from overture.research import ResearchError, ResearchResult


class FixtureMetricsTests(unittest.TestCase):
    def test_successful_fixture_run_records_five_stage_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "fixture"
            metrics_db_path = Path(tmpdir) / "metrics.sqlite"

            artifacts = run_overture_fixture(output_dir, metrics_db_path=metrics_db_path)

            rows = list(MetricsStore(metrics_db_path).iter_stages())
            self.assertEqual(
                [row.stage_name for row in rows],
                ["intake", "research", "graph", "synthesis", "ticket_draft"],
            )
            self.assertEqual(len({row.run_id for row in rows}), 1)
            self.assertEqual(rows[0].run_id, artifacts["run_id"])
            self.assertIsNone(rows[0].intake_id)
            intake = json.loads(Path(artifacts["intake"]).read_text(encoding="utf-8"))
            for row in rows[1:]:
                self.assertEqual(row.intake_id, intake["id"])
            for row in rows:
                self.assertEqual(row.status, "success")
                self.assertIsNone(row.error_message)
                self.assertGreaterEqual(row.duration_ms, 0)

    def test_research_failure_records_failure_metric_and_raises_pipeline_stage_error(self) -> None:
        def failed_research(_intake):
            return ResearchResult(
                intake_id="ignored",
                errors=(ResearchError(code="adapter_failure", message="research adapter failed"),),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_db_path = Path(tmpdir) / "metrics.sqlite"
            with patch.object(fixture, "_research_overture", failed_research):
                with self.assertRaises(PipelineStageError) as error:
                    run_overture_fixture(Path(tmpdir) / "fixture", metrics_db_path=metrics_db_path)

            self.assertEqual(error.exception.stage, "research")
            self.assertIn("research adapter failed", error.exception.message)

            rows = list(MetricsStore(metrics_db_path).iter_stages())
            self.assertEqual([row.stage_name for row in rows], ["intake", "research"])
            self.assertEqual(rows[0].status, "success")
            research_row = rows[1]
            self.assertEqual(research_row.status, "failure")
            self.assertIn("adapter_failure: research adapter failed", research_row.error_message or "")
            self.assertEqual(research_row.run_id, rows[0].run_id)
            self.assertIsNotNone(research_row.intake_id)

    def test_metrics_record_failure_does_not_mask_original_pipeline_stage_error(self) -> None:
        class FailingMetricsStore:
            def __init__(self, _db_path):
                pass

            def record(self, _metric):
                raise RuntimeError("metrics db unavailable")

        def failed_research(_intake):
            return ResearchResult(
                intake_id="ignored",
                errors=(ResearchError(code="adapter_failure", message="research adapter failed"),),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            with patch.object(fixture, "MetricsStore", FailingMetricsStore), patch.object(
                fixture, "_research_overture", failed_research
            ), contextlib.redirect_stderr(stderr):
                with self.assertRaises(PipelineStageError) as error:
                    run_overture_fixture(Path(tmpdir) / "fixture", metrics_db_path=Path(tmpdir) / "metrics.sqlite")

        self.assertEqual(error.exception.stage, "research")
        self.assertIn("research adapter failed", error.exception.message)
        self.assertIn("failed to record stage metric for research", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
