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


@dataclass(frozen=True)
class ReworkMetric:
    event_id: str
    issue_id: str
    issue_identifier: str | None
    author_id: str
    author_email: str | None
    from_state: str
    to_state: str
    occurred_at: str


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

    def record_rework(self, metric: ReworkMetric) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rework_metrics (
                    event_id,
                    issue_id,
                    issue_identifier,
                    author_id,
                    author_email,
                    from_state,
                    to_state,
                    occurred_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    issue_id = excluded.issue_id,
                    issue_identifier = excluded.issue_identifier,
                    author_id = excluded.author_id,
                    author_email = excluded.author_email,
                    from_state = excluded.from_state,
                    to_state = excluded.to_state,
                    occurred_at = excluded.occurred_at
                """,
                (
                    metric.event_id,
                    metric.issue_id,
                    metric.issue_identifier,
                    metric.author_id,
                    metric.author_email,
                    metric.from_state,
                    metric.to_state,
                    metric.occurred_at,
                ),
            )

    def rework_counts_by_author(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT author_id, count(*) AS count
                FROM rework_metrics
                GROUP BY author_id
                ORDER BY author_id
                """
            ).fetchall()
        return {str(row["author_id"]): int(row["count"]) for row in rows}

    def iter_rework_metrics(self) -> Iterator[ReworkMetric]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, issue_id, issue_identifier, author_id, author_email, from_state, to_state, occurred_at
                FROM rework_metrics
                ORDER BY occurred_at, event_id
                """
            ).fetchall()
        for row in rows:
            yield _rework_metric_from_row(row)

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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS rework_metrics (
            event_id TEXT NOT NULL PRIMARY KEY,
            issue_id TEXT NOT NULL,
            issue_identifier TEXT,
            author_id TEXT NOT NULL,
            author_email TEXT,
            from_state TEXT NOT NULL,
            to_state TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        )
        """
    )


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


def _rework_metric_from_row(row: sqlite3.Row) -> ReworkMetric:
    return ReworkMetric(
        event_id=row["event_id"],
        issue_id=row["issue_id"],
        issue_identifier=row["issue_identifier"],
        author_id=row["author_id"],
        author_email=row["author_email"],
        from_state=row["from_state"],
        to_state=row["to_state"],
        occurred_at=row["occurred_at"],
    )


def _parse_iso_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _p95(durations: list[int]) -> float | int:
    if len(durations) == 1:
        return durations[0]
    return statistics.quantiles(durations, n=100, method="inclusive")[94]
