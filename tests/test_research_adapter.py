from overture.graph import research_result_to_graph_records
from overture.intake import IntakeRecord
from overture.research import CuratedSourceResearchAdapter, ResearchAdapter


def test_curated_source_adapter_accepts_intake_and_returns_structured_items() -> None:
    intake = IntakeRecord(
        id="idea_overture",
        raw_text="Use Overture to turn curated research into graph-backed Symphony tickets",
        created_at="2026-05-05T00:00:00Z",
        source_type="test",
        normalized_summary="Use Overture to turn curated research into graph-backed Symphony tickets",
    )
    adapter: ResearchAdapter = CuratedSourceResearchAdapter(
        [
            {
                "title": "Overture ticket schema",
                "url": "https://example.test/overture-ticket-schema",
                "summary": "Overture generated tickets should preserve sources, graph provenance, and validation plans.",
                "evidence_claims": [
                    "The schema requires sources or evidence for generated tickets.",
                    "The schema requires graph provenance with source node identifiers.",
                ],
                "inference_claims": [
                    "Curated research notes can provide source-backed inputs for graph synthesis.",
                ],
            }
        ]
    )

    result = adapter.research(intake)

    assert result.ok
    assert result.intake_id == "idea_overture"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source.url == "https://example.test/overture-ticket-schema"
    assert item.summary
    assert item.relevance_score > 0
    assert 0 <= item.confidence <= 1
    assert {claim.kind for claim in item.claims} == {"evidence", "inference"}
    assert all(0 <= claim.confidence <= 1 for claim in item.claims)


def test_curated_source_adapter_returns_structured_errors() -> None:
    result = CuratedSourceResearchAdapter([]).research({"id": "empty", "raw_text": "Overture research"})

    assert not result.ok
    assert result.items == ()
    assert result.errors[0].code == "missing_sources"


def test_graph_ingestion_consumes_research_output() -> None:
    intake = {
        "id": "idea_overture",
        "raw_text": "Overture graph research sources",
        "normalized_summary": "Overture graph research sources",
    }
    result = CuratedSourceResearchAdapter(
        [
            {
                "title": "Internal Overture notes",
                "citation": "docs/symphony-ready-ticket-schema.md",
                "summary": "Overture tickets include sources, evidence, graph provenance, and validation.",
            }
        ]
    ).research(intake)

    records = research_result_to_graph_records(result)
    kinds = [record.kind for record in records]

    assert "Source" in kinds
    assert "ResearchItem" in kinds
    assert "Claim" in kinds
    assert "CITES" in kinds
    assert "HAS_CLAIM" in kinds
    assert any(record.properties.get("intake_id") == "idea_overture" for record in records)
