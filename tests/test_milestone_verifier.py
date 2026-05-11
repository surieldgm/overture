import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import overture.cli as cli
from overture.auth import AuthenticatedUser
from overture.export_store import ExportLedger, compute_hash
from overture.friction_log import FrictionLog
from overture.graph import GraphRecord
from overture.graph_store import SqliteGraphStore
from overture.metrics_store import MetricsStore, StageMetric
from overture.metrics_store import TicketMetric
from overture.observation_log import ObservationLog


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

    def test_m3_all_pass_loads_registry_rules_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_m3_config(workspace)
            _populate_m3_workspace(workspace, designers=3, observation_sessions=3, peer_artifacts=1, retro_docs=1)

            result = _run_cli(["milestone", "verify", "--config", str(config), "--workspace", str(workspace)])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stderr, "")
        self.assertIn("Milestone M3: PASS", result.stdout)
        self.assertIn("PASS m3_designers_shipped: observed=3 target=3", result.stdout)
        self.assertIn("PASS m3_peer_onboarding_artifacts: observed=1 target=1", result.stdout)
        self.assertIn("PASS m3_observation_sessions: observed=3 target=3", result.stdout)
        self.assertIn("PASS m3_retro_docs: observed=1 target=1", result.stdout)

    def test_m3_partial_pass_names_missing_peer_artifact_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_m3_config(workspace)
            _populate_m3_workspace(workspace, designers=3, observation_sessions=3, peer_artifacts=0, retro_docs=1)

            result = _run_cli(["milestone", "verify", "--config", str(config), "--workspace", str(workspace)])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Milestone M3: FAIL", result.stdout)
        self.assertIn("FAIL m3_peer_onboarding_artifacts: observed=0 target=1 deficit=1", result.stdout)
        self.assertIn("PASS m3_designers_shipped: observed=3 target=3", result.stdout)

    def test_m3_all_fail_reports_each_registry_deficit_without_mutating_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_m3_config(workspace)

            result = _run_cli(["milestone", "verify", "--config", str(config), "--workspace", str(workspace)])

            self.assertFalse((workspace / ".overture").exists(), "M3 verifier must not create local store directories")

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Milestone M3: FAIL", result.stdout)
        self.assertIn("FAIL m3_designers_shipped: observed=0 target=3 deficit=3", result.stdout)
        self.assertIn("FAIL m3_peer_onboarding_artifacts: observed=0 target=1 deficit=1", result.stdout)
        self.assertIn("FAIL m3_observation_sessions: observed=0 target=3 deficit=3", result.stdout)
        self.assertIn("FAIL m3_retro_docs: observed=0 target=1 deficit=1", result.stdout)

    def test_mwiz_all_pass_reports_passed_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_mwiz_config(
                workspace,
                persona_target=3,
                baseline_target=18,
                smoke_target=2,
                smoke_commands=[
                    "python -c \"import sys; sys.exit(0)\"",
                    "python -c \"import sys; sys.exit(0)\"",
                ],
            )
            _write_mwiz_report(
                workspace,
                completed=3,
                statuses=[
                    "closed",
                    "open",
                    "new",
                    "closed",
                    "open",
                    "new",
                    "closed",
                    "open",
                    "new",
                    "closed",
                    "open",
                    "new",
                    "closed",
                    "open",
                    "new",
                    "closed",
                    "open",
                    "new",
                    "closed",
                ],
            )
            _write_mwiz_schema_draft(workspace)

            result = _run_cli(["milestone", "verify", "--config", str(config), "--workspace", str(workspace)])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stderr, "")
        self.assertIn("Milestone M-WIZ: PASS", result.stdout)
        self.assertIn("PASS mwiz_persona_completion: observed=3 target=3", result.stdout)
        self.assertIn("PASS mwiz_baseline_coverage: observed=18 target=18", result.stdout)
        self.assertIn("PASS mwiz_smoke_tests: observed=2 target=2", result.stdout)
        self.assertIn("PASS mwiz_schema_validators: observed=1 target=1", result.stdout)

    def test_mwiz_partial_pass_fails_with_named_deficits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_mwiz_config(
                workspace,
                persona_target=3,
                baseline_target=18,
                smoke_target=2,
                smoke_commands=[
                    "python -c \"import sys; sys.exit(0)\"",
                    "python -c \"import sys; sys.exit(1)\"",
                ],
                ticket_drafts=["mwiz_invalid.md"],
            )
            _write_mwiz_report(
                workspace,
                completed=2,
                statuses=[
                    "closed",
                    "open",
                    "residual",
                    "closed",
                    "open",
                    "new",
                    "closed",
                    "open",
                    "closed",
                    "open",
                    "new",
                    "closed",
                    "open",
                    "new",
                    "closed",
                    "open",
                    "new",
                    "open",
                ],
            )
            _write_invalid_mwiz_schema_draft(workspace, "mwiz_invalid.md")

            result = _run_cli(["milestone", "verify", "--config", str(config), "--workspace", str(workspace)])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Milestone M-WIZ: FAIL", result.stdout)
        self.assertIn("FAIL mwiz_persona_completion: observed=2 target=3 deficit=1", result.stdout)
        self.assertIn("FAIL mwiz_baseline_coverage: observed=17 target=18 deficit=1", result.stdout)
        self.assertIn("FAIL mwiz_smoke_tests: observed=1 target=2 deficit=1", result.stdout)
        self.assertIn("FAIL mwiz_schema_validators: observed=0 target=1 deficit=1", result.stdout)

    def test_mwiz_all_fail_reports_all_named_deficits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config = _write_mwiz_config(
                workspace,
                persona_target=3,
                baseline_target=18,
                smoke_target=1,
                smoke_commands=["python -c \"import sys; sys.exit(1)\""],
                ticket_drafts=["missing.md"],
            )

            result = _run_cli(["milestone", "verify", "--config", str(config), "--workspace", str(workspace)])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Milestone M-WIZ: FAIL", result.stdout)
        self.assertIn("FAIL mwiz_persona_completion: observed=0 target=3 deficit=3", result.stdout)
        self.assertIn("FAIL mwiz_baseline_coverage: observed=0 target=18 deficit=18", result.stdout)
        self.assertIn("FAIL mwiz_smoke_tests: observed=0 target=1 deficit=1", result.stdout)
        self.assertIn("FAIL mwiz_schema_validators: observed=0 target=1 deficit=1", result.stdout)


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


def _write_m3_config(workspace: Path) -> Path:
    config = {"milestone": "M3"}
    path = workspace / "m3.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _write_mwiz_config(
    workspace: Path,
    *,
    persona_target: int,
    baseline_target: int,
    smoke_target: int,
    smoke_commands: list[str],
    ticket_drafts: list[str] | None = None,
) -> Path:
    config = {
        "milestone": "M-WIZ",
        "criteria": {
            "mwiz_persona_completion": {
                "kind": "mwiz_persona_completion",
                "target": persona_target,
                "report_glob": "docs/user-tests/*personas-post-mwiz*.md",
            },
            "mwiz_baseline_coverage": {
                "kind": "mwiz_baseline_coverage",
                "target": baseline_target,
                "report_glob": "docs/user-tests/*personas-post-mwiz*.md",
            },
            "mwiz_smoke_tests": {
                "kind": "mwiz_smoke_tests",
                "target": smoke_target,
                "commands": smoke_commands,
            },
            "mwiz_schema_validators": {
                "kind": "mwiz_schema_validators",
                "target": 1,
                "ticket_drafts": ticket_drafts or ["mwiz_schema_draft.md"],
            },
        },
    }
    path = workspace / "mwiz.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _write_mwiz_report(workspace: Path, *, completed: int, statuses: list[str]) -> None:
    normalized_statuses = statuses[:18]
    rows = [
        f"| #{index} | Medium | Synthetic finding | {status} | Validated in synthetic check |\n"
        for index, status in enumerate(normalized_statuses, start=1)
    ]
    report = workspace / "docs/user-tests" / "personas-post-mwiz-synthetic.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        (
            "# Synthetic post-MWIZ report\n\n"
            f"**{completed} of 3 personas completed idea→ticket via wizard.**\n\n"
            "## Baseline comparison table\n\n"
            "| Baseline finding | Severity | Baseline description | Post-MWIZ status | Evidence / notes |\n"
            "|---|---|---|---|---|\n"
            + "".join(rows)
        ),
        encoding="utf-8",
    )


def _write_mwiz_schema_draft(workspace: Path) -> None:
    path = workspace / "mwiz_schema_draft.md"
    template_path = Path(__file__).resolve().parent.parent / "examples" / "overture_mvp_linear_issue_draft.md"
    path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")


def _write_invalid_mwiz_schema_draft(workspace: Path, filename: str) -> None:
    path = workspace / filename
    path.write_text(
        "# Invalid schema draft\n"
        "No required sections present.\n",
        encoding="utf-8",
    )


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


def _populate_m3_workspace(
    workspace: Path,
    *,
    designers: int,
    observation_sessions: int,
    peer_artifacts: int,
    retro_docs: int,
) -> None:
    metrics = MetricsStore(workspace / ".overture" / "metrics.sqlite")
    for index in range(designers):
        metrics.record_ticket(
            TicketMetric(
                ticket_id=f"ERI-M3-{index}",
                author_id=f"designer-{index + 1}",
                author_email=f"designer-{index + 1}@example.test",
                sprint_label="m3-s7",
                milestone="M3",
            )
        )

    actor = AuthenticatedUser(user_id="observer@example.test", email="observer@example.test")
    observations = ObservationLog(workspace / ".overture" / "observation.sqlite")
    for index in range(observation_sessions):
        observations.append(
            session_id=f"designer-session-{index + 1}",
            event_type="http",
            route="/intake",
            action="submit",
            actor=actor,
            request={"index": index},
            response={"ok": True},
        )

    if peer_artifacts:
        graph = SqliteGraphStore(workspace / ".overture" / "graph.sqlite")
        for index, node_id in enumerate(
            (
                "component_designer_one_filled_artifact",
                "component_designer_three_peer_onboarding_artifact",
            )[:peer_artifacts]
        ):
            graph.upsert_record(
                GraphRecord(
                    kind="Component",
                    key=node_id,
                    properties={"label": f"M3 peer artifact {index + 1}", "viewer_route": "/peer-onboarding"},
                )
            )

    for index in range(retro_docs):
        retro = workspace / ".overture" / "retros" / f"m3-retro-{index + 1}.md"
        retro.parent.mkdir(parents=True, exist_ok=True)
        retro.write_text("# M3 Retro\n", encoding="utf-8")


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
