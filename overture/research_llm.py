"""LLM-suggested source research adapter with human approval.

Approvers should open and inspect source URLs before approving candidates. The
LLM proposes possible sources, but this adapter only converts approved
candidates into structured research items.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from .intake import IntakeRecord
from .research import (
    CuratedSource,
    ResearchAdapter,
    ResearchError,
    ResearchResult,
    _build_item,
    _normalize_intake,
    _normalize_source,
)

APPROVER_SKIP_VALUES = {"n", "no", "s", "skip"}


class LLMSuggestedSourceAdapter(ResearchAdapter):
    """Research adapter that asks an LLM to suggest sources, then requires approval."""

    def __init__(
        self,
        *,
        llm_client: Callable[[str], str],
        approver: Callable[[CuratedSource], bool],
        min_sources: int = 3,
        max_sources: int = 5,
    ) -> None:
        if min_sources < 0:
            raise ValueError("min_sources must be non-negative")
        if max_sources < 1:
            raise ValueError("max_sources must be at least 1")
        if min_sources > max_sources:
            raise ValueError("min_sources cannot exceed max_sources")

        self._llm_client = llm_client
        self._approver = approver
        self._min_sources = min_sources
        self._max_sources = max_sources

    def research(self, intake: IntakeRecord | Mapping[str, Any]) -> ResearchResult:
        normalized_intake = _normalize_intake(intake)
        if normalized_intake is None:
            return ResearchResult(
                intake_id=None,
                errors=(
                    ResearchError(
                        code="invalid_intake",
                        message="intake must include non-empty raw_text or normalized_summary",
                    ),
                ),
            )

        try:
            prompt = self._build_prompt(normalized_intake)
            response = self._llm_client(prompt)
            candidates = _parse_candidates(response)

            items = []
            errors: list[ResearchError] = []
            for index, payload in enumerate(candidates[: self._max_sources]):
                source = _normalize_source(payload)
                if source is None:
                    errors.append(
                        ResearchError(
                            code="invalid_source",
                            message="candidate must include title, summary, and either url or citation",
                            source=f"candidate[{index}]",
                        )
                    )
                    continue

                if not self._approver(source):
                    continue

                items.append(_build_item(normalized_intake, source))

            if not items and not errors:
                errors.append(
                    ResearchError(
                        code="no_relevant_sources",
                        message="no LLM-suggested sources were approved",
                        details={"min_sources": self._min_sources, "max_sources": self._max_sources},
                    )
                )

            return ResearchResult(intake_id=normalized_intake.id, items=tuple(items), errors=tuple(errors))
        except Exception as exc:
            return ResearchResult(
                intake_id=normalized_intake.id,
                errors=(ResearchError(code="adapter_failure", message=str(exc)),),
            )

    def _build_prompt(self, intake: IntakeRecord) -> str:
        schema = [
            {
                "title": "string, required",
                "url": "string or null; prefer a public URL when available",
                "citation": "string or null; required when url is null",
                "summary": "string, required; concise source summary",
                "evidence_claims": ["string evidence directly supported by the source"],
                "inference_claims": ["string cautious inference relevant to the intake"],
            }
        ]
        intake_payload = {
            "id": intake.id,
            "normalized_summary": intake.normalized_summary or intake.raw_text,
            "raw_text": intake.raw_text,
        }
        return "\n".join(
            [
                "You suggest source candidates for Overture research intake.",
                "Return only strict JSON. Do not include Markdown fences or explanatory text.",
                f"Suggest between {self._min_sources} and {self._max_sources} source candidates.",
                "Each candidate must be real enough for a human approver to verify before use.",
                "",
                "Intake:",
                json.dumps(intake_payload, indent=2, sort_keys=True),
                "",
                "Response JSON schema:",
                json.dumps(schema, indent=2, sort_keys=True),
            ]
        )


def cli_approver(source: CuratedSource) -> bool:
    """Prompt on stdout/stdin for candidate approval."""

    print()
    print(f"Title: {source.title}")
    print(f"URL: {source.url or ''}")
    print(f"Summary: {source.summary}")
    while True:
        answer = input("Approve source? [y/n/s]: ").strip().lower()
        print()
        if answer in {"y", "yes"}:
            return True
        if answer in APPROVER_SKIP_VALUES:
            return False
        print("Enter y to approve, n to reject, or s to skip.")


def codex_cli_client(prompt: str) -> str:
    """Call the local Codex CLI. This opt-in client requires `codex` on PATH."""

    completed = subprocess.run(
        ["codex", "exec", "--non-interactive"],
        input=prompt,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout


def fake_llm_client(prompt: str) -> str:
    """Deterministic CLI/test hook enabled with `OVERTURE_LLM_CLIENT=fake`."""

    return json.dumps(
        [
            {
                "title": "Symphony-ready ticket evidence contract",
                "url": "https://example.test/symphony-ticket-evidence",
                "citation": None,
                "summary": (
                    "Overture research should preserve sources, evidence claims, validation plans, "
                    "and graph provenance for Symphony-ready implementation tickets."
                ),
                "evidence_claims": [
                    "Research outputs should include source-backed claims for generated tickets.",
                    "Validation plans and graph provenance should stay attached to the ticket evidence.",
                ],
                "inference_claims": [
                    "Designer-led intake needs source suggestions before graph synthesis can produce useful tickets.",
                ],
            },
            {
                "title": "Designer-led intake research workflow",
                "url": "https://example.test/designer-intake-research",
                "citation": None,
                "summary": (
                    "A semi-automatic research workflow can suggest candidate sources for designers "
                    "while keeping a manual approval step before persistence."
                ),
                "evidence_claims": [
                    "Manual approval keeps suggested sources from being accepted without review.",
                    "Approved source summaries can be converted into structured research claims.",
                ],
                "inference_claims": [
                    "A CLI approval loop is enough to validate the workflow before adding a web UI.",
                ],
            },
        ]
    )


def research_result_to_jsonable(result: ResearchResult) -> dict[str, Any]:
    return _plain(result)


def write_research_result(path: Path, result: ResearchResult) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(research_result_to_jsonable(result), indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path


def _parse_candidates(response: str) -> list[Mapping[str, Any]]:
    payload = json.loads(response)
    if not isinstance(payload, list):
        raise ValueError("LLM response must be a JSON array")

    candidates = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise ValueError(f"candidate[{index}] must be an object")
        candidates.append(item)
    return candidates


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
