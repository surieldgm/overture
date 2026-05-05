from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overture.graph import research_result_to_graph_records
from overture.intake import IntakeRecord
from overture.research import CuratedSourceResearchAdapter


intake = IntakeRecord(
    id="idea_overture_validation",
    raw_text="Use Overture to turn curated research into graph-backed Symphony-ready tickets.",
    created_at="2026-05-05T00:00:00Z",
    source_type="example",
    normalized_summary="Use Overture to turn curated research into graph-backed Symphony-ready tickets.",
)

adapter = CuratedSourceResearchAdapter(
    [
        {
            "title": "Symphony-ready Linear ticket schema",
            "citation": "docs/symphony-ready-ticket-schema.md",
            "summary": (
                "Overture generated tickets must include sources or evidence, graph provenance, "
                "acceptance criteria, and validation plans."
            ),
            "evidence_claims": [
                "The schema requires generated tickets to include stable sources or evidence.",
                "The schema requires graph provenance with node identifiers and relationship labels.",
            ],
            "inference_claims": [
                "Curated source research can seed graph synthesis before autonomous research exists.",
            ],
        }
    ]
)

result = adapter.research(intake)
records = research_result_to_graph_records(result)

print(f"items={len(result.items)} errors={len(result.errors)} graph_records={len(records)}")
print(f"claim_kinds={sorted({claim.kind for item in result.items for claim in item.claims})}")
print(f"graph_kinds={sorted({record.kind for record in records})}")
