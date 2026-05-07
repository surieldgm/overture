"""Seed intake records from operator-confirmed friction entries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .friction_log import FrictionEntry, FrictionLog
from .intake import IntakeRecord, create_intake_record


@dataclass(frozen=True)
class SeededIntake:
    friction_entry: FrictionEntry
    intake: IntakeRecord
    path: Path


def seed_confirmed_friction_intakes(
    *,
    friction_log: FrictionLog,
    intake_store_dir: Path | str = Path(".overture") / "intake",
    session_id: str | None = None,
    run_id: str | None = None,
) -> list[SeededIntake]:
    seeded: list[SeededIntake] = []
    for entry in friction_log.iter_entries(session_id=session_id, run_id=run_id, confirmed=True):
        intake, path = create_intake_record(
            _intake_text(entry),
            intake_store_dir,
            source_type="friction",
        )
        seeded.append(SeededIntake(friction_entry=entry, intake=intake, path=path))
    return seeded


def _intake_text(entry: FrictionEntry) -> str:
    return (
        f"Confirmed operator friction [{entry.category}] "
        f"in session {entry.session_id} run {entry.run_id}: {entry.note}"
    )
