"""SQLite ledger for Linear exports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterator


@dataclass(frozen=True)
class ExportRecord:
    ticket_path: str
    title: str
    linear_issue_id: str
    linear_identifier: str
    linear_url: str
    created_at: str


class ExportStore:
    """Persist exported ticket paths so re-runs are idempotent."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def get(self, ticket_path: Path | str) -> ExportRecord | None:
        key = _ticket_key(ticket_path)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ticket_path, title, linear_issue_id, linear_identifier, linear_url, created_at
                FROM exports
                WHERE ticket_path = ?
                """,
                (key,),
            ).fetchone()
        if row is None:
            return None
        return ExportRecord(*row)

    def insert(
        self,
        *,
        ticket_path: Path | str,
        title: str,
        linear_issue_id: str,
        linear_identifier: str,
        linear_url: str,
    ) -> ExportRecord:
        key = _ticket_key(ticket_path)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO exports (ticket_path, title, linear_issue_id, linear_identifier, linear_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, title, linear_issue_id, linear_identifier, linear_url),
            )
            row = connection.execute(
                """
                SELECT ticket_path, title, linear_issue_id, linear_identifier, linear_url, created_at
                FROM exports
                WHERE ticket_path = ?
                """,
                (key,),
            ).fetchone()
        return ExportRecord(*row)

    def all(self) -> tuple[ExportRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticket_path, title, linear_issue_id, linear_identifier, linear_url, created_at
                FROM exports
                ORDER BY created_at, ticket_path
                """
            ).fetchall()
        return tuple(ExportRecord(*row) for row in rows)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS exports (
                    ticket_path TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    linear_issue_id TEXT NOT NULL,
                    linear_identifier TEXT NOT NULL,
                    linear_url TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


def _ticket_key(ticket_path: Path | str) -> str:
    return str(Path(ticket_path).expanduser().resolve())


def iter_export_rows(db_path: Path | str) -> Iterator[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        yield from connection.execute("SELECT * FROM exports ORDER BY created_at, ticket_path")
    finally:
        connection.close()
