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

    def test_append_confirmed_entry_and_seed_backlog_intake(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            db_path = base_dir / "metrics.sqlite"
            intake_dir = base_dir / "intake"
            first = _run_cli(
                [
                    "friction",
                    "append",
                    "--db-path",
                    str(db_path),
                    "--session-id",
                    "m1",
                    "--run-id",
                    "run-1",
                    "--category",
                    "slow",
                    "--note",
                    "research approval took too long",
                    "--confirmed",
                ]
            )
            second = _run_cli(
                [
                    "friction",
                    "append",
                    "--db-path",
                    str(db_path),
                    "--session-id",
                    "m1",
                    "--run-id",
                    "run-1",
                    "--category",
                    "confusing",
                    "--note",
                    "handoff instructions were unclear",
                    "--confirmed",
                ]
            )
            seeded = _run_cli(
                [
                    "backlog-seed",
                    "--db-path",
                    str(db_path),
                    "--store-dir",
                    str(intake_dir),
                    "--session-id",
                    "m1",
                    "--format=json",
                ]
            )

            payload = json.loads(seeded.stdout)
            intake_payloads = [
                json.loads(Path(item["path"]).read_text(encoding="utf-8"))
                for item in payload
            ]

        self.assertEqual(first.exit_code, 0)
        self.assertEqual(second.exit_code, 0)
        self.assertEqual(seeded.exit_code, 0)
        self.assertEqual(len(payload), 2)
        self.assertEqual([item["source_type"] for item in intake_payloads], ["friction", "friction"])
        self.assertIn("research approval took too long", intake_payloads[0]["raw_text"])
        self.assertIn("handoff instructions were unclear", intake_payloads[1]["raw_text"])

    def test_seed_m4_backlog_intakes_from_confirmed_designer_friction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            db_path = base_dir / "metrics.sqlite"
            intake_dir = base_dir / "intake"
            append = _run_cli(
                [
                    "friction",
                    "append",
                    "--db-path",
                    str(db_path),
                    "--session-id",
                    "m3",
                    "--run-id",
                    "three-designer-rollout",
                    "--category",
                    "performance",
                    "--note",
                    "approval page feels slow with real notes",
                    "--confirmed",
                ]
            )
            seeded = _run_cli(
                [
                    "backlog-seed",
                    "--target-milestone",
                    "M4",
                    "--db-path",
                    str(db_path),
                    "--store-dir",
                    str(intake_dir),
                    "--session-id",
                    "m3",
                    "--format=json",
                ]
            )

            payload = json.loads(seeded.stdout)
            intake_payload = json.loads(Path(payload[0]["path"]).read_text(encoding="utf-8"))

        self.assertEqual(append.exit_code, 0)
        self.assertEqual(seeded.exit_code, 0)
        self.assertEqual(len(payload), 1)
        self.assertEqual(intake_payload["source_type"], "m4-friction")
        self.assertIn("Sprint hint: M4-S2 performance", intake_payload["raw_text"])

    def test_seed_mwiz_backlog_intakes_from_persona_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report = base_dir / "personas-post-mwiz.md"
            intake_dir = base_dir / "intake"
            report.write_text(
                _mwiz_report(
                    headline="- Residual coverage sample",
                    baseline_rows=_mwiz_baseline_rows(
                        [
                            ("#1", "High", "Closed residual", "Closed", "verified"),
                            ("#2", "Medium", "Cookie replay is flaky", "Residual", "/tmp/m-wiz-test-rocio.md"),
                            ("#3", "Low", "Copy remains technical", "Residual", "notes"),
                        ]
                    ),
                    residuals=[
                        "- #3: copy remains technical.",
                    ],
                ),
                encoding="utf-8",
            )
            seeded = _run_cli(
                [
                    "backlog-seed",
                    "--store-dir",
                    str(intake_dir),
                    "--persona-report-path",
                    str(report),
                    "--format=json",
                ]
            )
            payload = json.loads(seeded.stdout)

            intake_payloads = [
                json.loads(Path(item["path"]).read_text(encoding="utf-8"))
                for item in payload
            ]

        self.assertEqual(seeded.exit_code, 0)
        self.assertEqual(len(payload), 2)
        self.assertEqual([item["finding_number"] for item in payload], ["#2", "#3"])
        self.assertEqual([item["intake_id"] for item in payload], [entry["id"] for entry in intake_payloads])
        self.assertEqual([entry["source_type"] for entry in intake_payloads], ["mwiz-residual"] * 2)
        self.assertIn("M-WIZ residual finding [#2]", intake_payloads[0]["raw_text"])


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


def _mwiz_report(*, headline: str, baseline_rows: str, residuals: list[str]) -> str:
    residual_text = "\n".join(residuals) if residuals else "_No residual findings were reported as open._"
    return "\n".join(
        [
            "# Persona report",
            "",
            "## Headline metric",
            headline,
            "",
            "## Baseline comparison table",
            baseline_rows,
            "### New findings introduced post-MWIZ",
            _mwiz_new_findings(),
            "## Residuals",
            residual_text,
        ]
    )


def _mwiz_baseline_rows(rows: list[tuple[str, str, str, str, str]]) -> str:
    lines = [
        "| Baseline finding | Severity | Baseline description | Post-MWIZ status | Evidence / notes |",
        "|---|---|---|---|---|",
    ]
    for finding_number, severity, description, status, evidence in rows:
        lines.append(f"| {finding_number} | {severity} | {description} | {status} | {evidence} |")
    return "\n".join(lines)


def _mwiz_new_findings() -> str:
    return "\n".join(["| New finding | Severity | Description |", "|---|---|---|"])
