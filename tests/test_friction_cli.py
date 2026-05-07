import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import overture.cli as cli
from overture.metrics_store import MetricsStore, StageMetric


class FrictionCliTests(unittest.TestCase):
    def test_append_two_entries_to_latest_run_and_query_by_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            metrics = MetricsStore(db_path)
            metrics.record(_metric("run-old", "2026-05-07T09:00:00.000000Z"))
            metrics.record(_metric("run-latest", "2026-05-07T10:00:00.000000Z"))

            first = _run_cli(
                [
                    "friction",
                    "append",
                    "--db-path",
                    str(db_path),
                    "--session-id",
                    "dogfood-day-1",
                    "--run-id",
                    "latest",
                    "--category",
                    "slow",
                    "--note",
                    "research approval lagged",
                ]
            )
            second = _run_cli(
                [
                    "friction",
                    "append",
                    "--db-path",
                    str(db_path),
                    "--session-id",
                    "dogfood-day-1",
                    "--run-id",
                    "latest",
                    "--category",
                    "confusing",
                    "--note",
                    "handoff status was unclear",
                ]
            )
            queried = _run_cli(
                [
                    "friction",
                    "list",
                    "--db-path",
                    str(db_path),
                    "--run-id",
                    "run-latest",
                    "--format=json",
                ]
            )

        self.assertEqual(first.exit_code, 0)
        self.assertEqual(second.exit_code, 0)
        self.assertEqual(first.stderr, "")
        self.assertEqual(second.stderr, "")
        payload = json.loads(queried.stdout)
        self.assertEqual(queried.exit_code, 0)
        self.assertEqual([entry["run_id"] for entry in payload], ["run-latest", "run-latest"])
        self.assertEqual([entry["category"] for entry in payload], ["slow", "confusing"])
        self.assertEqual(
            [entry["note"] for entry in payload],
            ["research approval lagged", "handoff status was unclear"],
        )

    def test_list_filters_by_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            _append(db_path, "day-1", "run-1", "slow", "first")
            _append(db_path, "day-2", "run-1", "broken", "second")

            result = _run_cli(
                [
                    "friction",
                    "list",
                    "--db-path",
                    str(db_path),
                    "--session-id",
                    "day-2",
                    "--format=json",
                ]
            )

        payload = json.loads(result.stdout)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual([entry["session_id"] for entry in payload], ["day-2"])
        self.assertEqual([entry["note"] for entry in payload], ["second"])


def _append(db_path: Path, session_id: str, run_id: str, category: str, note: str) -> None:
    result = _run_cli(
        [
            "friction",
            "append",
            "--db-path",
            str(db_path),
            "--session-id",
            session_id,
            "--run-id",
            run_id,
            "--category",
            category,
            "--note",
            note,
        ]
    )
    if result.exit_code != 0:
        raise AssertionError(result.stderr)


def _metric(run_id: str, started_at: str) -> StageMetric:
    return StageMetric(
        run_id=run_id,
        intake_id="intake-1",
        stage_name="ticket_draft",
        started_at=started_at,
        completed_at=started_at,
        duration_ms=100,
        status="success",
        error_message=None,
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
