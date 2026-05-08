import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from overture.intake import create_intake_record
from overture.research_llm import (
    CODEX_EXECUTABLE_ENV,
    LLMSuggestedSourceAdapter,
    codex_cli_available,
    codex_cli_client,
)


def _intake() -> dict[str, str]:
    return {
        "id": "idea_llm_research",
        "raw_text": "Help designers turn Overture intake into research-backed Symphony tickets",
        "normalized_summary": "Help designers turn Overture intake into research-backed Symphony tickets",
    }


def _valid_sources() -> str:
    return json.dumps(
        [
            {
                "title": "Overture research contract",
                "url": "https://example.test/overture-research-contract",
                "citation": None,
                "summary": (
                    "Overture research should preserve evidence, source URLs, "
                    "graph provenance, and Symphony ticket validation."
                ),
                "evidence_claims": [
                    "Research items include evidence claims for downstream Symphony tickets.",
                    "Source URLs and provenance should remain attached to the research output.",
                ],
                "inference_claims": [
                    "LLM-suggested source approval can reduce manual JSON authoring for designers.",
                ],
            },
            {
                "title": "Designer intake approval workflow",
                "url": "https://example.test/designer-intake-approval",
                "citation": None,
                "summary": (
                    "Designer intake workflows need suggested sources and a manual approval "
                    "step before accepted evidence is stored."
                ),
                "evidence_claims": [
                    "Manual approval prevents unreviewed source suggestions from entering the pipeline.",
                ],
                "inference_claims": [
                    "A CLI approval step is sufficient for validating the first source suggestion workflow.",
                ],
            },
        ]
    )


class LLMSuggestedSourceAdapterTests(unittest.TestCase):
    def test_happy_path_returns_curated_research_shape(self) -> None:
        prompts: list[str] = []

        def fake_llm(prompt: str) -> str:
            prompts.append(prompt)
            return _valid_sources()

        adapter = LLMSuggestedSourceAdapter(llm_client=fake_llm, approver=lambda source: True)

        result = adapter.research(_intake())

        self.assertTrue(result.ok)
        self.assertEqual(len(prompts), 1)
        self.assertIn("Response JSON schema", prompts[0])
        self.assertEqual(result.intake_id, "idea_llm_research")
        self.assertEqual(len(result.items), 2)
        for item in result.items:
            self.assertTrue(item.source.title)
            self.assertTrue(item.source.url)
            self.assertTrue(item.summary)
            self.assertGreater(item.relevance_score, 0)
            self.assertGreater(item.confidence, 0)
            self.assertTrue(item.claims)
            self.assertTrue(all(claim.text and claim.kind in {"evidence", "inference"} for claim in item.claims))

    def test_all_rejected_returns_no_relevant_sources(self) -> None:
        adapter = LLMSuggestedSourceAdapter(llm_client=lambda prompt: _valid_sources(), approver=lambda source: False)

        result = adapter.research(_intake())

        self.assertFalse(result.ok)
        self.assertEqual(result.items, ())
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].code, "no_relevant_sources")

    def test_malformed_json_returns_adapter_failure(self) -> None:
        adapter = LLMSuggestedSourceAdapter(llm_client=lambda prompt: "not-json", approver=lambda source: True)

        result = adapter.research(_intake())

        self.assertFalse(result.ok)
        self.assertEqual(result.items, ())
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].code, "adapter_failure")

    def test_approver_can_reject_fake_url_without_breaking_adapter(self) -> None:
        response = json.dumps(
            [
                {
                    "title": "Fake plausible URL",
                    "url": "https://example.invalid/hallucinated",
                    "citation": None,
                    "summary": "This fake source should be rejected by the approver.",
                    "evidence_claims": ["A rejected source should not become a research item."],
                    "inference_claims": [],
                },
                json.loads(_valid_sources())[0],
            ]
        )

        def reject_invalid(source) -> bool:
            return source.url != "https://example.invalid/hallucinated"

        adapter = LLMSuggestedSourceAdapter(llm_client=lambda prompt: response, approver=reject_invalid)

        result = adapter.research(_intake())

        self.assertTrue(result.ok)
        self.assertEqual(len(result.items), 1)
        self.assertNotEqual(result.items[0].source.url, "https://example.invalid/hallucinated")

    def test_codex_cli_client_reports_missing_executable(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "", CODEX_EXECUTABLE_ENV: ""}):
            with self.assertRaisesRegex(RuntimeError, "Codex CLI executable not found on PATH"):
                codex_cli_client("Suggest sources")

    def test_codex_cli_client_uses_configured_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "fake-codex"
            argv_log = Path(tmpdir) / "argv.log"
            executable.write_text(
                "#!/bin/sh\n"
                f'printf "%s\\n" "$@" > "{argv_log}"\n'
                "cat >/dev/null\n"
                "printf '[{\"title\":\"Configured Codex\"}]\\n'\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)

            with mock.patch.dict(os.environ, {CODEX_EXECUTABLE_ENV: str(executable)}):
                self.assertEqual(codex_cli_client("Suggest sources"), '[{"title":"Configured Codex"}]\n')

            argv = argv_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(argv, ["exec"])
            self.assertNotIn("--non-interactive", argv)

    def test_codex_cli_available_false_when_missing_from_path(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "", CODEX_EXECUTABLE_ENV: ""}):
            self.assertFalse(codex_cli_available())

    def test_codex_cli_available_true_when_configured_executable_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "fake-codex"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            with mock.patch.dict(os.environ, {CODEX_EXECUTABLE_ENV: str(executable)}):
                self.assertTrue(codex_cli_available())

    def test_codex_cli_available_false_when_configured_path_missing(self) -> None:
        with mock.patch.dict(os.environ, {CODEX_EXECUTABLE_ENV: "/nonexistent/codex-binary"}):
            self.assertFalse(codex_cli_available())


class ResearchCliTests(unittest.TestCase):
    def test_research_command_with_fake_client_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            intake, _ = create_intake_record(
                "Help designers turn Overture intake into research-backed Symphony tickets",
                base_dir / "intake",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "overture",
                    "research",
                    intake.id,
                    "--store-dir",
                    str(base_dir),
                ],
                check=True,
                capture_output=True,
                input="y\ny\n",
                text=True,
                env={"OVERTURE_LLM_CLIENT": "fake", **dict(os.environ)},
            )

            output_path = Path(result.stdout.splitlines()[-1])
            self.assertEqual(output_path, base_dir / "research" / f"{intake.id}.json")
            self.assertTrue(output_path.exists())

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["intake_id"], intake.id)
            self.assertEqual(len(payload["items"]), 2)
            self.assertEqual(payload["errors"], [])
            for item in payload["items"]:
                self.assertTrue(item["claims"])
                self.assertGreater(item["confidence"], 0)

    def test_research_command_falls_back_when_codex_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            intake, _ = create_intake_record(
                "Help designers turn Overture intake into research-backed Symphony tickets",
                base_dir / "intake",
            )

            sandbox_path = Path(tmpdir) / "empty-bin"
            sandbox_path.mkdir()
            child_env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"OVERTURE_LLM_CLIENT", CODEX_EXECUTABLE_ENV}
            }
            child_env["PATH"] = str(sandbox_path)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "overture",
                    "research",
                    intake.id,
                    "--store-dir",
                    str(base_dir),
                ],
                check=True,
                capture_output=True,
                input="y\ny\n",
                text=True,
                env=child_env,
            )

            self.assertIn("Codex CLI not found on PATH", result.stderr)
            output_path = Path(result.stdout.splitlines()[-1])
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["intake_id"], intake.id)
            self.assertEqual(len(payload["items"]), 2)


if __name__ == "__main__":
    unittest.main()
