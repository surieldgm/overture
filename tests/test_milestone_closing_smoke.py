import json
import tempfile
import unittest
from pathlib import Path

from overture.auth import AuthenticatedUser
from overture.backlog_seeder import seed_confirmed_friction_intakes
from overture.closing_chain import (
    generate_retro,
    seed_backlog_from_friction,
    verify_milestone_closing,
)
from overture.friction_log import FRICTION_CATEGORIES, FrictionLog
from overture.intake import load_intake_record, stable_intake_id
from overture.milestone_verifier import verify_milestone_config
from overture.metrics_store import MetricsStore, StageMetric
from overture.observation_log import ObservationLog
from overture.retro_generator import generate_retro_document


class MilestoneClosingSmokeTests(unittest.TestCase):
    def test_m3_three_designer_closing_chain_seeds_m4_intakes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            db_path = workspace / ".overture" / "metrics.sqlite"
            retro_path = workspace / ".overture" / "retro" / "m3.md"
            intake_dir = workspace / ".overture" / "intake" / "m4"
            config_path = _write_m3_config(workspace, target=9)

            designers = _seed_three_designer_m3_workspace(workspace=workspace, db_path=db_path)

            generated_retro = generate_retro_document(
                db_path=db_path,
                output_path=retro_path,
                milestone="M3",
                started_at="2026-05-07T00:00:00.000000Z",
                completed_at="2026-05-08T00:00:00.000000Z",
            )
            seeded = seed_confirmed_friction_intakes(
                friction_log=FrictionLog(db_path),
                intake_store_dir=intake_dir,
            )
            verification = verify_milestone_config(config_path, workspace=workspace)

            retro_text = generated_retro.read_text(encoding="utf-8")
            self.assertTrue(verification.passed)
            self.assertEqual(generated_retro, retro_path)
            self.assertIn("## Team Summary", retro_text)
            for designer in designers:
                self.assertIn(f"### {designer['email']}", retro_text)
                self.assertIn(f"`{designer['session_id']}`", retro_text)

            confirmed_frictions = list(FrictionLog(db_path).iter_entries(confirmed=True))
            self.assertEqual(len(confirmed_frictions), 9)
            self.assertEqual(len(seeded), len(confirmed_frictions))
            for item in seeded:
                intake = load_intake_record(item.path)
                self.assertEqual(intake.source_type, "friction")
                self.assertIn(item.friction_entry.category, intake.raw_text)
                self.assertIn(item.friction_entry.session_id, intake.raw_text)
                self.assertIn(item.friction_entry.run_id, intake.raw_text)
                self.assertIn(item.friction_entry.note, intake.raw_text)

    def test_two_day_dogfooding_closing_chain_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            metrics_db_path = temp / "metrics.sqlite"
            retro_path = temp / "milestones" / "m1-retro.md"
            intake_dir = temp / "intake" / "m2"

            _seed_two_days(metrics_db_path)

            retro = generate_retro(metrics_db_path=metrics_db_path, output_path=retro_path)
            seed = seed_backlog_from_friction(
                metrics_db_path=metrics_db_path,
                intake_dir=intake_dir,
            )
            result = verify_milestone_closing(
                metrics_db_path=metrics_db_path,
                retro_path=retro_path,
                intake_dir=intake_dir,
                required_sessions=("dogfood-day-1", "dogfood-day-2"),
            )

            self.assertTrue(retro.exists(), "retro Markdown file should exist")
            retro_text = retro.read_text(encoding="utf-8")
            self.assertIn("dogfood-day-1", retro_text)
            self.assertIn("dogfood-day-2", retro_text)

            confirmed_frictions = list(FrictionLog(metrics_db_path).iter_entries())
            self.assertEqual(
                len(confirmed_frictions),
                len(FRICTION_CATEGORIES),
                "seed should include one confirmed friction per category",
            )
            self.assertEqual(seed.friction_count, len(confirmed_frictions))
            self.assertEqual(len(seed.intake_paths), len(confirmed_frictions))
            for entry in confirmed_frictions:
                intake_text = (
                    f"Confirmed dogfooding friction for M2 backlog: {entry.category} friction "
                    f"in {entry.session_id} during run {entry.run_id}. Note: {entry.note}"
                )
                self.assertTrue(
                    (intake_dir / f"{stable_intake_id(intake_text)}.json").exists(),
                    f"missing intake for confirmed friction {entry.id}",
                )

            self.assertTrue(result.passed, "\n".join(result.failures))


def _seed_two_days(metrics_db_path: Path) -> None:
    metrics = MetricsStore(metrics_db_path)
    friction = FrictionLog(metrics_db_path)
    day_runs = {
        "dogfood-day-1": ("run-day-1-a", "run-day-1-b"),
        "dogfood-day-2": ("run-day-2-a", "run-day-2-b"),
    }
    for day_index, (session_id, run_ids) in enumerate(day_runs.items(), start=1):
        for run_index, run_id in enumerate(run_ids, start=1):
            _record_successful_run(metrics, run_id, f"intake-{day_index}-{run_index}")

    categories = tuple(FRICTION_CATEGORIES)
    friction.append(
        session_id="dogfood-day-1",
        run_id="run-day-1-a",
        category=categories[0],
        note="ticket drafting took too long to scan",
        created_at="2026-05-05T09:10:00.000000Z",
    )
    friction.append(
        session_id="dogfood-day-1",
        run_id="run-day-1-b",
        category=categories[1],
        note="retro action labels were hard to interpret",
        created_at="2026-05-05T10:15:00.000000Z",
    )
    friction.append(
        session_id="dogfood-day-2",
        run_id="run-day-2-a",
        category=categories[2],
        note="backlog seeding failed when evidence was sparse",
        created_at="2026-05-06T09:20:00.000000Z",
    )
    friction.append(
        session_id="dogfood-day-2",
        run_id="run-day-2-b",
        category=categories[3],
        note="verifier passed before checking generated intake files",
        created_at="2026-05-06T10:25:00.000000Z",
    )


def _record_successful_run(metrics: MetricsStore, run_id: str, intake_id: str) -> None:
    stages = ("intake", "research", "graph", "synthesis", "ticket_draft")
    for index, stage_name in enumerate(stages):
        metrics.record(
            StageMetric(
                run_id=run_id,
                intake_id=None if stage_name == "intake" else intake_id,
                stage_name=stage_name,
                started_at=f"2026-05-05T09:{index:02d}:00.000000Z",
                completed_at=f"2026-05-05T09:{index:02d}:01.000000Z",
                duration_ms=1000 + index,
                status="success",
                error_message=None,
            )
        )


def _write_m3_config(workspace: Path, *, target: int) -> Path:
    config = {
        "milestone": "Synthetic M3 Closing",
        "criteria": {
            "metric_runs": {"kind": "metric_runs", "target": target},
            "friction_entries": {"kind": "friction_entries", "target": target},
            "dogfooding_days": {"kind": "dogfooding_days", "target": 3},
            "generated_retro": {"kind": "generated_retro", "target": 1, "paths": [".overture/retro/*.md"]},
        },
    }
    path = workspace / ".overture" / "m3-closing-config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _seed_three_designer_m3_workspace(*, workspace: Path, db_path: Path) -> tuple[dict[str, str], ...]:
    designers = (
        {
            "id": "designer-1",
            "email": "designer-1@example.test",
            "session_id": "m3-designer-1",
        },
        {
            "id": "designer-2",
            "email": "designer-2@example.test",
            "session_id": "m3-designer-2",
        },
        {
            "id": "designer-3",
            "email": "designer-3@example.test",
            "session_id": "m3-designer-3",
        },
    )
    friction_shapes = (
        ("slow", "source approval took long enough to lose ticket context"),
        ("confusing", "peer handoff language made the next action ambiguous"),
        ("broken", "M3 verification failed before generated intake paths were checked"),
    )
    metrics = MetricsStore(db_path)
    friction = FrictionLog(db_path)
    observations = ObservationLog(workspace / ".overture" / "observations.sqlite")

    for designer_index, designer in enumerate(designers, start=1):
        actor = AuthenticatedUser(user_id=designer["id"], email=designer["email"])
        for friction_index, (category, note) in enumerate(friction_shapes, start=1):
            run_id = f"{designer['id']}-run-{friction_index}"
            intake_id = f"{designer['id']}-intake-{friction_index}"
            started_minute = designer_index * 10 + friction_index
            _record_m3_successful_run(
                metrics,
                run_id=run_id,
                intake_id=intake_id,
                author_id=designer["id"],
                author_email=designer["email"],
                started_minute=started_minute,
            )
            observations.append(
                session_id=designer["session_id"],
                event_type="m3_smoke",
                route="/intake",
                action="record-friction",
                actor=actor,
                request={"intake_id": intake_id, "category": category},
                response={"run_id": run_id, "status": "confirmed"},
            )
            friction.append(
                session_id=designer["session_id"],
                run_id=run_id,
                category=category,
                note=note,
                created_at=f"2026-05-07T11:{started_minute:02d}:00.000000Z",
                confirmed=True,
                author_id=designer["id"],
                author_email=designer["email"],
            )
    return designers


def _record_m3_successful_run(
    metrics: MetricsStore,
    *,
    run_id: str,
    intake_id: str,
    author_id: str,
    author_email: str,
    started_minute: int,
) -> None:
    stages = ("intake", "research", "graph", "synthesis", "ticket_draft")
    for stage_index, stage_name in enumerate(stages):
        metrics.record(
            StageMetric(
                run_id=run_id,
                intake_id=None if stage_name == "intake" else intake_id,
                stage_name=stage_name,
                started_at=f"2026-05-07T10:{started_minute:02d}:{stage_index:02d}.000000Z",
                completed_at=f"2026-05-07T10:{started_minute:02d}:{stage_index + 1:02d}.000000Z",
                duration_ms=900 + stage_index,
                status="success",
                error_message=None,
                author_id=author_id,
                author_email=author_email,
            )
        )


if __name__ == "__main__":
    unittest.main()
