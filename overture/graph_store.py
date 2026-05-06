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
from typing import Any

from .graph import GraphRecord
from .synthesis import GraphContext

DEFAULT_GRAPH_DB_PATH = Path(".overture") / "graph.sqlite"
NODE_KINDS = {"Source", "ResearchItem", "Claim"}
EDGE_KINDS = {"CITES", "HAS_CLAIM"}


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
