"""Curated-source research adapters for Overture intake ideas."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, is_dataclass
import re
from typing import Any, Literal, Mapping, Sequence

from .intake import IntakeRecord

ClaimKind = Literal["evidence", "inference"]
ResearchErrorCode = Literal[
    "invalid_intake",
    "missing_sources",
    "invalid_source",
    "no_relevant_sources",
    "adapter_failure",
]


@dataclass(frozen=True)
class SourceReference:
    """Stable reference for a curated web or document source."""

    title: str
    url: str | None = None
    citation: str | None = None

    @property
    def reference(self) -> str:
        return self.url or self.citation or self.title


@dataclass(frozen=True)
class ResearchClaim:
    text: str
    kind: ClaimKind
    confidence: float


@dataclass(frozen=True)
class ResearchItem:
    source: SourceReference
    summary: str
    claims: tuple[ResearchClaim, ...]
    relevance_score: float
    confidence: float


@dataclass(frozen=True)
class ResearchError:
    code: ResearchErrorCode
    message: str
    source: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchResult:
    intake_id: str | None
    items: tuple[ResearchItem, ...] = ()
    errors: tuple[ResearchError, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.items) and not self.errors


@dataclass(frozen=True)
class CuratedSource:
    title: str
    summary: str
    url: str | None = None
    citation: str | None = None
    evidence_claims: tuple[str, ...] = ()
    inference_claims: tuple[str, ...] = ()


class ResearchAdapter(ABC):
    """Interface for deterministic research adapters."""

    @abstractmethod
    def research(self, intake: IntakeRecord | Mapping[str, Any]) -> ResearchResult:
        """Return structured research notes for an intake idea."""


class CuratedSourceResearchAdapter(ResearchAdapter):
    """Research adapter backed by caller-provided curated sources.

    This intentionally does not browse or autonomously discover sources. It
    scores and normalizes an explicit source set so downstream graph ingestion
    can consume a stable contract while fuller research automation is deferred.
    """

    def __init__(self, sources: Sequence[CuratedSource | Mapping[str, Any]], *, min_relevance: float = 0.05) -> None:
        self._sources = tuple(sources)
        self._min_relevance = min_relevance

    def research(self, intake: IntakeRecord | Mapping[str, Any]) -> ResearchResult:
        try:
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

            if not self._sources:
                return ResearchResult(
                    intake_id=normalized_intake.id,
                    errors=(ResearchError(code="missing_sources", message="at least one curated source is required"),),
                )

            items: list[ResearchItem] = []
            errors: list[ResearchError] = []
            for index, source_payload in enumerate(self._sources):
                source = _normalize_source(source_payload)
                if source is None:
                    errors.append(
                        ResearchError(
                            code="invalid_source",
                            message="source must include title, summary, and either url or citation",
                            source=f"source[{index}]",
                        )
                    )
                    continue

                item = _build_item(normalized_intake, source)
                if item.relevance_score >= self._min_relevance:
                    items.append(item)

            if not items and not errors:
                errors.append(
                    ResearchError(
                        code="no_relevant_sources",
                        message="no curated sources met the minimum relevance threshold",
                        details={"min_relevance": self._min_relevance},
                    )
                )

            return ResearchResult(intake_id=normalized_intake.id, items=tuple(items), errors=tuple(errors))
        except Exception as exc:  # pragma: no cover - defensive boundary for pipeline callers
            return ResearchResult(
                intake_id=getattr(intake, "id", None) if intake is not None else None,
                errors=(ResearchError(code="adapter_failure", message=str(exc)),),
            )


def _normalize_intake(intake: IntakeRecord | Mapping[str, Any]) -> IntakeRecord | None:
    if isinstance(intake, IntakeRecord):
        text = intake.normalized_summary or intake.raw_text
        return intake if text.strip() else None

    if not isinstance(intake, Mapping):
        return None

    raw_text = str(intake.get("raw_text") or intake.get("normalized_summary") or "").strip()
    if not raw_text:
        return None

    return IntakeRecord(
        id=str(intake.get("id") or "idea_ad_hoc"),
        raw_text=raw_text,
        created_at=str(intake.get("created_at") or ""),
        source_type=str(intake.get("source_type") or "unknown"),
        normalized_summary=str(intake.get("normalized_summary") or raw_text),
        author_id=_optional_str(intake.get("author_id")),
        author_email=_optional_str(intake.get("author_email")),
    )


def _normalize_source(source: CuratedSource | Mapping[str, Any]) -> CuratedSource | None:
    if isinstance(source, CuratedSource):
        candidate = source
    elif is_dataclass(source):
        candidate = CuratedSource(**asdict(source))
    elif isinstance(source, Mapping):
        candidate = CuratedSource(
            title=str(source.get("title") or "").strip(),
            summary=str(source.get("summary") or source.get("content") or "").strip(),
            url=_optional_str(source.get("url")),
            citation=_optional_str(source.get("citation")),
            evidence_claims=tuple(str(claim).strip() for claim in source.get("evidence_claims", ()) if str(claim).strip()),
            inference_claims=tuple(str(claim).strip() for claim in source.get("inference_claims", ()) if str(claim).strip()),
        )
    else:
        return None

    if not candidate.title.strip() or not candidate.summary.strip() or not (candidate.url or candidate.citation):
        return None
    return candidate


def _build_item(intake: IntakeRecord, source: CuratedSource) -> ResearchItem:
    relevance = _relevance_score(intake.normalized_summary or intake.raw_text, source)
    evidence_claims = source.evidence_claims or _extract_evidence_claims(source.summary)
    claims = [
        ResearchClaim(text=claim, kind="evidence", confidence=_bounded(0.55 + relevance * 0.35))
        for claim in evidence_claims
    ]
    claims.extend(
        ResearchClaim(text=claim, kind="inference", confidence=_bounded(0.35 + relevance * 0.3))
        for claim in source.inference_claims
    )

    confidence = _bounded(0.45 + relevance * 0.4 + min(len(claims), 4) * 0.04)
    return ResearchItem(
        source=SourceReference(title=source.title, url=source.url, citation=source.citation),
        summary=source.summary,
        claims=tuple(claims),
        relevance_score=relevance,
        confidence=confidence,
    )


def _extract_evidence_claims(summary: str) -> tuple[str, ...]:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", summary) if sentence.strip()]
    return tuple(sentences[:2] or [summary.strip()])


def _relevance_score(idea_text: str, source: CuratedSource) -> float:
    idea_terms = _tokens(idea_text)
    source_terms = _tokens(" ".join([source.title, source.summary, *source.evidence_claims, *source.inference_claims]))
    if not idea_terms or not source_terms:
        return 0.0
    overlap = len(idea_terms & source_terms)
    coverage = overlap / len(idea_terms)
    density = overlap / len(source_terms)
    return _bounded(coverage * 0.75 + density * 0.25)


def _tokens(text: str) -> set[str]:
    stop_words = {
        "a",
        "an",
        "and",
        "as",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
    }
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2 and token not in stop_words}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)
