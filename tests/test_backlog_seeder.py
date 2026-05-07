import json
import tempfile
import unittest
from pathlib import Path

from overture.backlog_seeder import seed_confirmed_friction_intakes
from overture.friction_log import FrictionLog
from overture.intake import load_intake_record


class BacklogSeederTests(unittest.TestCase):
    def test_zero_confirmed_entries_seeds_no_intakes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            log = FrictionLog(base_dir / "metrics.sqlite")
            log.append(session_id="m1", run_id="run-1", category="slow", note="not approved yet")

            seeded = seed_confirmed_friction_intakes(
                friction_log=log,
                intake_store_dir=base_dir / "intake",
            )

        self.assertEqual(seeded, [])

    def test_several_confirmed_entries_seed_one_intake_each(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            log = FrictionLog(base_dir / "metrics.sqlite")
            log.append(
                session_id="m1",
                run_id="run-1",
                category="slow",
                note="research approval took too long",
                confirmed=True,
            )
            log.append(
                session_id="m1",
                run_id="run-1",
                category="confusing",
                note="handoff instructions were unclear",
                confirmed=True,
            )

            seeded = seed_confirmed_friction_intakes(
                friction_log=log,
                intake_store_dir=base_dir / "intake",
            )

            payloads = [json.loads(item.path.read_text(encoding="utf-8")) for item in seeded]
            loaded_id = load_intake_record(seeded[0].path).id

        self.assertEqual(len(seeded), 2)
        self.assertEqual([payload["source_type"] for payload in payloads], ["friction", "friction"])
        self.assertIn("research approval took too long", payloads[0]["raw_text"])
        self.assertIn("handoff instructions were unclear", payloads[1]["raw_text"])
        self.assertEqual(loaded_id, payloads[0]["id"])

    def test_mixed_entries_skip_unconfirmed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            log = FrictionLog(base_dir / "metrics.sqlite")
            log.append(
                session_id="m1",
                run_id="run-1",
                category="slow",
                note="confirmed source",
                confirmed=True,
            )
            log.append(
                session_id="m1",
                run_id="run-1",
                category="broken",
                note="operator has not confirmed this",
            )

            seeded = seed_confirmed_friction_intakes(
                friction_log=log,
                intake_store_dir=base_dir / "intake",
            )

        self.assertEqual(len(seeded), 1)
        self.assertIn("confirmed source", seeded[0].intake.raw_text)
        self.assertNotIn("operator has not confirmed this", seeded[0].intake.raw_text)


if __name__ == "__main__":
    unittest.main()
