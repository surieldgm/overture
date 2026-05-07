"""Read-only milestone done-condition verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import glob
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable


DEFAULT_CRITERION_PATHS = {
    "dogfooding_days": {"metrics_db": ".overture/metrics.sqlite"},
    "exported_tickets": {"ledger_db": ".overture/exports.sqlite"},
    "metric_runs": {"metrics_db": ".overture/metrics.sqlite"},
    "friction_entries": {"metrics_db": ".overture/metrics.sqlite"},
    "generated_retro": {"paths": [".overture/retro/*.md"]},
}


@dataclass(frozen=True)
class CriterionResult:
    name: str
    kind: str
    passed: bool
    observed: int
    target: int
    deficit: int
    source: str


@dataclass(frozen=True)
class MilestoneVerification:
    milestone: str
    passed: bool
    criteria: tuple[CriterionResult, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "milestone": self.milestone,
            "passed": self.passed,
            "criteria": [asdict(result) for result in self.criteria],
        }


def verify_milestone_config(config_path: Path | str, *, workspace: Path | str = ".") -> MilestoneVerification:
    config_file = Path(config_path)
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read milestone config {config_file}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid milestone config {config_file}: {exc}") from exc

    milestone = _require_text(config.get("milestone", config_file.stem), "milestone")
    criteria = tuple(
        _verify_criterion(criterion, workspace=Path(workspace))
        for criterion in _normalize_criteria(config)
    )
    if not criteria:
        raise ValueError("milestone config must declare at least one criterion")
    return MilestoneVerification(
        milestone=milestone,
        passed=all(result.passed for result in criteria),
        criteria=criteria,
    )


def render_human_report(verification: MilestoneVerification) -> str:
    status = "PASS" if verification.passed else "FAIL"
    lines = [f"Milestone {verification.milestone}: {status}"]
    for result in verification.criteria:
        criterion_status = "PASS" if result.passed else "FAIL"
        deficit = "" if result.passed else f" deficit={result.deficit}"
        lines.append(
            f"{criterion_status} {result.name}: observed={result.observed} "
            f"target={result.target}{deficit} source={result.source}"
        )
    return "\n".join(lines)


def _normalize_criteria(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_criteria = config.get("criteria")
    if isinstance(raw_criteria, list):
        return [_require_mapping(criterion, "criterion") for criterion in raw_criteria]
    if isinstance(raw_criteria, dict):
        criteria: list[dict[str, Any]] = []
        for name, raw_criterion in raw_criteria.items():
            criterion = dict(_require_mapping(raw_criterion, f"criteria.{name}"))
            criterion.setdefault("name", name)
            criteria.append(criterion)
        return criteria
    raise ValueError("milestone config must include criteria as an object or list")


def _verify_criterion(raw_criterion: dict[str, Any], *, workspace: Path) -> CriterionResult:
    name = _require_text(raw_criterion.get("name"), "criterion.name")
    kind = _require_text(raw_criterion.get("kind", name), f"{name}.kind")
    target = _require_non_negative_int(raw_criterion.get("target"), f"{name}.target")
    defaults = DEFAULT_CRITERION_PATHS.get(kind, {})
    criterion = {**defaults, **raw_criterion}

    if kind == "dogfooding_days":
        source = _resolve(workspace, _require_text(criterion.get("metrics_db"), f"{name}.metrics_db"))
        observed = _count_sqlite(source, "SELECT count(DISTINCT session_id) FROM friction_entries")
    elif kind == "exported_tickets":
        source = _resolve(workspace, _require_text(criterion.get("ledger_db"), f"{name}.ledger_db"))
        observed = _count_sqlite(source, "SELECT count(*) FROM exports")
    elif kind == "metric_runs":
        source = _resolve(workspace, _require_text(criterion.get("metrics_db"), f"{name}.metrics_db"))
        observed = _count_sqlite(source, "SELECT count(DISTINCT run_id) FROM stage_metrics")
    elif kind == "friction_entries":
        source = _resolve(workspace, _require_text(criterion.get("metrics_db"), f"{name}.metrics_db"))
        observed = _count_sqlite(source, "SELECT count(*) FROM friction_entries")
    elif kind == "generated_retro":
        paths = _require_string_list(criterion.get("paths"), f"{name}.paths")
        source = ",".join(paths)
        observed = _count_existing_nonempty_matches(workspace, paths)
    else:
        raise ValueError(f"unsupported criterion kind: {kind}")

    deficit = max(target - observed, 0)
    return CriterionResult(
        name=name,
        kind=kind,
        passed=deficit == 0,
        observed=observed,
        target=target,
        deficit=deficit,
        source=str(source),
    )


def _count_sqlite(db_path: Path, query: str) -> int:
    if not db_path.exists():
        return 0
    try:
        connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return 0
    try:
        row = connection.execute(query).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return 0
        raise
    finally:
        connection.close()
    return int(row[0] if row is not None else 0)


def _count_existing_nonempty_matches(workspace: Path, patterns: Iterable[str]) -> int:
    matches: set[Path] = set()
    for pattern in patterns:
        full_pattern = _resolve(workspace, pattern)
        for match in glob.glob(str(full_pattern), recursive=True):
            path = Path(match)
            if path.is_file() and path.stat().st_size > 0:
                matches.add(path.resolve())
    return len(matches)


def _resolve(workspace: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return workspace / path


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty string list")
    strings = [_require_text(item, field_name) for item in value]
    return strings
