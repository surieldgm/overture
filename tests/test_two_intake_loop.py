import re
import tempfile
import unittest
from pathlib import Path

from overture.fixture import run_overture_fixture


class TwoIntakeLoopTests(unittest.TestCase):
    def test_second_intake_graph_provenance_cites_prior_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            run_overture_fixture(
                temp / "run1",
                idea="Add idea persistence to Overture",
                graph_store_base_path=temp,
            )
            run_overture_fixture(
                temp / "run2",
                idea="Query persisted ideas in synthesis briefs",
                graph_store_base_path=temp,
            )

            draft = (temp / "run2" / "ticket" / "symphony-ticket-draft.md").read_text(encoding="utf-8")
            provenance = _graph_provenance_section(draft)

            self.assertIn(
                "prior:",
                provenance,
                "no prior nodes in graph provenance\n\n## Graph provenance\n" + provenance,
            )


def _graph_provenance_section(markdown: str) -> str:
    match = re.search(r"^## Graph provenance\n(?P<body>.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL)
    return match.group("body").strip() if match else "<missing graph provenance section>"


if __name__ == "__main__":
    unittest.main()
