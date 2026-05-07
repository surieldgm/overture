"""Milestone closing-chain helpers for dogfooding retros and backlog seeds."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .friction_log import FrictionEntry, FrictionLog
from .intake import create_intake_record, stable_intake_id
from .metrics_store import MetricsStore, StageMetric


DEFAULT_RETRO_PATH = Path(".overture") / "milestones" / "m1-retro.md"
DEFAULT_BACKLOG_INTAKE_DIR = Path(".overture") / "intake" / "m2"


@dataclass(frozen=True)
class BacklogSeedResult:
    intake_paths: tuple[Path, ...]
    friction_count: int


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    failures: tuple[str, ...]


def generate_retro(
    *,
    metrics_db_path: Path | str,
    output_path: Path | str = DEFAULT_RETRO_PATH,
) -> Path:
    """Render a milestone retro from locally recorded metrics and friction."""

    metrics = list(MetricsStore(metrics_db_path).iter_stages())
    frictions = list(FrictionLog(metrics_db_path).iter_entries())
    sessions = _session_ids(frictions)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(_retro_lines(metrics=metrics, frictions=frictions, sessions=sessions)) + "\n",
        encoding="utf-8",
    )
    return path


def seed_backlog_from_friction(
    *,
    metrics_db_path: Path | str,
    intake_dir: Path | str = DEFAULT_BACKLOG_INTAKE_DIR,
) -> BacklogSeedResult:
    """Create M2 intake records for every confirmed friction entry.

    The current friction log has no separate moderation state, so persisted
    friction entries are treated as the confirmed set for milestone closing.
    """

    target_dir = Path(intake_dir)
    intake_paths: list[Path] = []
    frictions = list(FrictionLog(metrics_db_path).iter_entries())
    for entry in frictions:
        _, path = create_intake_record(
            _friction_intake_text(entry),
            target_dir,
            source_type="milestone-friction",
        )
        intake_paths.append(path)
    return BacklogSeedResult(intake_paths=tuple(intake_paths), friction_count=len(frictions))


def verify_milestone_closing(
    *,
    metrics_db_path: Path | str,
    retro_path: Path | str = DEFAULT_RETRO_PATH,
    intake_dir: Path | str = DEFAULT_BACKLOG_INTAKE_DIR,
    required_sessions: tuple[str, ...] = (),
) -> VerificationResult:
    """Verify that the closing chain produced the artifacts M2 needs."""

    failures: list[str] = []
    retro = Path(retro_path)
    intake_base = Path(intake_dir)
    metrics = list(MetricsStore(metrics_db_path).iter_stages())
    frictions = list(FrictionLog(metrics_db_path).iter_entries())

    if not metrics:
        failures.append("metrics store has no stage metrics")
    failed_metrics = [metric for metric in metrics if metric.status != "success"]
    if failed_metrics:
        failures.append("metrics store contains failed stage metrics")

    if not retro.exists():
        failures.append(f"retro file does not exist: {retro}")
        retro_text = ""
    else:
        retro_text = retro.read_text(encoding="utf-8")

    for session_id in required_sessions:
        if session_id not in retro_text:
            failures.append(f"retro does not reference required session: {session_id}")

    run_ids_with_metrics = {metric.run_id for metric in metrics}
    for entry in frictions:
        if entry.run_id not in run_ids_with_metrics:
            failures.append(f"friction entry {entry.id} references run without metrics: {entry.run_id}")
        intake_path = intake_base / f"{stable_intake_id(_friction_intake_text(entry))}.json"
        if not intake_path.exists():
            failures.append(f"missing intake for friction entry {entry.id}: {intake_path}")
            continue
        payload = json.loads(intake_path.read_text(encoding="utf-8"))
        if payload.get("source_type") != "milestone-friction":
            failures.append(f"intake {intake_path.name} has unexpected source_type")

    return VerificationResult(passed=not failures, failures=tuple(failures))


def _retro_lines(
    *,
    metrics: list[StageMetric],
    frictions: list[FrictionEntry],
    sessions: tuple[str, ...],
) -> list[str]:
    lines = [
        "# M1 Dogfooding Retro",
        "",
        "## Sessions",
    ]
    if sessions:
        for session_id in sessions:
            session_frictions = [entry for entry in frictions if entry.session_id == session_id]
            run_ids = _ordered_unique(entry.run_id for entry in session_frictions)
            lines.append(f"- `{session_id}`: {len(session_frictions)} confirmed frictions across {len(run_ids)} runs")
    else:
        lines.append("- No dogfooding sessions recorded.")

    lines.extend(["", "## Metrics"])
    for run_id in _ordered_unique(metric.run_id for metric in metrics):
        run_metrics = [metric for metric in metrics if metric.run_id == run_id]
        total_ms = sum(metric.duration_ms for metric in run_metrics)
        stage_names = ", ".join(metric.stage_name for metric in run_metrics)
        lines.append(f"- `{run_id}`: {len(run_metrics)} stages, {total_ms}ms total ({stage_names})")
    if not metrics:
        lines.append("- No metrics recorded.")

    lines.extend(["", "## Confirmed Frictions"])
    for entry in frictions:
        lines.append(
            f"- `{entry.session_id}` / `{entry.run_id}` / `{entry.category}`: {entry.note}"
        )
    if not frictions:
        lines.append("- No confirmed frictions recorded.")

    lines.extend(
        [
            "",
            "## M2 Backlog Seed",
            "",
            "Create one intake record for each confirmed friction listed above.",
        ]
    )
    return lines


def _session_ids(frictions: list[FrictionEntry]) -> tuple[str, ...]:
    return tuple(_ordered_unique(entry.session_id for entry in frictions))


def _ordered_unique(values) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _friction_intake_text(entry: FrictionEntry) -> str:
    return (
        f"Confirmed dogfooding friction for M2 backlog: {entry.category} friction "
        f"in {entry.session_id} during run {entry.run_id}. Note: {entry.note}"
    )
