"""Graph ingestion records for Overture synthesis steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .research import ResearchResult

GraphRecordKind = Literal[
    "Source",
    "ResearchItem",
    "Evidence",
    "Claim",
    "Idea",
    "Need",
    "Component",
    "Capability",
    "Constraint",
    "Risk",
    "TicketCandidate",
    "UserInput",
    "CITES",
    "HAS_CLAIM",
    "derived_from",
    "supports",
    "addresses",
    "depends_on",
    "embeds",
    "instantiates",
    "references",
    "requires",
    "suggests",
]


@dataclass(frozen=True)
class GraphRecord:
    kind: GraphRecordKind
    key: str
    properties: dict[str, Any]


def research_result_to_graph_records(result: ResearchResult) -> tuple[GraphRecord, ...]:
    """Convert research adapter output into graph-ingestion records."""

    records: list[GraphRecord] = []
    for item_index, item in enumerate(result.items):
        source_key = _key("source", item.source.reference)
        item_key = _key("research_item", result.intake_id or "unknown", str(item_index), item.source.reference)

        records.append(
            GraphRecord(
                kind="Source",
                key=source_key,
                properties={
                    "title": item.source.title,
                    "url": item.source.url,
                    "citation": item.source.citation,
                    "reference": item.source.reference,
                },
            )
        )
        records.append(
            GraphRecord(
                kind="ResearchItem",
                key=item_key,
                properties={
                    "intake_id": result.intake_id,
                    "summary": item.summary,
                    "relevance_score": item.relevance_score,
                    "confidence": item.confidence,
                },
            )
        )
        records.append(GraphRecord(kind="CITES", key=_key(item_key, "cites", source_key), properties={"from": item_key, "to": source_key}))

        for claim_index, claim in enumerate(item.claims):
            claim_key = _key("claim", item_key, str(claim_index))
            records.append(
                GraphRecord(
                    kind="Claim",
                    key=claim_key,
                    properties={
                        "text": claim.text,
                        "kind": claim.kind,
                        "confidence": claim.confidence,
                    },
                )
            )
            records.append(
                GraphRecord(
                    kind="HAS_CLAIM",
                    key=_key(item_key, "has_claim", claim_key),
                    properties={"from": item_key, "to": claim_key},
                )
            )

    return tuple(records)


def _key(*parts: str) -> str:
    return ":".join(_slug(part) for part in parts)


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")[:80] or "unknown"
