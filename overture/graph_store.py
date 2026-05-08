"""SQLite-backed graph record store for Overture.

The store is intentionally small and uses SQLite's single-writer model. WAL mode
is enabled for every connection so sequential readers can observe committed graph
updates while future orchestration remains conservative about concurrent writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .graph import GraphRecord
from .synthesis import GraphContext

DEFAULT_GRAPH_DB_PATH = Path(".overture") / "graph.sqlite"
NODE_KINDS = {
    "Source",
    "ResearchItem",
    "Evidence",
    "Claim",
    "Idea",
    "Need",
    "Component",
    "Capability",
    "Constraint",
    "Risk",
    "TicketCandidate",
    "UserInput",
}
EDGE_KINDS = {
    "CITES",
    "HAS_CLAIM",
    "derived_from",
    "supports",
    "addresses",
    "depends_on",
    "embeds",
    "instantiates",
    "references",
    "requires",
    "suggests",
}


class SqliteGraphStore:
    """Persist graph ingestion records in a local SQLite database."""

    def __init__(self, db_path: Path | str = DEFAULT_GRAPH_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def upsert_record(self, record: GraphRecord) -> None:
        """Insert or update one graph record by its stable key."""

        created_at = _utc_now()
        properties = _json(record.properties)
        with self._connect() as connection:
            if record.kind in NODE_KINDS:
                connection.execute(
                    """
                    INSERT INTO nodes (id, kind, properties, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind = excluded.kind,
                        properties = excluded.properties,
                        created_at = excluded.created_at
                    """,
                    (record.key, record.kind, properties, created_at),
                )
                return

            if record.kind in EDGE_KINDS:
                from_id = _required_property(record, "from")
                to_id = _required_property(record, "to")
                connection.execute(
                    """
                    INSERT INTO edges (from_id, to_id, kind, properties, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(from_id, to_id, kind) DO UPDATE SET
                        properties = excluded.properties,
                        created_at = excluded.created_at
                    """,
                    (from_id, to_id, record.kind, properties, created_at),
                )
                return

            raise ValueError(f"unsupported graph record kind: {record.kind}")

    def upsert_records(self, records: Iterable[GraphRecord]) -> int:
        """Insert or update graph records and return the number accepted."""

        count = 0
        for record in records:
            self.upsert_record(record)
            count += 1
        return count

    def load_context(self, limit: int = 100) -> GraphContext:
        """Load recent nodes and every edge touching those nodes."""

        if limit < 1:
            return GraphContext()

        with self._connect() as connection:
            node_rows = connection.execute(
                """
                SELECT id, kind, properties, created_at
                FROM nodes
                ORDER BY created_at DESC, id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            nodes = tuple(_node_mapping(row) for row in node_rows)
            node_ids = tuple(str(node["id"]) for node in nodes)
            if not node_ids:
                return GraphContext()

            placeholders = ",".join("?" for _ in node_ids)
            edge_rows = connection.execute(
                f"""
                SELECT from_id, to_id, kind, properties, created_at
                FROM edges
                WHERE from_id IN ({placeholders}) OR to_id IN ({placeholders})
                ORDER BY created_at DESC, from_id ASC, to_id ASC, kind ASC
                """,
                (*node_ids, *node_ids),
            ).fetchall()

        return GraphContext(nodes=nodes, edges=tuple(_edge_mapping(row) for row in edge_rows))

    def list_nodes(self, *, kind: str | None = None, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        """List persisted nodes, optionally restricted by kind."""

        query = "SELECT id, kind, properties, created_at FROM nodes"
        params: list[Any] = []
        if kind is not None:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY created_at DESC, id ASC"
        if limit is not None:
            if limit < 1:
                return ()
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_node_mapping(row) for row in rows)

    def list_edges(self, *, kind: str | None = None, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        """List persisted edges, optionally restricted by kind."""

        query = "SELECT from_id, to_id, kind, properties, created_at FROM edges"
        params: list[Any] = []
        if kind is not None:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY created_at DESC, from_id ASC, to_id ASC, kind ASC"
        if limit is not None:
            if limit < 1:
                return ()
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_edge_mapping(row) for row in rows)

    def iter_records(self) -> tuple[GraphRecord, ...]:
        """Return every persisted graph record in migration-safe form."""

        records: list[GraphRecord] = []
        for node in reversed(self.list_nodes()):
            node_id = str(node["id"])
            records.append(
                GraphRecord(
                    kind=str(node["kind"]),  # type: ignore[arg-type]
                    key=node_id,
                    properties=dict(node.get("properties") or {}),
                )
            )
        for edge in reversed(self.list_edges()):
            from_id = str(edge["from"])
            to_id = str(edge["to"])
            kind = str(edge["kind"])
            properties = dict(edge.get("properties") or {})
            properties["from"] = from_id
            properties["to"] = to_id
            records.append(
                GraphRecord(
                    kind=kind,  # type: ignore[arg-type]
                    key=str(edge.get("id") or f"{from_id}:{kind}:{to_id}"),
                    properties=properties,
                )
            )
        return tuple(records)

    def table_counts(self) -> dict[str, int]:
        """Return row counts for migration and integrity checks."""

        with self._connect() as connection:
            return {
                "nodes": int(connection.execute("SELECT count(*) FROM nodes").fetchone()[0]),
                "edges": int(connection.execute("SELECT count(*) FROM edges").fetchone()[0]),
            }

    def record_linear_webhook_event(
        self,
        *,
        event_id: str,
        event_timestamp: str,
        issue_id: str,
        previous_status: str | None,
        new_status: str,
        actor: dict[str, Any],
        raw_event: dict[str, Any],
    ) -> bool:
        """Persist a normalized Linear issue webhook event.

        Returns True when a new row was inserted and False when the event was a
        duplicate delivery of an already captured lifecycle transition.
        """

        received_at = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO linear_webhook_events (
                    event_id,
                    event_timestamp,
                    issue_id,
                    previous_status,
                    new_status,
                    actor,
                    raw_event,
                    received_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_timestamp,
                    issue_id,
                    previous_status,
                    new_status,
                    _json(actor),
                    _json(raw_event),
                    received_at,
                ),
            )
            return cursor.rowcount > 0

    def list_linear_webhook_events(self) -> tuple[dict[str, Any], ...]:
        """Return captured Linear webhook events in receive order."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_timestamp, issue_id, previous_status, new_status, actor, raw_event, received_at
                FROM linear_webhook_events
                ORDER BY received_at ASC, issue_id ASC
                """
            ).fetchall()
        return tuple(_linear_webhook_event_mapping(row) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        _ensure_schema(connection)
        return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            properties TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            properties TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (from_id, to_id, kind)
        );

        CREATE TABLE IF NOT EXISTS linear_webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            event_timestamp TEXT NOT NULL,
            issue_id TEXT NOT NULL,
            previous_status TEXT,
            new_status TEXT NOT NULL,
            actor TEXT NOT NULL,
            raw_event TEXT NOT NULL,
            received_at TEXT NOT NULL,
            UNIQUE(issue_id, event_timestamp, new_status)
        );
        """
    )


def _node_mapping(row: sqlite3.Row) -> dict[str, Any]:
    properties = _loads(row["properties"])
    return {
        "id": row["id"],
        "type": row["kind"],
        "kind": row["kind"],
        "properties": properties,
        "created_at": row["created_at"],
        **properties,
    }


def _edge_mapping(row: sqlite3.Row) -> dict[str, Any]:
    properties = _loads(row["properties"])
    return {
        "id": f"{row['from_id']}__{row['kind']}__{row['to_id']}",
        "type": row["kind"],
        "kind": row["kind"],
        "from": row["from_id"],
        "to": row["to_id"],
        "properties": properties,
        "created_at": row["created_at"],
        **properties,
    }


def _linear_webhook_event_mapping(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "timestamp": row["event_timestamp"],
        "issue_id": row["issue_id"],
        "previous_status": row["previous_status"],
        "new_status": row["new_status"],
        "actor": _loads(row["actor"]),
        "raw_event": _loads(row["raw_event"]),
        "received_at": row["received_at"],
    }


def _loads(value: str) -> dict[str, Any]:
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else {}


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _required_property(record: GraphRecord, name: str) -> str:
    value = record.properties.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{record.kind} record {record.key!r} is missing properties[{name!r}]")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
