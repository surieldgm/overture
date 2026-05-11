import json
import tempfile
import unittest
from pathlib import Path

from overture.backlog_seeder import seed_mwiz_residual_intakes
from overture.milestone_verifier import verify_milestone_config
from overture.retro_generator import generate_retro_document


class MwizClosingSmokeTests(unittest.TestCase):
    def test_mwiz_closing_chain_passes_for_synthetic_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config_path = _write_mwiz_config(workspace)
            report_path = _write_mwiz_report(workspace)
            _write_mwiz_schema_draft(workspace)

            verification = verify_milestone_config(config_path, workspace=workspace)
            self.assertTrue(verification.passed, verification.criteria)
            self.assertEqual(verification.milestone, "M-WIZ")

            for result in verification.criteria:
                self.assertTrue(result.passed, f"criterion failed: {result.name}")

            retro_path = workspace / ".overture" / "retros" / "milestone-retro.md"
            generate_retro_document(
                output_path=retro_path,
                persona_report_path=report_path,
                milestone="M-WIZ",
                started_at="2026-05-09T00:00:00.000000Z",
                completed_at="2026-05-10T00:00:00.000000Z",
            )
            retro_text = retro_path.read_text(encoding="utf-8")
            self.assertTrue(retro_path.exists(), "retro output path should exist")
            self.assertIn("## Residual findings carried forward", retro_text)
            self.assertIn("## Qualitative summary", retro_text)

            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("## Baseline comparison table", report_text)

            seeded = seed_mwiz_residual_intakes(
                persona_report_path=report_path,
                intake_store_dir=workspace / ".overture" / "intake",
            )

            self.assertEqual(len(seeded), 2)
            intake_payloads = [json.loads(item.path.read_text(encoding="utf-8")) for item in seeded]

            self.assertEqual(sorted(item.finding.number for item in seeded), ["#3", "#4"])
            payload_by_number = {
                payload["raw_text"].split("[", 1)[1].split("]", 1)[0]: payload
                for payload in intake_payloads
            }
            self.assertEqual(payload_by_number["#3"]["source_type"], "mwiz-residual")
            self.assertEqual(payload_by_number["#4"]["source_type"], "mwiz-residual")
            self.assertIn("Problem statement: Needs clearer copy.", payload_by_number["#3"]["raw_text"])
            self.assertIn("Needs explicit guardrail", payload_by_number["#4"]["raw_text"])


def _write_mwiz_config(workspace: Path) -> Path:
    config = {
        "milestone": "M-WIZ",
        "criteria": {
            "mwiz_persona_completion": {
                "kind": "mwiz_persona_completion",
                "target": 2,
                "report_glob": "docs/user-tests/*personas-post-mwiz*.md",
            },
            "mwiz_baseline_coverage": {
                "kind": "mwiz_baseline_coverage",
                "target": 2,
                "report_glob": "docs/user-tests/*personas-post-mwiz*.md",
            },
            "mwiz_smoke_tests": {
                "kind": "mwiz_smoke_tests",
                "target": 2,
                "commands": [
                    "python -c \"import sys; sys.exit(0)\"",
                    "python -c \"import sys; sys.exit(0)\"",
                ],
            },
            "mwiz_schema_validators": {
                "kind": "mwiz_schema_validators",
                "target": 1,
                "ticket_drafts": ["mwiz_schema_draft.md"],
            },
        },
    }
    path = workspace / "mwiz-smoke-config.json"
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_mwiz_report(workspace: Path) -> Path:
    report = workspace / "docs" / "user-tests" / "personas-post-mwiz-synthetic-smoke.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        (
            "# Synthetic post-MWIZ report\n\n"
            "**2 of 3 personas completed idea→ticket via wizard.**\n\n"
            "## Headline metric\n\n"
            "**Residual findings are reduced after synthesis.**\n\n"
            "## Baseline comparison table\n\n"
            "| Baseline finding | Severity | Baseline description | Post-MWIZ status | Evidence / notes |\n"
            "|---|---|---|---|---|\n"
            "| #1 | High | Closed baseline issue | Closed | validated with /tmp/m-wiz-test-carla.md |\n"
            "| #2 | Medium | Needs prioritization path | Closed | validated with /tmp/m-wiz-test-tomas.md |\n"
            "| #3 | Low | Needs clearer copy | Residual | traced to /tmp/m-wiz-test-carla.md |\n"
            "| #4 | Medium | Needs explicit guardrail | Residual | traced to /tmp/m-wiz-test-rocio.md |\n\n"
            "## New findings introduced post-MWIZ\n"
            "| New finding | Severity | Description |\n"
            "|---|---|---|\n"
            "## Residuals\n"
            "- #3: Needs clearer copy for release notes.\n"
            "- #4: Needs explicit guardrail for edge cases.\n"
        ),
        encoding="utf-8",
    )
    return report


def _write_mwiz_schema_draft(workspace: Path) -> None:
    template_path = (
        Path(__file__).resolve().parent.parent
        / "examples"
        / "overture_mvp_linear_issue_draft.md"
    )
    path = workspace / "mwiz_schema_draft.md"
    path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
