"""Seed intake records from operator-confirmed friction entries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .friction_log import FrictionEntry, FrictionLog
from .intake import IntakeRecord, create_intake_record, load_intake_record, stable_intake_id


M4_SPRINT_HINT_BY_CATEGORY = {
    "designer-experience": "M4-S1 designer experience",
    "onboarding": "M4-S1 onboarding",
    "performance": "M4-S2 performance",
    "error-handling": "M4-S2 error handling",
    "uncategorized": "M4-retro manual triage",
}


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
        intake, path = _create_or_load_intake(
            _intake_text(entry),
            intake_store_dir,
            source_type="friction",
        )
        seeded.append(SeededIntake(friction_entry=entry, intake=intake, path=path))
    return seeded


def seed_m4_designer_experience_intakes(
    *,
    friction_log: FrictionLog,
    intake_store_dir: Path | str = Path(".overture") / "intake",
    session_id: str | None = None,
    run_id: str | None = None,
) -> list[SeededIntake]:
    """Create M4 intake records from confirmed M3 designer-rollout frictions."""

    seeded: list[SeededIntake] = []
    for entry in friction_log.iter_entries(session_id=session_id, run_id=run_id, confirmed=True):
        if entry.category not in M4_SPRINT_HINT_BY_CATEGORY:
            continue
        intake, path = _create_or_load_intake(
            _m4_intake_text(entry),
            intake_store_dir,
            source_type="m4-friction",
        )
        seeded.append(SeededIntake(friction_entry=entry, intake=intake, path=path))
    return seeded


def _intake_text(entry: FrictionEntry) -> str:
    return (
        f"Confirmed operator friction [{entry.category}] "
        f"in session {entry.session_id} run {entry.run_id}: {entry.note}"
    )


def _m4_intake_text(entry: FrictionEntry) -> str:
    sprint_hint = M4_SPRINT_HINT_BY_CATEGORY[entry.category]
    return (
        f"M4 backlog intake from confirmed M3 designer friction [{entry.category}].\n"
        f"Sprint hint: {sprint_hint}.\n"
        f"Source session: {entry.session_id}; run: {entry.run_id}; friction id: {entry.id}.\n"
        f"Designer-confirmed note: {entry.note}"
    )


def _create_or_load_intake(
    raw_text: str,
    store_dir: Path | str,
    *,
    source_type: str,
) -> tuple[IntakeRecord, Path]:
    path = Path(store_dir) / f"{stable_intake_id(raw_text)}.json"
    if path.exists():
        return load_intake_record(path), path
    return create_intake_record(raw_text, store_dir, source_type=source_type)
