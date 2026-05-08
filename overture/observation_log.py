"""SQLite-backed passive observation log for authenticated wizard sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Callable, Iterable, Mapping

from .auth import AuthenticatedUser

OBSERVATION_LOG_EVENT_CAP = 500
FOUNDER_EMAILS_ENV = "OVERTURE_FOUNDER_EMAILS"


@dataclass(frozen=True)
class ObservationEvent:
    id: int
    session_id: str
    event_type: str
    route: str
    action: str
    occurred_at: str
    actor_id: str
    actor_email: str
    author_id: str
    author_email: str
    request: Mapping[str, object]
    response: Mapping[str, object]
    error: str | None = None


class ObservationLog:
    """Append-only session event recorder with read access scoped by identity."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        event_cap: int = OBSERVATION_LOG_EVENT_CAP,
        now: Callable[[], str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.event_cap = event_cap
        self.now = now or _utc_now_iso

    def append(
        self,
        *,
        session_id: str,
        event_type: str,
        route: str,
        action: str,
        actor: AuthenticatedUser,
        author_id: str | None = None,
        author_email: str | None = None,
        request: Mapping[str, object] | None = None,
        response: Mapping[str, object] | None = None,
        error: str | None = None,
    ) -> ObservationEvent:
        clean_session_id = str(session_id).strip()
        if not clean_session_id:
            raise ValueError("session_id is required")
        clean_author_id = str(author_id or actor.user_id).strip()
        clean_author_email = str(author_email or actor.email).strip()
        request_json = _json_dump(request or {})
        response_json = _json_dump(response or {})
        occurred_at = _millisecond_timestamp(str(self.now()))

        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                INSERT INTO observation_events (
                    session_id, event_type, route, action, occurred_at,
                    actor_id, actor_email, author_id, author_email,
                    request_json, response_json, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_session_id,
                    str(event_type),
                    str(route),
                    str(action),
                    occurred_at,
                    actor.user_id,
                    actor.email,
                    clean_author_id,
                    clean_author_email,
                    request_json,
                    response_json,
                    str(error) if error else None,
                ),
            )
            self._enforce_cap(connection, clean_session_id)
            row = connection.execute(
                "SELECT * FROM observation_events WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _event_from_row(row)

    def iter_session_events(
        self,
        session_id: str,
        *,
        user: AuthenticatedUser,
        founder_emails: Iterable[str] | None = None,
    ) -> tuple[ObservationEvent, ...]:
        with self._connect() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT * FROM observation_events
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (str(session_id),),
            ).fetchall()
        events = tuple(_event_from_row(row) for row in rows)
        if not events:
            return ()
        if not can_read_session_events(events, user=user, founder_emails=founder_emails):
            raise PermissionError("observation log is only readable by the session author or founder")
        return events

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS observation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                route TEXT NOT NULL,
                action TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_email TEXT NOT NULL,
                author_id TEXT NOT NULL,
                author_email TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                error TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_observation_events_session ON observation_events(session_id, id)"
        )

    def _enforce_cap(self, connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            """
            DELETE FROM observation_events
            WHERE id IN (
                SELECT id FROM observation_events
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (session_id, self.event_cap),
        )


def founder_emails_from_env() -> set[str]:
    raw = os.environ.get(FOUNDER_EMAILS_ENV, "")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def can_read_session_events(
    events: Iterable[ObservationEvent],
    *,
    user: AuthenticatedUser,
    founder_emails: Iterable[str] | None = None,
) -> bool:
    event_list = tuple(events)
    if not event_list:
        return True
    author_ids = {event.author_id for event in event_list}
    author_emails = {event.author_email.lower() for event in event_list}
    founders = {email.strip().lower() for email in (founder_emails if founder_emails is not None else founder_emails_from_env())}
    return user.user_id in author_ids or user.email.lower() in author_emails or user.email.lower() in founders


def _event_from_row(row: sqlite3.Row) -> ObservationEvent:
    return ObservationEvent(
        id=int(row["id"]),
        session_id=str(row["session_id"]),
        event_type=str(row["event_type"]),
        route=str(row["route"]),
        action=str(row["action"]),
        occurred_at=str(row["occurred_at"]),
        actor_id=str(row["actor_id"]),
        actor_email=str(row["actor_email"]),
        author_id=str(row["author_id"]),
        author_email=str(row["author_email"]),
        request=_json_load(str(row["request_json"])),
        response=_json_load(str(row["response_json"])),
        error=str(row["error"]) if row["error"] else None,
    )


def _json_dump(payload: Mapping[str, object]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))


def _json_load(payload: str) -> Mapping[str, object]:
    value = json.loads(payload)
    return value if isinstance(value, Mapping) else {}


def _millisecond_timestamp(value: str) -> str:
    if "." not in value:
        return value.replace("+00:00", "Z").replace("Z", ".000Z")
    prefix, suffix = value.split(".", 1)
    fraction = suffix
    timezone = ""
    for marker in ("Z", "+", "-"):
        if marker in suffix:
            index = suffix.find(marker)
            fraction = suffix[:index]
            timezone = suffix[index:]
            break
    timezone = timezone or "Z"
    return f"{prefix}.{fraction[:3].ljust(3, '0')}{timezone.replace('+00:00', 'Z')}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
