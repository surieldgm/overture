import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import overture.cli as cli
from overture.fixture import PIPELINE_STAGES
from overture.metrics_store import MetricsStore


class DogfoodingDayOneSmokeTests(unittest.TestCase):
    def test_two_run_loop_reports_progress_metrics_friction_and_prior_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            metrics_db_path = temp / "metrics.sqlite"
            with _pushd(temp):
                first = _run_cli(
                    [
                        "run",
                        "Add idea persistence to Overture",
                        "--output-dir",
                        str(temp / "run1"),
                        "--metrics-db-path",
                        str(metrics_db_path),
                    ]
                )
                second = _run_cli(
                    [
                        "run",
                        "Query persisted ideas in synthesis briefs",
                        "--output-dir",
                        str(temp / "run2"),
                        "--metrics-db-path",
                        str(metrics_db_path),
                    ]
                )

            self.assertEqual(first.exit_code, 0, first.stderr)
            self.assertEqual(second.exit_code, 0, second.stderr)
            self.assertEqual(
                Path(first.stdout.strip()),
                temp / "run1" / "ticket" / "symphony-ticket-draft.md",
            )
            self.assertEqual(
                Path(second.stdout.strip()),
                temp / "run2" / "ticket" / "symphony-ticket-draft.md",
            )

            stderr = first.stderr + second.stderr
            self._assert_progress_markers(stderr)

            rows = list(MetricsStore(metrics_db_path).iter_stages())
            self.assertEqual(len(rows), len(PIPELINE_STAGES) * 2)
            run_ids = _run_ids_in_order(rows)
            self.assertEqual(len(run_ids), 2)
            self.assertNotEqual(run_ids[0], run_ids[1])

            append = _run_cli(
                [
                    "friction",
                    "append",
                    "--db-path",
                    str(metrics_db_path),
                    "--session-id",
                    "dogfood-day-1",
                    "--run-id",
                    run_ids[0],
                    "--category",
                    "confusing",
                    "--note",
                    "first-run handoff needed more context",
                ]
            )
            queried = _run_cli(
                [
                    "friction",
                    "list",
                    "--db-path",
                    str(metrics_db_path),
                    "--session-id",
                    "dogfood-day-1",
                    "--run-id",
                    run_ids[0],
                    "--format=json",
                ]
            )

            self.assertEqual(append.exit_code, 0, append.stderr)
            self.assertEqual(queried.exit_code, 0, queried.stderr)
            entries = json.loads(queried.stdout)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["run_id"], run_ids[0])
            self.assertEqual(entries[0]["session_id"], "dogfood-day-1")
            self.assertEqual(entries[0]["category"], "confusing")
            self.assertEqual(entries[0]["note"], "first-run handoff needed more context")

            first_graph = json.loads(
                (temp / "run1" / "graph" / "graph-records.json").read_text(encoding="utf-8")
            )
            first_node_ids = {node["id"] for node in first_graph["context"]["nodes"]}
            second_draft = (temp / "run2" / "ticket" / "symphony-ticket-draft.md").read_text(
                encoding="utf-8"
            )
            prior_node_ids = {
                node_id.removeprefix("prior:")
                for node_id in re.findall(r"`(prior:[^`]+)`", _graph_provenance_section(second_draft))
            }
            self.assertTrue(
                first_node_ids & prior_node_ids,
                "second run draft did not cite a prior node from the first run graph context",
            )

    def _assert_progress_markers(self, stderr: str) -> None:
        lines = stderr.splitlines()
        for stage in PIPELINE_STAGES:
            self.assertEqual(lines.count(f"{stage} started"), 2)
            completed = [
                line
                for line in lines
                if re.match(rf"^{re.escape(stage)} completed \d+ms$", line)
            ]
            self.assertEqual(len(completed), 2)


def _run_ids_in_order(rows) -> list[str]:
    run_ids: list[str] = []
    for row in rows:
        if row.run_id not in run_ids:
            run_ids.append(row.run_id)
    return run_ids


def _graph_provenance_section(markdown: str) -> str:
    match = re.search(
        r"^## Graph provenance\n(?P<body>.*?)(?=^## |\Z)",
        markdown,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body").strip() if match else "<missing graph provenance section>"


def _run_cli(argv: list[str]) -> "_CliResult":
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
        mock.patch.dict(os.environ, {}, clear=True),
    ):
        exit_code = cli.main(argv)
    return _CliResult(exit_code=exit_code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


@contextlib.contextmanager
def _pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class _CliResult:
    def __init__(self, *, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


if __name__ == "__main__":
    unittest.main()
