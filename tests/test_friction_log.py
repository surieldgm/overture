import tempfile
import unittest
from pathlib import Path
import sqlite3

from overture.friction_log import FrictionLog
from overture.metrics_store import MetricsStore, StageMetric


class FrictionLogTests(unittest.TestCase):
    def test_append_round_trips_across_store_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            first_store = FrictionLog(db_path)

            first_store.append(
                session_id="dogfood-day-1",
                run_id="run-1",
                category="slow",
                note="research approval paused long enough to lose context",
                created_at="2026-05-07T10:00:00.000000Z",
            )

            second_store = FrictionLog(db_path)
            rows = list(second_store.iter_entries(session_id="dogfood-day-1", run_id="run-1"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].session_id, "dogfood-day-1")
        self.assertEqual(rows[0].run_id, "run-1")
        self.assertEqual(rows[0].category, "slow")
        self.assertEqual(rows[0].note, "research approval paused long enough to lose context")
        self.assertFalse(rows[0].confirmed)

    def test_append_and_confirm_flag_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FrictionLog(Path(tmpdir) / "metrics.sqlite")
            appended = store.append(
                session_id="dogfood-day-1",
                run_id="run-1",
                category="slow",
                note="research approval paused long enough to lose context",
                confirmed=True,
            )
            unconfirmed = store.append(
                session_id="dogfood-day-1",
                run_id="run-1",
                category="confusing",
                note="handoff status was unclear",
            )

            confirmed_later = store.confirm(unconfirmed.id or 0)
            confirmed_rows = list(store.iter_entries(confirmed=True))

        self.assertTrue(appended.confirmed)
        self.assertTrue(confirmed_later.confirmed)
        self.assertEqual([entry.id for entry in confirmed_rows], [appended.id, unconfirmed.id])

    def test_iter_entries_filters_by_session_and_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FrictionLog(Path(tmpdir) / "metrics.sqlite")
            store.append(
                session_id="dogfood-day-1",
                run_id="run-1",
                category="confusing",
                note="unclear prompt",
                confirmed=True,
                created_at="2026-05-07T10:00:00.000000Z",
            )
            store.append(
                session_id="dogfood-day-1",
                run_id="run-2",
                category="broken",
                note="export failed",
                created_at="2026-05-07T10:01:00.000000Z",
            )
            store.append(
                session_id="dogfood-day-2",
                run_id="run-1",
                category="surprising",
                note="unexpected handoff",
                created_at="2026-05-07T10:02:00.000000Z",
            )

            day_one = list(store.iter_entries(session_id="dogfood-day-1"))
            run_one = list(store.iter_entries(run_id="run-1"))
            exact = list(store.iter_entries(session_id="dogfood-day-1", run_id="run-1"))
            confirmed = list(store.iter_entries(confirmed=True))

        self.assertEqual([entry.note for entry in day_one], ["unclear prompt", "export failed"])
        self.assertEqual([entry.note for entry in run_one], ["unclear prompt", "unexpected handoff"])
        self.assertEqual([entry.note for entry in exact], ["unclear prompt"])
        self.assertEqual([entry.note for entry in confirmed], ["unclear prompt"])

    def test_latest_run_id_uses_most_recent_metrics_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            metrics = MetricsStore(db_path)
            metrics.record(_metric("run-1", "2026-05-07T10:00:00.000000Z"))
            metrics.record(_metric("run-2", "2026-05-07T11:00:00.000000Z"))

            self.assertEqual(FrictionLog(db_path).latest_run_id(), "run-2")

    def test_append_rejects_unknown_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FrictionLog(Path(tmpdir) / "metrics.sqlite")

            with self.assertRaises(ValueError):
                store.append(
                    session_id="dogfood-day-1",
                    run_id="run-1",
                    category="annoying",
                    note="too broad",
                )

    def test_append_accepts_designer_rollout_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FrictionLog(Path(tmpdir) / "metrics.sqlite")

            entry = store.append(
                session_id="m3",
                run_id="three-designer-rollout",
                category="designer-experience",
                note="source approval state is hard to scan",
                confirmed=True,
            )

        self.assertEqual(entry.category, "designer-experience")
        self.assertTrue(entry.confirmed)

    def test_existing_legacy_category_check_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.sqlite"
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE friction_entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        category TEXT NOT NULL,
                        note TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        author_id TEXT,
                        author_email TEXT,
                        confirmed INTEGER NOT NULL DEFAULT 0,
                        CHECK (category IN ('slow', 'confusing', 'broken', 'surprising'))
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO friction_entries (
                        session_id, run_id, category, note, created_at, confirmed
                    )
                    VALUES ('m1', 'run-1', 'slow', 'legacy row', '2026-05-07T10:00:00.000000Z', 1)
                    """
                )

            store = FrictionLog(db_path)
            store.append(
                session_id="m3",
                run_id="three-designer-rollout",
                category="onboarding",
                note="first-run setup lacks enough context",
                confirmed=True,
            )
            entries = list(store.iter_entries(confirmed=True))

        self.assertEqual([entry.category for entry in entries], ["slow", "onboarding"])


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


if __name__ == "__main__":
    unittest.main()
