"""SQLite-backed export ledger for Linear issue creation.

Ticket text is hashed after normalizing line endings to LF, stripping trailing
whitespace from each line, and reducing trailing newlines to exactly one final
newline. This keeps hashes stable across common editor and platform differences
without storing ticket bodies in the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3

DEFAULT_EXPORT_DB_PATH = Path(".overture") / "exports.sqlite"


@dataclass(frozen=True)
class ExportRecord:
    ticket_path: str
    ticket_hash: str
    linear_issue_id: str
    linear_url: str
    exported_at: str


class ExportLedger:
    """Persist exported ticket paths and their Linear issue destinations."""

    def __init__(self, db_path: Path | str = DEFAULT_EXPORT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        with self._connect():
            pass

    def find(self, ticket_path: str) -> ExportRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ticket_path, ticket_hash, linear_issue_id, linear_url, exported_at
                FROM exports
                WHERE ticket_path = ?
                """,
                (ticket_path,),
            ).fetchone()

        return _record_from_row(row) if row else None

    def record(
        self,
        ticket_path: str,
        ticket_hash: str,
        linear_issue_id: str,
        linear_url: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO exports (
                    ticket_path,
                    ticket_hash,
                    linear_issue_id,
                    linear_url,
                    exported_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticket_path) DO UPDATE SET
                    ticket_hash = excluded.ticket_hash,
                    linear_issue_id = excluded.linear_issue_id,
                    linear_url = excluded.linear_url,
                    exported_at = excluded.exported_at
                """,
                (ticket_path, ticket_hash, linear_issue_id, linear_url, _utc_now()),
            )

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        return connection


def compute_hash(ticket_text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in ticket_text.splitlines()).rstrip("\n") + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS exports (
            ticket_path TEXT PRIMARY KEY,
            ticket_hash TEXT NOT NULL,
            linear_issue_id TEXT NOT NULL,
            linear_url TEXT NOT NULL,
            exported_at TEXT NOT NULL
        )
        """
    )


def _record_from_row(row: sqlite3.Row) -> ExportRecord:
    return ExportRecord(
        ticket_path=row["ticket_path"],
        ticket_hash=row["ticket_hash"],
        linear_issue_id=row["linear_issue_id"],
        linear_url=row["linear_url"],
        exported_at=row["exported_at"],
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
