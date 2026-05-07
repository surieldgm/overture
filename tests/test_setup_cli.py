import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import overture.cli as cli
from overture.setup import WORKSPACE_DIRS


class SetupCliTests(unittest.TestCase):
    def test_clean_workspace_reports_checks_and_creates_required_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"

            result = _run_cli(
                ["setup", "--workspace", str(workspace)],
                env={"LINEAR_API_KEY": "secret"},
            )

            dirs = [workspace / relative for relative in WORKSPACE_DIRS]
            dirs_exist = [directory.is_dir() for directory in dirs]

        self.assertEqual(result.exit_code, 0)
        self.assertIn("[PASS] env LINEAR_API_KEY: observed=set (6 chars)", result.stdout)
        self.assertIn("[PASS] workspace write permission: observed=writable", result.stdout)
        self.assertIn("[PASS] import overture.metrics_store: observed=available", result.stdout)
        self.assertIn("scaffold: created=", result.stdout)
        self.assertIn("summary: PASS", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(dirs_exist, [True] * len(dirs))

    def test_partially_configured_workspace_creates_only_missing_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            existing = workspace / ".overture" / "intake"
            existing.mkdir(parents=True)

            result = _run_cli(
                ["setup", "--workspace", str(workspace)],
                env={"LINEAR_API_KEY": "secret"},
            )

            expected_created = len(WORKSPACE_DIRS) - 2

        self.assertEqual(result.exit_code, 0)
        self.assertIn(f"scaffold: created={expected_created} existing=2", result.stdout)

    def test_already_configured_workspace_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            for relative in WORKSPACE_DIRS:
                (workspace / relative).mkdir(parents=True, exist_ok=True)
            sentinel = workspace / ".overture" / "intake" / "keep.json"
            sentinel.write_text("do not touch", encoding="utf-8")

            result = _run_cli(
                ["setup", "--workspace", str(workspace)],
                env={"LINEAR_API_KEY": "secret"},
            )

            sentinel_text = sentinel.read_text(encoding="utf-8")

        self.assertEqual(result.exit_code, 0)
        self.assertIn(f"scaffold: created=0 existing={len(WORKSPACE_DIRS)}", result.stdout)
        self.assertEqual(sentinel_text, "do not touch")

    def test_missing_critical_env_var_exits_nonzero_and_names_deficit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            result = _run_cli(["setup", "--workspace", str(workspace)], env={})

        self.assertEqual(result.exit_code, 1)
        self.assertIn("[FAIL] env LINEAR_API_KEY: observed=missing", result.stdout)
        self.assertIn("set LINEAR_API_KEY before exporting to Linear", result.stdout)
        self.assertIn("scaffold: skipped", result.stdout)
        self.assertIn("summary: FAIL", result.stdout)
        self.assertFalse((workspace / ".overture").exists())

    def test_failed_setup_does_not_create_missing_workspace_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "missing-parent" / "workspace"

            result = _run_cli(["setup", "--workspace", str(workspace)], env={})
            parent_exists = workspace.parent.exists()

        self.assertEqual(result.exit_code, 1)
        self.assertIn("[FAIL] env LINEAR_API_KEY: observed=missing", result.stdout)
        self.assertFalse(parent_exists)


def _run_cli(argv: list[str], *, env: dict[str, str]) -> "_CliResult":
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.dict(os.environ, env, clear=True),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        exit_code = cli.main(argv)
    return _CliResult(exit_code=exit_code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


class _CliResult:
    def __init__(self, *, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


if __name__ == "__main__":
    unittest.main()
