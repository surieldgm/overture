import json
import tempfile
import unittest
from pathlib import Path

from overture.backlog_seeder import (
    M4_SPRINT_HINT_BY_CATEGORY,
    seed_mwiz_residual_intakes,
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

    def test_mwiz_residual_emits_one_intake_per_open_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report = base_dir / "personas-post-mwiz.md"
            report.write_text(
                _mwiz_report(
                    headline="- Residual coverage sample",
                    baseline_rows=_mwiz_baseline_rows(
                        [
                            ("#1", "High", "Closed baseline finding", "Closed", "verified"),
                            ("#2", "Medium", "Need clearer copy", "Residual", "/tmp/m-wiz-test-carla.md"),
                            ("#3", "Low", "Flow still brittle", "Residual (Carryover)", "Tomás test"),
                        ]
                    ),
                    residuals=[
                        "- #4 Low requires manual workaround",
                        "- #3: duplicate residual from narrative notes",
                    ],
                ),
                encoding="utf-8",
            )
            seeded = seed_mwiz_residual_intakes(
                persona_report_path=report,
                intake_store_dir=base_dir / "intake",
            )
            payloads = [json.loads(item.path.read_text(encoding="utf-8")) for item in seeded]

        self.assertEqual(len(seeded), 3)
        self.assertEqual([item.finding.number for item in seeded], ["#2", "#3", "#4"])
        self.assertEqual([payload["source_type"] for payload in payloads], ["mwiz-residual"] * 3)
        self.assertIn("M-WIZ residual finding [#2]", payloads[0]["raw_text"])
        self.assertIn("from Carla", payloads[0]["raw_text"])
        self.assertIn("Problem statement: Need clearer copy", payloads[0]["raw_text"])
        self.assertIn("M-WIZ residual finding [#4]", payloads[2]["raw_text"])
        self.assertIn("from Unknown persona", payloads[2]["raw_text"])

    def test_mwiz_residual_seeder_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report = base_dir / "personas-post-mwiz.md"
            report.write_text(
                _mwiz_report(
                    headline="- Residual coverage sample",
                    baseline_rows=_mwiz_baseline_rows(
                        [("#5", "High", "Needs priority", "Residual", "Rocío report")]
                    ),
                    residuals=["- #5: Needs priority."],
                ),
                encoding="utf-8",
            )
            first_seeded = seed_mwiz_residual_intakes(
                persona_report_path=report,
                intake_store_dir=base_dir / "intake",
            )
            first_payload = json.loads(first_seeded[0].path.read_text(encoding="utf-8"))
            second_seeded = seed_mwiz_residual_intakes(
                persona_report_path=report,
                intake_store_dir=base_dir / "intake",
            )
            second_payload = json.loads(second_seeded[0].path.read_text(encoding="utf-8"))
            paths = list((base_dir / "intake").glob("*.json"))

        self.assertEqual(len(first_seeded), 1)
        self.assertEqual(len(second_seeded), 1)
        self.assertEqual(len(paths), 1)
        self.assertEqual(first_seeded[0].intake.id, second_seeded[0].intake.id)
        self.assertEqual(first_payload["created_at"], second_payload["created_at"])
        self.assertIn("Needs priority", first_seeded[0].intake.raw_text)

    def test_mwiz_residual_seeder_skips_closed_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            report = base_dir / "personas-post-mwiz.md"
            report.write_text(
                _mwiz_report(
                    headline="- Residual coverage sample",
                    baseline_rows=_mwiz_baseline_rows(
                        [
                            ("#6", "High", "Closed issue", "Closed", "notes"),
                            ("#7", "High", "Blocked by regression", "Residual", "notes"),
                        ]
                    ),
                    residuals=[
                        "- #6: should be skipped as closed",
                        "- #7: duplicate from residual narrative",
                    ],
                ),
                encoding="utf-8",
            )
            seeded = seed_mwiz_residual_intakes(
                persona_report_path=report,
                intake_store_dir=base_dir / "intake",
            )

        self.assertEqual(len(seeded), 1)
        self.assertEqual(seeded[0].finding.number, "#7")


def _mwiz_report(*, headline: str, baseline_rows: str, residuals: list[str]) -> str:
    residual_text = "\n".join(residuals) if residuals else "_No residual findings were reported as open._"
    return "\n".join(
        [
            "# Persona report",
            "",
            "## Headline metric",
            headline,
            "",
            "## Baseline comparison table",
            baseline_rows,
            "### New findings introduced post-MWIZ",
            _mwiz_new_findings(),
            "## Residuals",
            residual_text,
        ]
    )


def _mwiz_baseline_rows(rows: list[tuple[str, str, str, str, str]]) -> str:
    lines = [
        "| Baseline finding | Severity | Baseline description | Post-MWIZ status | Evidence / notes |",
        "|---|---|---|---|---|",
    ]
    for finding_number, severity, description, status, evidence in rows:
        lines.append(f"| {finding_number} | {severity} | {description} | {status} | {evidence} |")
    return "\n".join(lines)


def _mwiz_new_findings() -> str:
    return "\n".join(["| New finding | Severity | Description |", "|---|---|---|"])


if __name__ == "__main__":
    unittest.main()
