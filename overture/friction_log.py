"""SQLite-backed operator friction log entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator

from .metrics_store import DEFAULT_METRICS_DB_PATH

FRICTION_CATEGORIES = ("slow", "confusing", "broken", "surprising")


@dataclass(frozen=True)
class FrictionEntry:
    id: int | None
    session_id: str
    run_id: str
    category: str
    note: str
    created_at: str
    confirmed: bool = False
    author_id: str | None = None
    author_email: str | None = None


class FrictionLog:
    """Persist dogfooding friction entries alongside run metrics."""

    def __init__(self, db_path: Path | str = DEFAULT_METRICS_DB_PATH) -> None:
        self.db_path = Path(db_path)
        with self._connect():
            pass

    def append(
        self,
        *,
        session_id: str,
        run_id: str,
        category: str,
        note: str,
        created_at: str | None = None,
        confirmed: bool = False,
        author_id: str | None = None,
        author_email: str | None = None,
    ) -> FrictionEntry:
        session_id = _require_text(session_id, "session_id")
        run_id = _require_text(run_id, "run_id")
        note = _require_text(note, "note")
        if category not in FRICTION_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(FRICTION_CATEGORIES)}")

        timestamp = created_at or _utc_now_iso()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO friction_entries (
                    session_id, run_id, category, note, created_at, confirmed, author_id, author_email
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, run_id, category, note, timestamp, int(confirmed), _optional_text(author_id), _optional_text(author_email)),
            )
            entry_id = int(cursor.lastrowid)

        return FrictionEntry(
            id=entry_id,
            session_id=session_id,
            run_id=run_id,
            category=category,
            note=note,
            created_at=timestamp,
            confirmed=confirmed,
            author_id=_optional_text(author_id),
            author_email=_optional_text(author_email),
        )

    def confirm(self, entry_id: int) -> FrictionEntry:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE friction_entries
                SET confirmed = 1
                WHERE id = ?
                """,
                (entry_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"friction entry not found: {entry_id}")
            row = connection.execute(
                """
                SELECT id, session_id, run_id, category, note, created_at, confirmed, author_id, author_email
                FROM friction_entries
                WHERE id = ?
                """,
                (entry_id,),
            ).fetchone()

        return _entry_from_row(row)

    def iter_entries(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        confirmed: bool | None = None,
    ) -> Iterator[FrictionEntry]:
        conditions: list[str] = []
        parameters: list[str] = []
        if session_id is not None:
            conditions.append("session_id = ?")
            parameters.append(session_id)
        if run_id is not None:
            conditions.append("run_id = ?")
            parameters.append(run_id)
        if confirmed is not None:
            conditions.append("confirmed = ?")
            parameters.append(str(int(confirmed)))

        query = """
            SELECT id, session_id, run_id, category, note, created_at, confirmed, author_id, author_email
            FROM friction_entries
        """
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY datetime(created_at), id"

        with self._connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()

        for row in rows:
            yield _entry_from_row(row)

    def latest_run_id(self) -> str | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT run_id
                    FROM stage_metrics
                    GROUP BY run_id
                    ORDER BY max(started_at) DESC
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table: stage_metrics" in str(exc):
                return None
            raise
        if row is None:
            return None
        return str(row["run_id"])

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS friction_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            category TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL,
            author_id TEXT,
            author_email TEXT,
            CHECK (category IN ('slow', 'confusing', 'broken', 'surprising'))
        )
        """
    )
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(friction_entries)").fetchall()
    }
    if "confirmed" not in columns:
        connection.execute("ALTER TABLE friction_entries ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 0")
    if "author_id" not in columns:
        connection.execute("ALTER TABLE friction_entries ADD COLUMN author_id TEXT")
    if "author_email" not in columns:
        connection.execute("ALTER TABLE friction_entries ADD COLUMN author_email TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_friction_entries_session_run
        ON friction_entries (session_id, run_id, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_friction_entries_run
        ON friction_entries (run_id, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_friction_entries_confirmed
        ON friction_entries (confirmed, created_at)
        """
    )


def _entry_from_row(row: sqlite3.Row) -> FrictionEntry:
    return FrictionEntry(
        id=row["id"],
        session_id=row["session_id"],
        run_id=row["run_id"],
        category=row["category"],
        note=row["note"],
        created_at=row["created_at"],
        confirmed=bool(row["confirmed"]),
        author_id=row["author_id"],
        author_email=row["author_email"],
    )


def _require_text(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
