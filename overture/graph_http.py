"""HTTP access layer for the shared Overture graph store."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from threading import Lock
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .graph import GraphRecord
from .graph_store import SqliteGraphStore
from .synthesis import GraphContext


class SharedGraphBackend:
    """Serialize graph writes while serving reads from a SQLite-backed store."""

    def __init__(self, store: SqliteGraphStore) -> None:
        self.store = store
        self._write_lock = Lock()

    def upsert_records(self, records: Iterable[GraphRecord]) -> int:
        with self._write_lock:
            return self.store.upsert_records(records)

    def load_context(self, limit: int = 100) -> GraphContext:
        return self.store.load_context(limit)

    def list_nodes(self, *, kind: str | None = None, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        return self.store.list_nodes(kind=kind, limit=limit)

    def list_edges(self, *, kind: str | None = None, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        return self.store.list_edges(kind=kind, limit=limit)

    def iter_records(self) -> tuple[GraphRecord, ...]:
        return self.store.iter_records()

    def table_counts(self) -> dict[str, int]:
        return self.store.table_counts()


class GraphHttpClient:
    """Small stdlib client for the shared graph HTTP API."""

    def __init__(self, base_url: str, *, timeout: float = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def upsert_record(self, record: GraphRecord) -> None:
        self.upsert_records((record,))

    def upsert_records(self, records: Iterable[GraphRecord]) -> int:
        payload = {"records": [_record_payload(record) for record in records]}
        response = self._request_json("POST", "/records", payload)
        return int(response.get("accepted") or 0)

    def load_context(self, limit: int = 100) -> GraphContext:
        response = self._request_json("GET", f"/context?{urlencode({'limit': limit})}")
        return _context_from_payload(response.get("context", {}))

    def list_nodes(self, *, kind: str | None = None, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        query = _query({"kind": kind, "limit": limit})
        response = self._request_json("GET", f"/nodes{query}")
        return tuple(_mapping_items(response.get("nodes", ())))

    def list_edges(self, *, kind: str | None = None, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        query = _query({"kind": kind, "limit": limit})
        response = self._request_json("GET", f"/edges{query}")
        return tuple(_mapping_items(response.get("edges", ())))

    def list_claims(self, *, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        query = _query({"limit": limit})
        response = self._request_json("GET", f"/claims{query}")
        return tuple(_mapping_items(response.get("claims", ())))

    def list_evidence(self, *, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        query = _query({"limit": limit})
        response = self._request_json("GET", f"/evidence{query}")
        return tuple(_mapping_items(response.get("evidence", ())))

    def table_counts(self) -> dict[str, int]:
        response = self._request_json("GET", "/counts")
        counts = response.get("counts", {})
        return {"nodes": int(counts.get("nodes") or 0), "edges": int(counts.get("edges") or 0)} if isinstance(counts, Mapping) else {"nodes": 0, "edges": 0}

    def _request_json(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"graph HTTP {method} {path} failed: {exc.code} {detail}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError(f"graph HTTP {method} {path} returned non-object JSON")
        return decoded


def create_graph_http_server(
    db_path: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
) -> ThreadingHTTPServer:
    backend = SharedGraphBackend(SqliteGraphStore(db_path))

    class Handler(GraphHTTPRequestHandler):
        graph_backend = backend

    return ThreadingHTTPServer((host, port), Handler)


def migrate_graph_store(source_db_path: Path | str, target_url: str) -> dict[str, int]:
    source = SqliteGraphStore(source_db_path)
    records = source.iter_records()
    accepted = GraphHttpClient(target_url).upsert_records(records)
    counts = GraphHttpClient(target_url).table_counts()
    return {"source_records": len(records), "accepted": accepted, "target_nodes": counts["nodes"], "target_edges": counts["edges"]}


class GraphHTTPRequestHandler(BaseHTTPRequestHandler):
    graph_backend: SharedGraphBackend
    server_version = "OvertureGraphHTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self._send_json({"ok": True})
                return
            if parsed.path == "/context":
                self._send_json({"context": _context_payload(self.graph_backend.load_context(_limit(params)))})
                return
            if parsed.path == "/counts":
                self._send_json({"counts": self.graph_backend.table_counts()})
                return
            if parsed.path == "/records":
                self._send_json({"records": [_record_payload(record) for record in self.graph_backend.iter_records()]})
                return
            if parsed.path == "/nodes":
                self._send_json({"nodes": self.graph_backend.list_nodes(kind=_first(params, "kind"), limit=_optional_limit(params))})
                return
            if parsed.path == "/edges":
                self._send_json({"edges": self.graph_backend.list_edges(kind=_first(params, "kind"), limit=_optional_limit(params))})
                return
            if parsed.path == "/claims":
                self._send_json({"claims": self.graph_backend.list_nodes(kind="Claim", limit=_optional_limit(params))})
                return
            if parsed.path == "/evidence":
                self._send_json({"evidence": self.graph_backend.list_nodes(kind="Evidence", limit=_optional_limit(params))})
                return
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self._send_error(500, str(exc))
            return
        self._send_error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            records = _records_for_post(parsed.path, payload)
            accepted = self.graph_backend.upsert_records(records)
            self._send_json({"accepted": accepted}, status=201)
        except ValueError as exc:
            self._send_error(400, str(exc))
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self._send_error(500, str(exc))

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> Mapping[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 1:
            return {}
        decoded = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(decoded, Mapping):
            raise ValueError("request body must be a JSON object")
        return decoded

    def _send_json(self, payload: Mapping[str, Any], *, status: int = 200) -> None:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)


def _records_for_post(path: str, payload: Mapping[str, Any]) -> tuple[GraphRecord, ...]:
    if path == "/records":
        records = payload.get("records")
        if isinstance(records, list):
            return tuple(_record_from_payload(item) for item in records)
        return (_record_from_payload(payload),)
    if path == "/nodes":
        return (_node_record(payload, default_kind=str(payload.get("kind") or "Idea")),)
    if path == "/claims":
        return (_node_record(payload, default_kind="Claim"),)
    if path == "/evidence":
        return (_node_record(payload, default_kind="Evidence"),)
    if path == "/edges":
        return (_edge_record(payload),)
    raise ValueError(f"unsupported write path: {path}")


def _node_record(payload: Mapping[str, Any], *, default_kind: str) -> GraphRecord:
    node_id = str(payload.get("id") or payload.get("key") or "")
    if not node_id:
        raise ValueError("node payload requires id")
    properties = dict(payload.get("properties") or {})
    for key, value in payload.items():
        if key not in {"id", "key", "kind", "type", "properties"}:
            properties[str(key)] = value
    return GraphRecord(kind=default_kind, key=node_id, properties=properties)  # type: ignore[arg-type]


def _edge_record(payload: Mapping[str, Any]) -> GraphRecord:
    from_id = str(payload.get("from") or "")
    to_id = str(payload.get("to") or "")
    kind = str(payload.get("kind") or payload.get("type") or "")
    if not from_id or not to_id or not kind:
        raise ValueError("edge payload requires from, to, and kind")
    properties = dict(payload.get("properties") or {})
    properties["from"] = from_id
    properties["to"] = to_id
    key = str(payload.get("id") or payload.get("key") or f"{from_id}:{kind}:{to_id}")
    return GraphRecord(kind=kind, key=key, properties=properties)  # type: ignore[arg-type]


def _record_from_payload(payload: Any) -> GraphRecord:
    if not isinstance(payload, Mapping):
        raise ValueError("record payload must be an object")
    kind = str(payload.get("kind") or "")
    key = str(payload.get("key") or payload.get("id") or "")
    properties = payload.get("properties")
    if not kind or not key or not isinstance(properties, Mapping):
        raise ValueError("record payload requires kind, key, and properties")
    return GraphRecord(kind=kind, key=key, properties=dict(properties))  # type: ignore[arg-type]


def _record_payload(record: GraphRecord) -> dict[str, Any]:
    return {"kind": record.kind, "key": record.key, "properties": record.properties}


def _context_payload(context: GraphContext) -> dict[str, Any]:
    return asdict(context)


def _context_from_payload(payload: object) -> GraphContext:
    if not isinstance(payload, Mapping):
        return GraphContext()
    return GraphContext(
        nodes=tuple(_mapping_items(payload.get("nodes", ()))),
        edges=tuple(_mapping_items(payload.get("edges", ()))),
        claims=tuple(_mapping_items(payload.get("claims", ()))),
        evidence=tuple(_mapping_items(payload.get("evidence", ()))),
    )


def _mapping_items(value: object) -> Iterable[dict[str, Any]]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _query(params: Mapping[str, Any]) -> str:
    cleaned = {key: value for key, value in params.items() if value is not None}
    return f"?{urlencode(cleaned)}" if cleaned else ""


def _limit(params: Mapping[str, list[str]]) -> int:
    raw = _first(params, "limit")
    return int(raw) if raw else 100


def _optional_limit(params: Mapping[str, list[str]]) -> int | None:
    raw = _first(params, "limit")
    return int(raw) if raw else None


def _first(params: Mapping[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None
