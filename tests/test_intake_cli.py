import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from overture.intake import load_intake_record


class IntakeCliTests(unittest.TestCase):
    def test_intake_command_creates_loadable_record(self) -> None:
        idea = "Build a GraphRAG system that turns research into Symphony tickets"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "overture",
                    "intake",
                    idea,
                    "--store-dir",
                    tmpdir,
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            record_path = Path(result.stdout.splitlines()[0])
            self.assertTrue(record_path.exists())

            payload = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["raw_text"], idea)
            self.assertEqual(payload["source_type"], "cli")
            self.assertEqual(payload["normalized_summary"], idea)
            self.assertRegex(payload["id"], r"^idea_[0-9a-f]{32}$")
            self.assertRegex(payload["created_at"], r"^\d{4}-\d{2}-\d{2}T")

            loaded = load_intake_record(record_path)
            self.assertEqual(loaded.raw_text, idea)
            self.assertEqual(loaded.id, payload["id"])

    def test_intake_command_rejects_empty_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "overture",
                    "intake",
                    "   ",
                    "--store-dir",
                    tmpdir,
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("idea text cannot be empty", result.stderr)
            self.assertEqual(list(Path(tmpdir).glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
