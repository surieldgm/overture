"""Local JSONL observation log for authenticated UI wizard sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Lock
from typing import Iterable, Mapping


OBSERVATION_LOG_FILENAME = "observation-log.jsonl"


@dataclass(frozen=True)
class ObservationEvent:
    event_type: str
    method: str
    path: str
    status: int
    user_id: str
    user_email: str
    from_route: str | None = None
    to_route: str | None = None
    form_fields: tuple[str, ...] = ()
    error: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "event_type": self.event_type,
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "user_id": self.user_id,
            "user_email": self.user_email,
        }
        if self.from_route is not None:
            payload["from_route"] = self.from_route
        if self.to_route is not None:
            payload["to_route"] = self.to_route
        if self.form_fields:
            payload["form_fields"] = list(self.form_fields)
        if self.error is not None:
            payload["error"] = self.error
        payload.update(dict(self.metadata))
        return payload


class ObservationLog:
    """Append-only JSONL store for wizard request observations."""

    def __init__(self, store_dir: Path | str, *, filename: str = OBSERVATION_LOG_FILENAME) -> None:
        self.path = Path(store_dir) / filename
        self._lock = Lock()

    def append(self, events: Iterable[ObservationEvent]) -> None:
        rows = [json.dumps(event.to_jsonable(), sort_keys=True, separators=(",", ":")) for event in events]
        if not rows:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(row + "\n")


def load_observation_events(path: Path | str) -> list[dict[str, object]]:
    source = Path(path)
    if not source.exists():
        return []
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
