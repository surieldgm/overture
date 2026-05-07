import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import overture.cli as cli
from overture.export_store import ExportLedger, compute_hash
from overture.friction_log import FrictionLog
from overture.metrics_store import MetricsStore, StageMetric


class MilestoneVerifierTests(unittest.TestCase):
    def test_all_pass_reports_each_observed_value_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_config(workspace, target=2)
            _populate_workspace(workspace, metric_runs=2, exported_tickets=2, friction_entries=2, dogfooding_days=2)
            _write_retro(workspace)

            result = _run_cli(["milestone", "verify", "--config", str(config), "--workspace", str(workspace)])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stderr, "")
        self.assertIn("Milestone Synthetic M1: PASS", result.stdout)
        self.assertIn("PASS metric_runs: observed=2 target=2", result.stdout)
        self.assertIn("PASS exported_tickets: observed=2 target=2", result.stdout)
        self.assertIn("PASS friction_entries: observed=2 target=2", result.stdout)
        self.assertIn("PASS dogfooding_days: observed=2 target=2", result.stdout)
        self.assertIn("PASS generated_retro: observed=1 target=1", result.stdout)

    def test_partial_pass_json_reports_named_deficits_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_config(workspace, target=2)
            _populate_workspace(workspace, metric_runs=2, exported_tickets=1, friction_entries=1, dogfooding_days=1)
            _write_retro(workspace)

            result = _run_cli(
                [
                    "milestone",
                    "verify",
                    "--config",
                    str(config),
                    "--workspace",
                    str(workspace),
                    "--format=json",
                ]
            )

        payload = json.loads(result.stdout)
        criteria = {criterion["name"]: criterion for criterion in payload["criteria"]}
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["passed"], False)
        self.assertEqual(criteria["metric_runs"]["passed"], True)
        self.assertEqual(criteria["exported_tickets"]["deficit"], 1)
        self.assertEqual(criteria["friction_entries"]["deficit"], 1)
        self.assertEqual(criteria["dogfooding_days"]["deficit"], 1)
        self.assertEqual(criteria["generated_retro"]["passed"], True)

    def test_all_fail_against_empty_workspace_reports_each_deficit_without_mutating_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_config(workspace, target=2)

            result = _run_cli(["milestone", "verify", "--config", str(config), "--workspace", str(workspace)])

            self.assertFalse((workspace / ".overture").exists(), "verifier must not create local store directories")

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Milestone Synthetic M1: FAIL", result.stdout)
        self.assertIn("FAIL metric_runs: observed=0 target=2 deficit=2", result.stdout)
        self.assertIn("FAIL exported_tickets: observed=0 target=2 deficit=2", result.stdout)
        self.assertIn("FAIL friction_entries: observed=0 target=2 deficit=2", result.stdout)
        self.assertIn("FAIL dogfooding_days: observed=0 target=2 deficit=2", result.stdout)
        self.assertIn("FAIL generated_retro: observed=0 target=1 deficit=1", result.stdout)


def _write_config(workspace: Path, *, target: int) -> Path:
    config = {
        "milestone": "Synthetic M1",
        "criteria": {
            "metric_runs": {"kind": "metric_runs", "target": target},
            "exported_tickets": {"kind": "exported_tickets", "target": target},
            "friction_entries": {"kind": "friction_entries", "target": target},
            "dogfooding_days": {"kind": "dogfooding_days", "target": target},
            "generated_retro": {"kind": "generated_retro", "target": 1},
        },
    }
    path = workspace / "milestone.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _populate_workspace(
    workspace: Path,
    *,
    metric_runs: int,
    exported_tickets: int,
    friction_entries: int,
    dogfooding_days: int,
) -> None:
    metrics_db = workspace / ".overture" / "metrics.sqlite"
    metrics = MetricsStore(metrics_db)
    for index in range(metric_runs):
        metrics.record(
            StageMetric(
                run_id=f"run-{index}",
                intake_id=f"intake-{index}",
                stage_name="ticket_draft",
                started_at=f"2026-05-07T10:0{index}:00.000000Z",
                completed_at=f"2026-05-07T10:0{index}:01.000000Z",
                duration_ms=1000,
                status="success",
                error_message=None,
            )
        )

    log = FrictionLog(metrics_db)
    for index in range(friction_entries):
        session_index = index % max(dogfooding_days, 1)
        log.append(
            session_id=f"dogfood-day-{session_index + 1}",
            run_id=f"run-{min(index, max(metric_runs - 1, 0))}",
            category="slow",
            note=f"note {index}",
            created_at=f"2026-05-07T11:0{index}:00.000000Z",
        )

    ledger = ExportLedger(workspace / ".overture" / "exports.sqlite")
    for index in range(exported_tickets):
        ledger.record(
            f"ticket-{index}.md",
            compute_hash(f"# Ticket {index}\n"),
            f"issue-{index}",
            f"https://linear.app/eria/issue/ERI-{index}/ticket",
        )


def _write_retro(workspace: Path) -> None:
    retro = workspace / ".overture" / "retro" / "m1.md"
    retro.parent.mkdir(parents=True, exist_ok=True)
    retro.write_text("# M1 Retro\n", encoding="utf-8")


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
