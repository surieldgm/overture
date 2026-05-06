"""Validate the local Linear export path without network access.

Manual real-Linear smoke:
LINEAR_API_KEY=<k> python -m overture export <path> --team-id <real>
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overture import cli
from overture.fixture import run_overture_fixture


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        temp = Path(tmpdir)
        run_overture_fixture(temp / "run", idea="Sprint 2 export smoke test")
        ticket_path = temp / "run" / "ticket" / "symphony-ticket-draft.md"

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = cli.main(["export", str(ticket_path), "--team-id", "dry-run-team", "--dry-run"])
        if exit_code != 0:
            return exit_code

        lines = stdout.getvalue().splitlines()
        title = next(
            line.removeprefix("would create: title=").strip()
            for line in lines
            if line.startswith("would create: title=")
        )
        body = " ".join(lines[1:]).strip()
        print(f"Parsed title: {title}")
        print(f"Body summary: {body[:200]}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
