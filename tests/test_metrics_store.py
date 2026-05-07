import sqlite3
import tempfile
import unittest
from pathlib import Path

from overture.metrics_store import MetricsStore, ReworkSignal, StageMetric, TicketMetric, compute_duration_ms


class MetricsStoreTests(unittest.TestCase):
    def test_record_creates_database_and_inserts_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nested" / "metrics.sqlite"
            store = MetricsStore(db_path)
            metric = StageMetric(
                run_id="run-1",
                intake_id="intake-1",
                stage_name="research",
                started_at="2026-05-06T10:00:00.000000Z",
                completed_at="2026-05-06T10:00:01.250000Z",
                duration_ms=1250,
                status="success",
                error_message=None,
            )

            store.record(metric)

            self.assertTrue(db_path.exists())
            with sqlite3.connect(db_path) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM stage_metrics").fetchone()[0], 1)

    def test_record_upserts_same_run_and_stage_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MetricsStore(Path(tmpdir) / "metrics.sqlite")
            original = StageMetric(
                run_id="run-1",
                intake_id="intake-1",
                stage_name="research",
                started_at="2026-05-06T10:00:00.000000Z",
                completed_at="2026-05-06T10:00:01.000000Z",
                duration_ms=1000,
                status="success",
                error_message=None,
            )
            updated = StageMetric(
                run_id="run-1",
                intake_id="intake-2",
                stage_name="research",
                started_at="2026-05-06T10:00:00.000000Z",
                completed_at="2026-05-06T10:00:02.000000Z",
                duration_ms=2000,
                status="failed",
                error_message="timeout",
            )

            store.record(original)
            store.record(updated)

            rows = list(store.iter_stages())
            self.assertEqual(rows, [updated])

    def test_iter_stages_orders_by_started_at_and_honors_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MetricsStore(Path(tmpdir) / "metrics.sqlite")
            store.record(_metric("run-2", "synthesis", "2026-05-06T10:00:02.000000Z", 20))
            store.record(_metric("run-1", "intake", "2026-05-06T10:00:00.000000Z", 10))
            store.record(_metric("run-3", "graph", "2026-05-06T10:00:01.000000Z", 30))

            rows = list(store.iter_stages(limit=2))

            self.assertEqual([row.stage_name for row in rows], ["intake", "graph"])

    def test_summary_computes_per_stage_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MetricsStore(Path(tmpdir) / "metrics.sqlite")
            for index, duration_ms in enumerate((100, 200, 300, 400), start=1):
                store.record(_metric(f"run-{index}", "research", f"2026-05-06T10:00:0{index}.000000Z", duration_ms))
            store.record(
                _metric(
                    "run-5",
                    "ticket_draft",
                    "2026-05-06T10:00:05.000000Z",
                    500,
                    status="failed",
                    error_message="bad template",
                )
            )

            summary = store.summary()

            self.assertEqual(set(summary), {"research", "ticket_draft"})
            self.assertEqual(summary["research"]["count"], 4)
            self.assertEqual(summary["research"]["mean_ms"], 250)
            self.assertEqual(summary["research"]["median_ms"], 250.0)
            self.assertEqual(summary["research"]["p95_ms"], 385.0)
            self.assertEqual(summary["research"]["success_rate"], 1.0)
            self.assertEqual(summary["ticket_draft"]["count"], 1)
            self.assertEqual(summary["ticket_draft"]["median_ms"], 500)
            self.assertEqual(summary["ticket_draft"]["p95_ms"], 500)
            self.assertEqual(summary["ticket_draft"]["success_rate"], 0.0)
            for stats in summary.values():
                self.assertIsInstance(stats["count"], int)
                self.assertIsInstance(stats["median_ms"], (float, int))
                self.assertIsInstance(stats["p95_ms"], (float, int))
                self.assertGreaterEqual(stats["success_rate"], 0.0)
                self.assertLessEqual(stats["success_rate"], 1.0)

    def test_compute_duration_ms_parses_iso_microseconds_and_rejects_negative_duration(self) -> None:
        self.assertEqual(
            compute_duration_ms("2026-05-06T10:00:00.123456Z", "2026-05-06T10:00:01.623456Z"),
            1500,
        )

        with self.assertRaises(ValueError):
            compute_duration_ms("2026-05-06T10:00:01.000000Z", "2026-05-06T10:00:00.999999Z")

    def test_record_rework_signal_increments_matching_ticket_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MetricsStore(Path(tmpdir) / "metrics.sqlite")
            store.record_ticket(
                TicketMetric(
                    ticket_id="ERI-1",
                    author_id="designer-1",
                    author_email="designer-1@example.test",
                    sprint_label="m3-s3",
                    milestone="M3",
                )
            )

            inserted = store.record_rework_signal(
                ReworkSignal(signal_id="signal-1", ticket_id="ERI-1", detected_at="2026-05-07T10:00:00.000000Z")
            )

            self.assertTrue(inserted)
            [ticket] = list(store.iter_ticket_rework_counters())
            self.assertEqual(ticket.ticket_id, "ERI-1")
            self.assertEqual(ticket.rework_count, 1)

    def test_rework_counts_by_author_for_milestone_counts_five_synthetic_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MetricsStore(Path(tmpdir) / "metrics.sqlite")
            store.record_ticket(
                TicketMetric(
                    ticket_id="ERI-1",
                    author_id="designer-1",
                    author_email="designer-1@example.test",
                    sprint_label="m3-s3",
                    milestone="M3",
                )
            )
            store.record_ticket(
                TicketMetric(
                    ticket_id="ERI-2",
                    author_id="designer-2",
                    author_email="designer-2@example.test",
                    sprint_label="m3-s3",
                    milestone="M3",
                )
            )

            for index, ticket_id in enumerate(("ERI-1", "ERI-1", "ERI-1", "ERI-2", "ERI-2"), start=1):
                store.record_rework_signal(
                    ReworkSignal(
                        signal_id=f"signal-{index}",
                        ticket_id=ticket_id,
                        detected_at=f"2026-05-07T10:00:0{index}.000000Z",
                    )
                )

            counts = store.rework_counts_by_author(milestone="M3")

            self.assertEqual(
                counts,
                {
                    "designer-1": {"author_email": "designer-1@example.test", "rework_count": 3},
                    "designer-2": {"author_email": "designer-2@example.test", "rework_count": 2},
                },
            )

    def test_rework_rate_by_sprint_label_uses_rework_over_total_tickets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MetricsStore(Path(tmpdir) / "metrics.sqlite")
            for ticket_id, sprint_label in (
                ("ERI-1", "m3-s3"),
                ("ERI-2", "m3-s3"),
                ("ERI-3", "m3-s3"),
                ("ERI-4", "m3-s4"),
            ):
                store.record_ticket(TicketMetric(ticket_id=ticket_id, sprint_label=sprint_label, milestone="M3"))

            store.record_rework_signal(
                ReworkSignal(signal_id="signal-1", ticket_id="ERI-1", detected_at="2026-05-07T10:00:00.000000Z")
            )
            store.record_rework_signal(
                ReworkSignal(signal_id="signal-2", ticket_id="ERI-2", detected_at="2026-05-07T10:00:01.000000Z")
            )

            rates = store.rework_rate_by_sprint_label()

            self.assertEqual(rates["m3-s3"], {"rework_count": 2, "total_tickets": 3, "rework_rate": 2 / 3})
            self.assertEqual(rates["m3-s4"], {"rework_count": 0, "total_tickets": 1, "rework_rate": 0.0})

    def test_record_rework_signal_is_idempotent_by_signal_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MetricsStore(Path(tmpdir) / "metrics.sqlite")
            store.record_ticket(TicketMetric(ticket_id="ERI-1", sprint_label="m3-s3", milestone="M3"))
            signal = ReworkSignal(signal_id="signal-1", ticket_id="ERI-1", detected_at="2026-05-07T10:00:00.000000Z")

            self.assertTrue(store.record_rework_signal(signal))
            self.assertFalse(store.record_rework_signal(signal))

            [ticket] = list(store.iter_ticket_rework_counters())
            self.assertEqual(ticket.rework_count, 1)

    def test_rework_counts_by_author_includes_unknown_author_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MetricsStore(Path(tmpdir) / "metrics.sqlite")
            store.record_ticket(TicketMetric(ticket_id="ERI-legacy", sprint_label="pre-m3", milestone="M3"))
            store.record_rework_signal(
                ReworkSignal(
                    signal_id="signal-legacy",
                    ticket_id="ERI-legacy",
                    detected_at="2026-05-07T10:00:00.000000Z",
                )
            )

            self.assertEqual(
                store.rework_counts_by_author(milestone="M3"),
                {"unknown author": {"author_email": None, "rework_count": 1}},
            )


def _metric(
    run_id: str,
    stage_name: str,
    started_at: str,
    duration_ms: int,
    *,
    status: str = "success",
    error_message: str | None = None,
) -> StageMetric:
    return StageMetric(
        run_id=run_id,
        intake_id="intake-1",
        stage_name=stage_name,
        started_at=started_at,
        completed_at=started_at,
        duration_ms=duration_ms,
        status=status,
        error_message=error_message,
    )


if __name__ == "__main__":
    unittest.main()
