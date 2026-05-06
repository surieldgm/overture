import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from overture import cli
from overture.fixture import run_overture_fixture
from overture.metrics_store import MetricsStore


EXPECTED_STAGES = ("intake", "research", "graph", "synthesis", "ticket_draft")
POST_INTAKE_STAGES = ("research", "graph", "synthesis", "ticket_draft")


class MetricsE2ETests(unittest.TestCase):
    def test_two_fixture_runs_feed_metrics_store_and_cli_summary(self) -> None:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            metrics_db_path = temp / "metrics.sqlite"

            run_overture_fixture(temp / "run1", metrics_db_path=metrics_db_path)
            run_overture_fixture(temp / "run2", metrics_db_path=metrics_db_path)

            rows = list(MetricsStore(metrics_db_path).iter_stages())
            self.assertEqual(len(rows), 10, "metrics DB should contain exactly 10 stage rows")

            run_ids = {row.run_id for row in rows}
            self.assertEqual(len(run_ids), 2, "metrics DB should contain two distinct run_id values")

            statuses = {row.status for row in rows}
            self.assertEqual(statuses, {"success"}, "all metrics rows should have status = success")

            rows_by_run = {
                run_id: [row for row in rows if row.run_id == run_id]
                for run_id in run_ids
            }
            for run_id, run_rows in rows_by_run.items():
                stage_names = {row.stage_name for row in run_rows}
                self.assertEqual(
                    stage_names,
                    set(EXPECTED_STAGES),
                    f"run_id {run_id} should contain all five fixture stage names",
                )
                post_intake_ids = {
                    row.intake_id
                    for row in run_rows
                    if row.stage_name in POST_INTAKE_STAGES
                }
                self.assertEqual(
                    len(post_intake_ids),
                    1,
                    f"run_id {run_id} should share one intake_id across post-intake stages",
                )
                self.assertNotIn(
                    None,
                    post_intake_ids,
                    f"run_id {run_id} should record a non-empty intake_id after intake",
                )

            table_stdout = io.StringIO()
            with contextlib.redirect_stdout(table_stdout):
                table_exit_code = cli.main(["metrics", "--db-path", str(metrics_db_path)])

            self.assertEqual(table_exit_code, 0, "metrics table CLI exit code should be 0")
            table = table_stdout.getvalue()
            for stage_name in EXPECTED_STAGES:
                self.assertIn(stage_name, table, f"metrics table should include stage {stage_name}")
            self.assertIn("total runs: 2", table, "metrics table should report total runs: 2")

            json_stdout = io.StringIO()
            with contextlib.redirect_stdout(json_stdout):
                json_exit_code = cli.main(["metrics", "--db-path", str(metrics_db_path), "--format=json"])

            self.assertEqual(json_exit_code, 0, "metrics JSON CLI exit code should be 0")
            payload = json.loads(json_stdout.getvalue())
            self.assertEqual(
                set(payload),
                set(EXPECTED_STAGES) | {"total_runs"},
                "metrics JSON should contain the expected top-level keys",
            )
            self.assertEqual(payload["total_runs"], 2, "metrics JSON should report two total runs")
            self.assertEqual(
                sum(payload[stage_name]["count"] for stage_name in EXPECTED_STAGES),
                10,
                "metrics JSON should contain all five stage summaries",
            )

        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 5.0, "metrics e2e test should run in under 5 seconds")


if __name__ == "__main__":
    unittest.main()
