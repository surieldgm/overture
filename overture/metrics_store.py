"""SQLite-backed pipeline stage timing metrics.

The summary p95 is computed from raw local samples and is unreliable for small
sample sizes, especially below n = 20. Consumers should read `count` alongside
percentiles before drawing conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
import statistics
from typing import Iterable, Iterator

DEFAULT_METRICS_DB_PATH = Path(".overture") / "metrics.sqlite"


@dataclass(frozen=True)
class StageMetric:
    run_id: str
    intake_id: str | None
    stage_name: str
    started_at: str
    completed_at: str
    duration_ms: int
    status: str
    error_message: str | None
    author_id: str | None = None
    author_email: str | None = None


class MetricsStore:
    """Persist per-stage timing metrics for Overture pipeline runs."""

    def __init__(self, db_path: Path | str = DEFAULT_METRICS_DB_PATH) -> None:
        self.db_path = Path(db_path)
        with self._connect():
            pass

    def record(self, metric: StageMetric) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO stage_metrics (
                    run_id,
                    intake_id,
                    stage_name,
                    started_at,
                    completed_at,
                    duration_ms,
                    status,
                    error_message,
                    author_id,
                    author_email
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, stage_name) DO UPDATE SET
                    intake_id = excluded.intake_id,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    duration_ms = excluded.duration_ms,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    author_id = excluded.author_id,
                    author_email = excluded.author_email
                """,
                (
                    metric.run_id,
                    metric.intake_id,
                    metric.stage_name,
                    metric.started_at,
                    metric.completed_at,
                    metric.duration_ms,
                    metric.status,
                    metric.error_message,
                    metric.author_id,
                    metric.author_email,
                ),
            )

    def iter_stages(self, limit: int | None = None) -> Iterator[StageMetric]:
        query = """
            SELECT run_id, intake_id, stage_name, started_at, completed_at, duration_ms, status, error_message, author_id, author_email
            FROM stage_metrics
            ORDER BY started_at
        """
        parameters: tuple[int, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        for row in rows:
            yield _metric_from_row(row)

    def iter_stages_for_last_runs(self, run_limit: int) -> Iterator[StageMetric]:
        if run_limit < 1:
            raise ValueError("run_limit must be at least 1")

        with self._connect() as connection:
            run_rows = connection.execute(
                """
                SELECT run_id
                FROM stage_metrics
                GROUP BY run_id
                ORDER BY max(started_at) DESC
                LIMIT ?
                """,
                (run_limit,),
            ).fetchall()
            run_ids = [row["run_id"] for row in run_rows]
            if not run_ids:
                return

            placeholders = ", ".join("?" for _ in run_ids)
            rows = connection.execute(
                f"""
                SELECT run_id, intake_id, stage_name, started_at, completed_at, duration_ms, status, error_message, author_id, author_email
                FROM stage_metrics
                WHERE run_id IN ({placeholders})
                ORDER BY started_at
                """,
                tuple(run_ids),
            ).fetchall()

        for row in rows:
            yield _metric_from_row(row)

    def count_runs(self, run_limit: int | None = None) -> int:
        if run_limit is not None and run_limit < 1:
            raise ValueError("run_limit must be at least 1")

        with self._connect() as connection:
            if run_limit is None:
                row = connection.execute("SELECT count(DISTINCT run_id) FROM stage_metrics").fetchone()
                return int(row[0])
            row = connection.execute(
                """
                SELECT count(*)
                FROM (
                    SELECT run_id
                    FROM stage_metrics
                    GROUP BY run_id
                    ORDER BY max(started_at) DESC
                    LIMIT ?
                )
                """,
                (run_limit,),
            ).fetchone()
            return int(row[0])

    def summary(self, *, last_runs: int | None = None) -> dict[str, dict[str, float | int]]:
        grouped: dict[str, list[StageMetric]] = {}
        metrics: Iterable[StageMetric]
        if last_runs is None:
            metrics = self.iter_stages()
        else:
            metrics = self.iter_stages_for_last_runs(last_runs)

        for metric in metrics:
            grouped.setdefault(metric.stage_name, []).append(metric)

        summaries: dict[str, dict[str, float | int]] = {}
        for stage_name, metrics in grouped.items():
            durations = [metric.duration_ms for metric in metrics]
            success_count = sum(1 for metric in metrics if metric.status == "success")
            summaries[stage_name] = {
                "count": len(durations),
                "mean_ms": statistics.mean(durations),
                "median_ms": statistics.median(durations),
                "p95_ms": _p95(durations),
                "success_rate": success_count / len(durations),
            }

        return summaries

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        return connection


def compute_duration_ms(started_at: str, completed_at: str) -> int:
    started = _parse_iso_timestamp(started_at)
    completed = _parse_iso_timestamp(completed_at)
    duration = completed - started
    if duration.total_seconds() < 0:
        raise ValueError("completed_at must not be earlier than started_at")
    return int(duration.total_seconds() * 1000)


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stage_metrics (
            run_id TEXT NOT NULL,
            intake_id TEXT,
            stage_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT,
            author_id TEXT,
            author_email TEXT,
            PRIMARY KEY (run_id, stage_name)
        )
        """
    )
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(stage_metrics)").fetchall()
    }
    if "author_id" not in columns:
        connection.execute("ALTER TABLE stage_metrics ADD COLUMN author_id TEXT")
    if "author_email" not in columns:
        connection.execute("ALTER TABLE stage_metrics ADD COLUMN author_email TEXT")


def _metric_from_row(row: sqlite3.Row) -> StageMetric:
    return StageMetric(
        run_id=row["run_id"],
        intake_id=row["intake_id"],
        stage_name=row["stage_name"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_ms=row["duration_ms"],
        status=row["status"],
        error_message=row["error_message"],
        author_id=row["author_id"],
        author_email=row["author_email"],
    )


def _parse_iso_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _p95(durations: list[int]) -> float | int:
    if len(durations) == 1:
        return durations[0]
    return statistics.quantiles(durations, n=100, method="inclusive")[94]
