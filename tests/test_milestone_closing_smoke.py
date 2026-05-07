import tempfile
import unittest
from pathlib import Path

from overture.closing_chain import (
    generate_retro,
    seed_backlog_from_friction,
    verify_milestone_closing,
)
from overture.friction_log import FRICTION_CATEGORIES, FrictionLog
from overture.intake import stable_intake_id
from overture.metrics_store import MetricsStore, StageMetric


class MilestoneClosingSmokeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
