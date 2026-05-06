import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import overture.cli as cli
from overture.metrics_store import MetricsStore, StageMetric


STAGES = ("intake", "research", "graph", "synthesis", "ticket_draft")


class MetricsCliTests(unittest.TestCase):
    def test_table_output_includes_stage_rows_and_total_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            store = MetricsStore(db_path)
            _record_run(store, "run-1", "2026-05-06T10:00:00.000000Z")
            _record_run(store, "run-2", "2026-05-06T11:00:00.000000Z")

            result = _run_cli(["metrics", "--db-path", str(db_path)])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stderr, "")
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0].split(), ["stage", "count", "median_ms", "p95_ms", "success_rate"])
        self.assertEqual(lines[-1], "total runs: 2")
        stage_lines = lines[1:-1]
        self.assertEqual(len(stage_lines), 5)
        for stage in STAGES:
            self.assertIn(stage, result.stdout)
        for line in lines:
            self.assertLessEqual(len(line), 58)

    def test_json_output_includes_stage_keys_and_total_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            store = MetricsStore(db_path)
            _record_run(store, "run-1", "2026-05-06T10:00:00.000000Z")
            _record_run(store, "run-2", "2026-05-06T11:00:00.000000Z")

            result = _run_cli(["metrics", "--db-path", str(db_path), "--format=json"])

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["total_runs"], 2)
        self.assertEqual(set(STAGES).issubset(payload), True)
        self.assertEqual(payload["intake"]["count"], 2)
        self.assertTrue(result.stdout.endswith("\n"))
        for line in result.stdout.splitlines():
            self.assertEqual(line.rstrip(), line)

    def test_last_filter_restricts_summary_to_most_recent_distinct_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            store = MetricsStore(db_path)
            _record_run(store, "run-1", "2026-05-06T10:00:00.000000Z", duration_offset=100)
            _record_run(store, "run-2", "2026-05-06T11:00:00.000000Z", duration_offset=200)

            result = _run_cli(["metrics", "--db-path", str(db_path), "--last", "1", "--format=json"])

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["total_runs"], 1)
        for stage in STAGES:
            self.assertEqual(payload[stage]["count"], 1)
            self.assertGreaterEqual(payload[stage]["median_ms"], 200)

    def test_empty_database_exits_1_with_stderr_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "empty.sqlite"

            result = _run_cli(["metrics", "--db-path", str(db_path)])

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "no metrics recorded yet\n")


def _record_run(
    store: MetricsStore,
    run_id: str,
    base_started_at: str,
    *,
    duration_offset: int = 0,
) -> None:
    for index, stage in enumerate(STAGES):
        store.record(
            StageMetric(
                run_id=run_id,
                intake_id="intake-1",
                stage_name=stage,
                started_at=base_started_at.replace(":00.000000Z", f":0{index}.000000Z"),
                completed_at=base_started_at.replace(":00.000000Z", f":0{index}.000000Z"),
                duration_ms=duration_offset + ((index + 1) * 100),
                status="success",
                error_message=None,
            )
        )


def _run_cli(argv: list[str]) -> "_CliResult":
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = cli.main(argv)
    return _CliResult(exit_code=exit_code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


class _CliResult:
    def __init__(self, *, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


if __name__ == "__main__":
    unittest.main()
