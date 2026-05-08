import json
import tempfile
import unittest
from pathlib import Path

from overture.backlog_seeder import (
    M4_SPRINT_HINT_BY_CATEGORY,
    seed_confirmed_friction_intakes,
    seed_m4_designer_experience_intakes,
)
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

    def test_m4_seeder_maps_designer_categories_to_sprint_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            log = FrictionLog(base_dir / "metrics.sqlite")
            for index, category in enumerate(
                ("designer-experience", "onboarding", "performance", "error-handling"),
                start=1,
            ):
                log.append(
                    session_id="m3",
                    run_id="three-designer-rollout",
                    category=category,
                    note=f"confirmed designer friction {index}",
                    confirmed=True,
                    created_at=f"2026-05-07T10:0{index}:00.000000Z",
                )

            seeded = seed_m4_designer_experience_intakes(
                friction_log=log,
                intake_store_dir=base_dir / "intake",
                session_id="m3",
            )

            payloads = [json.loads(item.path.read_text(encoding="utf-8")) for item in seeded]

        self.assertEqual(
            [item.friction_entry.category for item in seeded],
            list(M4_SPRINT_HINT_BY_CATEGORY)[:4],
        )
        self.assertEqual([payload["source_type"] for payload in payloads], ["m4-friction"] * 4)
        for payload, category in zip(payloads, M4_SPRINT_HINT_BY_CATEGORY):
            self.assertIn(f"[{category}]", payload["raw_text"])
            self.assertIn(f"Sprint hint: {M4_SPRINT_HINT_BY_CATEGORY[category]}", payload["raw_text"])
            self.assertIn("M4 backlog intake from confirmed M3 designer friction", payload["raw_text"])

    def test_m4_seeder_is_idempotent_and_skips_unconfirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            log = FrictionLog(base_dir / "metrics.sqlite")
            log.append(
                session_id="m3",
                run_id="three-designer-rollout",
                category="designer-experience",
                note="confirmed source",
                confirmed=True,
            )
            log.append(
                session_id="m3",
                run_id="three-designer-rollout",
                category="onboarding",
                note="designer has not confirmed this",
            )

            first_seeded = seed_m4_designer_experience_intakes(
                friction_log=log,
                intake_store_dir=base_dir / "intake",
            )
            first_payload = json.loads(first_seeded[0].path.read_text(encoding="utf-8"))
            second_seeded = seed_m4_designer_experience_intakes(
                friction_log=log,
                intake_store_dir=base_dir / "intake",
            )
            second_payload = json.loads(second_seeded[0].path.read_text(encoding="utf-8"))
            paths = list((base_dir / "intake").glob("*.json"))

        self.assertEqual(len(first_seeded), 1)
        self.assertEqual(len(second_seeded), 1)
        self.assertEqual(len(paths), 1)
        self.assertEqual(first_seeded[0].intake.id, second_seeded[0].intake.id)
        self.assertEqual(first_payload["created_at"], second_payload["created_at"])
        self.assertIn("confirmed source", second_seeded[0].intake.raw_text)
        self.assertNotIn("designer has not confirmed this", second_seeded[0].intake.raw_text)

    def test_m4_seeder_keeps_uncategorized_bucket_for_manual_triage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            log = FrictionLog(base_dir / "metrics.sqlite")
            log.append(
                session_id="m3",
                run_id="three-designer-rollout",
                category="uncategorized",
                note="designer confirmed but category is missing",
                confirmed=True,
            )

            seeded = seed_m4_designer_experience_intakes(
                friction_log=log,
                intake_store_dir=base_dir / "intake",
            )

        self.assertEqual(len(seeded), 1)
        self.assertIn("Sprint hint: M4-retro manual triage", seeded[0].intake.raw_text)


if __name__ == "__main__":
    unittest.main()
