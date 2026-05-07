import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WALKTHROUGH = REPO_ROOT / "docs" / "onboarding-walkthrough.md"
COMMAND_FENCE = re.compile(r"^```(?:sh|shell|bash)\s*$")


class OnboardingSmokeTests(unittest.TestCase):
    def test_onboarding_walkthrough_commands_run_from_clean_workspace(self) -> None:
        """Run the designer onboarding path without external services.

        The smoke creates a temporary copy of the repository to simulate a clean
        checkout, runs the first-run setup command, then executes every shell
        block labeled `Command:` in the walkthrough. The only stubbed surfaces
        are the documented ones: a placeholder `LINEAR_API_KEY` for setup and
        export dry-run validation, `OVERTURE_LLM_CLIENT=fake` for deterministic
        source suggestions, and scripted `y` responses for the CLI approval
        prompts. No real LLM or Linear endpoint is contacted.
        """

        commands = _walkthrough_commands(WALKTHROUGH)
        self.assertEqual(len(commands), 9)

        with tempfile.TemporaryDirectory(prefix="overture-onboarding-smoke-") as tmpdir:
            sandbox = Path(tmpdir)
            repo = sandbox / "repo"
            workspace = sandbox / "workspace"
            _copy_clean_repo(REPO_ROOT, repo)

            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            context: dict[str, str] = {}

            for index, raw_command in enumerate(commands, start=1):
                command = _render_command(raw_command, workspace=workspace, context=context)
                stdin = "y\ny\n" if " overture research " in f" {command} " else None
                stdout = _run_command(command, cwd=repo, env=env, stdin=stdin, index=index)

                if "python -m pip install -e ." in command:
                    venv_bin = repo / ".venv" / "bin"
                    env["VIRTUAL_ENV"] = str(repo / ".venv")
                    env["PATH"] = f"{venv_bin}{os.pathsep}{env['PATH']}"
                if " overture intake " in f" {command} ":
                    context["intake_id"] = stdout.strip().splitlines()[1]

            _assert_promised_artifacts(repo=repo, workspace=workspace, intake_id=context["intake_id"])


def _walkthrough_commands(doc_path: Path) -> list[str]:
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    commands: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != "Command:":
            continue

        fence_index = _next_command_fence(lines, index + 1)
        if fence_index is None:
            raise AssertionError(f"`Command:` at line {index + 1} is missing a shell fence")

        block: list[str] = []
        for command_line in lines[fence_index + 1 :]:
            if command_line.strip() == "```":
                break
            block.append(command_line)
        else:
            raise AssertionError(f"Shell command fence at line {fence_index + 1} is not closed")

        command = "\n".join(block).strip()
        if not command:
            raise AssertionError(f"Shell command fence at line {fence_index + 1} is empty")
        commands.append(command)

    return commands


def _next_command_fence(lines: list[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        if not lines[index].strip():
            continue
        if COMMAND_FENCE.match(lines[index].strip()):
            return index
        return None
    return None


def _copy_clean_repo(source: Path, destination: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}
        ignored.update(name for name in names if name.endswith((".pyc", ".pyo")))
        if Path(directory) == source:
            ignored.add(".overture")
        return ignored.intersection(names)

    shutil.copytree(source, destination, ignore=ignore)


def _render_command(command: str, *, workspace: Path, context: dict[str, str]) -> str:
    rendered = command.replace("/tmp/overture-onboarding", str(workspace))
    rendered = rendered.replace("<linear-team-id>", "team-id")
    if "<intake-id>" in rendered:
        try:
            rendered = rendered.replace("<intake-id>", context["intake_id"])
        except KeyError as exc:
            raise AssertionError("walkthrough research command appeared before intake produced an ID") from exc
    return rendered


def _run_command(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str],
    stdin: str | None,
    index: int,
) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=stdin,
        text=True,
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"walkthrough command {index} failed with exit {completed.returncode}: {command}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed.stdout


def _assert_promised_artifacts(*, repo: Path, workspace: Path, intake_id: str) -> None:
    promised_paths = [
        repo / "examples" / "overture_mvp_linear_issue_draft.md",
        repo / "examples" / "validate_curated_research.py",
        repo / "examples" / "validate_two_intake_loop.py",
        workspace / ".overture",
        workspace / ".overture" / "intake",
        workspace / ".overture" / "research",
        workspace / ".overture" / "graph",
        workspace / ".overture" / "synthesis",
        workspace / ".overture" / "ticket",
        workspace / "intake" / f"{intake_id}.json",
        workspace / "research" / f"{intake_id}.json",
        workspace / "run" / "synthesis" / "synthesis-brief.json",
        workspace / "final" / "ticket" / "symphony-ticket-draft.md",
    ]
    missing = [str(path) for path in promised_paths if not path.exists()]
    if missing:
        raise AssertionError(f"walkthrough promised artifacts were not created: {missing}")

    ticket_text = (workspace / "final" / "ticket" / "symphony-ticket-draft.md").read_text(encoding="utf-8")
    for section in (
        "## Context",
        "## Problem",
        "## Proposed change",
        "## Acceptance criteria",
        "## Validation plan",
        "## Sources / evidence",
        "## Graph provenance",
    ):
        if section not in ticket_text:
            raise AssertionError(f"ticket draft is missing documented section: {section}")


if __name__ == "__main__":
    unittest.main()
