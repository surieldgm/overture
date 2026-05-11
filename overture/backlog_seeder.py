"""Seed intake records from operator-confirmed friction entries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .friction_log import FrictionEntry, FrictionLog
from .retro_generator import PersonaFinding, _parse_persona_report
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


@dataclass(frozen=True)
class SeededResidualIntake:
    finding: PersonaFinding
    intake: IntakeRecord
    path: Path


MWIZ_SEVERITY_HINT_BY_LEVEL = {
    "critical": "Sprint hint: prioritize for immediate next milestone.",
    "high": "Sprint hint: prioritize for next milestone.",
}


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


def seed_mwiz_residual_intakes(
    *,
    persona_report_path: Path | str,
    intake_store_dir: Path | str = Path(".overture") / "intake",
) -> list[SeededResidualIntake]:
    parsed = _parse_persona_report(persona_report_path)
    closed = {finding.number for finding in parsed.closed_baseline_findings}
    persona_by_number: dict[str, str] = {
        finding.number: finding.persona
        for finding in parsed.residual_findings
        if finding.persona
    }

    deduped: dict[str, PersonaFinding] = {}
    for finding in parsed.residual_findings:
        if finding.number in closed or finding.number in deduped:
            continue
        persona = finding.persona or persona_by_number.get(finding.number)
        deduped[finding.number] = (
            replace(finding, persona=persona) if persona != finding.persona else finding
        )

    seeded: list[SeededResidualIntake] = []
    for finding in deduped.values():
        intake, path = _create_or_load_intake(
            _mwiz_residual_intake_text(finding),
            intake_store_dir,
            source_type="mwiz-residual",
        )
        seeded.append(SeededResidualIntake(finding=finding, intake=intake, path=path))
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


def _mwiz_residual_intake_text(finding: PersonaFinding) -> str:
    normalized_severity = (finding.severity or "Unknown").strip()
    hint = MWIZ_SEVERITY_HINT_BY_LEVEL.get(normalized_severity.lower())
    persona = finding.persona or "Unknown persona"
    text = (
        f"M-WIZ residual finding [{finding.number}] from {persona}.\n"
        f"Severity: {normalized_severity}.\n"
        f"Problem statement: {finding.description}.\n"
    )
    if hint:
        text += hint
    return text


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
