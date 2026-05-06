"""Run two fixture passes and print metrics summaries for inspection."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overture import cli
from overture.fixture import run_overture_fixture


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        temp = Path(tmpdir)
        metrics_db_path = temp / "metrics.sqlite"

        run_overture_fixture(temp / "run1", metrics_db_path=metrics_db_path)
        run_overture_fixture(temp / "run2", metrics_db_path=metrics_db_path)

        print("Metrics table")
        table_exit_code = cli.main(["metrics", "--db-path", str(metrics_db_path)])
        if table_exit_code != 0:
            return table_exit_code

        print()
        print("Metrics JSON")
        return cli.main(["metrics", "--db-path", str(metrics_db_path), "--format=json"])


if __name__ == "__main__":
    raise SystemExit(main())
