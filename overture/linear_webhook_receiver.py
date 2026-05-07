"""HTTP receiver for simulated Linear webhook events."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .metrics_store import MetricsStore
from .rework_classifier import classify_linear_webhook
from .rework_counter import ReworkCounter


class LinearWebhookBackend:
    def __init__(self, metrics_store: MetricsStore) -> None:
        self.counter = ReworkCounter(metrics_store)

    def receive(self, payload: Mapping[str, Any]) -> bool:
        signal = classify_linear_webhook(payload)
        if signal is None:
            return False
        self.counter.record(signal)
        return True


def create_linear_webhook_receiver(
    metrics_db_path: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8767,
) -> ThreadingHTTPServer:
    backend = LinearWebhookBackend(MetricsStore(metrics_db_path))

    class Handler(LinearWebhookRequestHandler):
        webhook_backend = backend

    return ThreadingHTTPServer((host, port), Handler)


class LinearWebhookRequestHandler(BaseHTTPRequestHandler):
    webhook_backend: LinearWebhookBackend
    server_version = "OvertureLinearWebhook/1.0"

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in {"/linear/webhook", "/webhooks/linear"}:
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            counted = self.webhook_backend.receive(self._read_json())
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"accepted": True, "rework_counted": counted}, status=202)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> Mapping[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 1:
            raise ValueError("request body is required")
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
