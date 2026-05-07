"""First-run setup checks and workspace scaffolding."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import tempfile


REQUIRED_ENV_VARS = ("LINEAR_API_KEY",)
REQUIRED_IMPORTS = (
    "sqlite3",
    "overture.export_store",
    "overture.linear_client",
    "overture.metrics_store",
)
WORKSPACE_DIRS = (
    ".overture",
    ".overture/intake",
    ".overture/research",
    ".overture/graph",
    ".overture/synthesis",
    ".overture/ticket",
    ".overture/runs",
    ".overture/fixtures",
    ".overture/retros",
    ".overture/milestones",
)


@dataclass(frozen=True)
class SetupCheck:
    name: str
    passed: bool
    observed: str
    detail: str = ""


@dataclass(frozen=True)
class SetupReport:
    workspace: Path
    checks: tuple[SetupCheck, ...]
    created_dirs: tuple[Path, ...]

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.checks)


def run_setup(workspace: Path | str = Path(".")) -> SetupReport:
    workspace_path = Path(workspace).expanduser().resolve(strict=False)
    checks: list[SetupCheck] = []
    checks.extend(_env_checks())
    checks.append(_write_permission_check(workspace_path))
    checks.extend(_import_checks())

    created_dirs: list[Path] = []
    if all(check.passed for check in checks):
        created_dirs = _create_workspace_dirs(workspace_path)

    return SetupReport(
        workspace=workspace_path,
        checks=tuple(checks),
        created_dirs=tuple(created_dirs),
    )


def render_setup_report(report: SetupReport) -> str:
    lines = [f"workspace: {report.workspace}"]
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        suffix = f" - {check.detail}" if check.detail else ""
        lines.append(f"[{status}] {check.name}: observed={check.observed}{suffix}")

    created = len(report.created_dirs)
    existing = len(WORKSPACE_DIRS) - created if report.ok else 0
    if report.ok:
        lines.append(f"scaffold: created={created} existing={existing}")
    else:
        lines.append("scaffold: skipped")
    lines.append("summary: PASS" if report.ok else "summary: FAIL")
    return "\n".join(lines) + "\n"


def _env_checks() -> list[SetupCheck]:
    checks = []
    for name in REQUIRED_ENV_VARS:
        value = os.environ.get(name)
        if value:
            observed = f"set ({len(value)} chars)"
            checks.append(SetupCheck(name=f"env {name}", passed=True, observed=observed))
        else:
            checks.append(
                SetupCheck(
                    name=f"env {name}",
                    passed=False,
                    observed="missing",
                    detail=f"set {name} before exporting to Linear",
                )
            )
    return checks


def _write_permission_check(workspace: Path) -> SetupCheck:
    parent = _nearest_existing_parent(workspace)
    if parent is None:
        return SetupCheck(
            name="workspace write permission",
            passed=False,
            observed=f"parent missing ({workspace})",
            detail="create or choose a workspace under an existing writable directory",
        )

    try:
        with tempfile.NamedTemporaryFile(prefix=".overture-write-check-", dir=parent, delete=True):
            pass
    except OSError as exc:
        return SetupCheck(
            name="workspace write permission",
            passed=False,
            observed=f"not writable ({parent})",
            detail=str(exc),
        )

    return SetupCheck(
        name="workspace write permission",
        passed=True,
        observed=f"writable ({parent})",
    )


def _nearest_existing_parent(path: Path) -> Path | None:
    current = path if path.exists() else path.parent
    while not current.exists():
        if current.parent == current:
            return None
        current = current.parent
    return current


def _import_checks() -> list[SetupCheck]:
    checks = []
    for module_name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
        except ImportError as exc:
            checks.append(
                SetupCheck(
                    name=f"import {module_name}",
                    passed=False,
                    observed="failed",
                    detail=str(exc),
                )
            )
        else:
            checks.append(
                SetupCheck(
                    name=f"import {module_name}",
                    passed=True,
                    observed="available",
                )
            )
    return checks


def _create_workspace_dirs(workspace: Path) -> list[Path]:
    created: list[Path] = []
    for relative in WORKSPACE_DIRS:
        directory = workspace / relative
        existed = directory.exists()
        directory.mkdir(parents=True, exist_ok=True)
        if not existed:
            created.append(directory)
    return created
