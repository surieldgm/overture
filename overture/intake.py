"""Durable intake records for isolated Overture ideas."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

SUMMARY_MAX_CHARS = 160


@dataclass(frozen=True)
class IntakeRecord:
    id: str
    raw_text: str
    created_at: str
    source_type: str
    normalized_summary: str
    author_id: str | None = None
    author_email: str | None = None


def create_intake_record(
    raw_text: str,
    store_dir: Path | str = Path(".overture") / "intake",
    *,
    source_type: str = "cli",
    author_id: str | None = None,
    author_email: str | None = None,
) -> tuple[IntakeRecord, Path]:
    normalized_summary = normalize_summary(raw_text)
    if not normalized_summary:
        raise ValueError("idea text cannot be empty")

    created_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    record = IntakeRecord(
        id=stable_intake_id(raw_text),
        raw_text=raw_text,
        created_at=created_at,
        source_type=source_type,
        normalized_summary=normalized_summary,
        author_id=author_id,
        author_email=author_email,
    )

    target_dir = Path(store_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{record.id}.json"
    path.write_text(json.dumps(asdict(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record, path


def load_intake_record(path: Path | str) -> IntakeRecord:
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return IntakeRecord(
        id=payload["id"],
        raw_text=payload["raw_text"],
        created_at=payload["created_at"],
        source_type=payload["source_type"],
        normalized_summary=payload["normalized_summary"],
        author_id=payload.get("author_id"),
        author_email=payload.get("author_email"),
    )


def normalize_summary(raw_text: str) -> str:
    compact = re.sub(r"\s+", " ", raw_text).strip()
    if len(compact) <= SUMMARY_MAX_CHARS:
        return compact
    return compact[: SUMMARY_MAX_CHARS - 1].rstrip() + "..."


def stable_intake_id(raw_text: str) -> str:
    return f"idea_{uuid5(NAMESPACE_URL, raw_text).hex}"
