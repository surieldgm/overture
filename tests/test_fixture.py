import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from overture.fixture import PipelineStageError, run_overture_fixture, validate_ticket_draft


class FixtureTests(unittest.TestCase):
    def test_fixture_command_persists_all_pipeline_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "overture",
                    "fixture",
                    "--output-dir",
                    tmpdir,
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            output = result.stdout
            self.assertIn("intake:", output)
            self.assertIn("research:", output)
            self.assertIn("graph:", output)
            self.assertIn("synthesis:", output)
            self.assertIn("ticket_draft:", output)

            base_dir = Path(tmpdir)
            intake_paths = list((base_dir / "intake").glob("*.json"))
            self.assertEqual(len(intake_paths), 1)
            self.assertEqual(json.loads(intake_paths[0].read_text(encoding="utf-8"))["source_type"], "fixture")

            research_path = base_dir / "research" / "research-notes.json"
            graph_path = base_dir / "graph" / "graph-records.json"
            synthesis_path = base_dir / "synthesis" / "synthesis-brief.json"
            ticket_path = base_dir / "ticket" / "symphony-ticket-draft.md"
            for path in (research_path, graph_path, synthesis_path, ticket_path):
                self.assertTrue(path.exists(), path)

            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            self.assertEqual(graph["schema_version"], "kg-minimal-v1")
            self.assertGreater(len(graph["ingestion_records"]), 0)
            self.assertGreater(len(graph["context"]["nodes"]), 0)
            self.assertGreater(len(graph["context"]["edges"]), 0)

            synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
            self.assertEqual(synthesis["candidate_ticket_breakdown"][0]["readiness"], "ready")

            ticket = ticket_path.read_text(encoding="utf-8")
            validate_ticket_draft(ticket)
            self.assertIn("# Add Overture end-to-end fixture", ticket)
            self.assertIn("## Graph provenance", ticket)
            self.assertIn("- Nodes:", ticket)
            self.assertIn("- Edges:", ticket)
            self.assertIn("- Confidence:", ticket)
            self.assertIn("- Conflicts:", ticket)

            export_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "overture",
                    "export",
                    str(ticket_path),
                    "--team-id",
                    "team-id",
                    "--dry-run",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("would create: title=Add Overture end-to-end fixture", export_result.stdout)

    def test_fixture_starts_from_raw_idea_override(self) -> None:
        idea = "Use Overture to test raw idea intake through ticket generation."
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = run_overture_fixture(tmpdir, idea=idea)

            intake = json.loads(artifacts["intake"].read_text(encoding="utf-8"))
            self.assertEqual(intake["raw_text"], idea)
            self.assertTrue(artifacts["ticket_draft"].exists())

    def test_fixture_reads_prior_store_context_for_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                first = Path(tmpdir) / "first"
                second = Path(tmpdir) / "second"
                run_overture_fixture(first, idea="first idea about graph storage")
                artifacts = run_overture_fixture(second, idea="second idea about querying the graph")
            finally:
                os.chdir(previous_cwd)

            synthesis = json.loads(artifacts["synthesis"].read_text(encoding="utf-8"))
            prior_concepts = [concept for concept in synthesis["connected_concepts"] if concept.get("from_prior")]
            self.assertGreater(len(prior_concepts), 0)

            ticket = artifacts["ticket_draft"].read_text(encoding="utf-8")
            self.assertIn("`prior:", ticket)

    def test_fixture_failure_identifies_stage(self) -> None:
        def broken_intake(_idea: str, _store_dir: Path):
            raise ValueError("cannot persist intake")

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(PipelineStageError) as error:
                run_overture_fixture(tmpdir, intake_factory=broken_intake)

        self.assertEqual(error.exception.stage, "intake")
        self.assertIn("cannot persist intake", error.exception.message)


if __name__ == "__main__":
    unittest.main()
