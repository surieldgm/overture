import unittest

from overture.synthesis import GraphContext, synthesize_graph_context
from overture.ticket_writer import (
    REQUIRED_SECTION_HEADINGS,
    generate_linear_issue_draft,
    validate_linear_issue_payload,
)


def test_generates_schema_valid_linear_issue_draft_from_synthesis() -> None:
    brief = synthesize_graph_context(_overture_mvp_graph())

    draft = generate_linear_issue_draft(brief)

    assert draft.title == "Add graph-context synthesis brief"
    assert draft.to_dict()["title"] == draft.title
    assert draft.description.startswith("# Add graph-context synthesis brief")
    assert [line for line in draft.description.splitlines() if line.startswith("#")] == [
        "# Add graph-context synthesis brief",
        *REQUIRED_SECTION_HEADINGS,
    ]
    assert "## Context" in draft.description
    assert "## Proposed change" in draft.description
    assert "## Acceptance criteria" in draft.description
    assert "## Validation plan" in draft.description
    assert "## Sources / evidence" in draft.description
    assert "## Out of scope" in draft.description
    assert "`overture/graph.py`" in draft.description
    assert "`need_preserve_topology_and_provenance`" in draft.description
    assert validate_linear_issue_payload(draft.title, draft.description) == ()


def test_ticket_writer_accepts_mapping_synthesis_output() -> None:
    brief = synthesize_graph_context(_overture_mvp_graph())

    draft = generate_linear_issue_draft(brief.to_dict())

    assert draft.title == "Add graph-context synthesis brief"
    assert validate_linear_issue_payload(draft.title, draft.description) == ()


def test_ticket_writer_prefixes_prior_concepts_in_graph_provenance() -> None:
    brief = synthesize_graph_context(
        _overture_mvp_graph(),
        prior_context=GraphContext(
            nodes=(
                {
                    "id": "idea_prior_state",
                    "type": "Idea",
                    "summary": "Prior idea to compare against.",
                    "created_at": "2026-05-04T00:00:00Z",
                },
            )
        ),
    )

    draft = generate_linear_issue_draft(brief)

    assert "`prior:idea_prior_state`" in draft.description
    assert validate_linear_issue_payload(draft.title, draft.description) == ()


def test_validation_rejects_missing_required_ticket_sections() -> None:
    errors = validate_linear_issue_payload(
        "Add invalid ticket",
        "# Add invalid ticket\n\n## Context\n\nOnly context.",
    )

    assert "required sections must appear in canonical order" in errors
    assert any("required sections cannot be empty" in error for error in errors)


class TicketWriterGraphProvenanceContractTests(unittest.TestCase):
    def test_generated_draft_uses_export_graph_provenance_labels(self) -> None:
        draft = generate_linear_issue_draft(synthesize_graph_context(_overture_mvp_graph()))

        self.assertIn("- Nodes:", draft.description)
        self.assertIn("- Edges:", draft.description)
        self.assertIn("- Confidence:", draft.description)
        self.assertIn("- Conflicts:", draft.description)
        self.assertNotIn("Source node IDs:", draft.description)
        self.assertNotIn("Relationships:", draft.description)
        self.assertEqual(validate_linear_issue_payload(draft.title, draft.description), ())

    def test_export_validator_rejects_legacy_graph_provenance_labels(self) -> None:
        draft = generate_linear_issue_draft(synthesize_graph_context(_overture_mvp_graph()))
        legacy_description = (
            draft.description.replace("Nodes:", "Source node IDs:")
            .replace("Edges:", "Relationships:")
            .replace("Confidence:", "Graph synthesis confidence:")
            .replace("Conflicts:", "Unresolved graph conflicts:")
        )

        errors = validate_linear_issue_payload(draft.title, legacy_description)

        self.assertIn("Graph provenance missing Nodes:", errors)
        self.assertIn("Graph provenance missing Edges:", errors)
        self.assertIn("Graph provenance missing Confidence:", errors)
        self.assertIn("Graph provenance missing Conflicts:", errors)


def _overture_mvp_graph() -> GraphContext:
    return GraphContext(
        nodes=(
            {
                "id": "userinput_overture_mvp_intake",
                "type": "UserInput",
                "label": "Overture MVP intake",
                "summary": "User wants rough product ideas converted into research-backed graph knowledge and Symphony-ready Linear tickets.",
                "raw_text": "Build Overture so a rough product idea can become research-backed graph knowledge and then Symphony-ready Linear tickets without losing provenance.",
                "provenance": {"origin": "user_input", "source_refs": ["Linear:ERI-8"], "confidence": "high"},
            },
            {
                "id": "idea_overture_mvp_knowledge_graph",
                "type": "Idea",
                "label": "Overture MVP knowledge graph",
                "summary": "Represent intake, research, synthesis, and ticket candidates as connected graph knowledge.",
                "provenance": {
                    "origin": "synthesis",
                    "source_node_ids": ["userinput_overture_mvp_intake"],
                    "source_refs": ["Linear:ERI-8"],
                    "confidence": "high",
                },
            },
            {
                "id": "need_preserve_topology_and_provenance",
                "type": "Need",
                "label": "Preserve topology and provenance",
                "summary": "Autonomous implementation agents need graph outputs that show why insights exist and how they relate.",
                "provenance": {
                    "origin": "synthesis",
                    "source_node_ids": ["userinput_overture_mvp_intake", "idea_overture_mvp_knowledge_graph"],
                    "source_refs": ["Linear:ERI-8"],
                    "confidence": "high",
                },
            },
            {
                "id": "claim_graph_must_be_non_hierarchical",
                "type": "Claim",
                "statement": "Typed graph edges are required to preserve non-hierarchical relationships between Overture concepts.",
                "claim_kind": "interpretation",
                "confidence": "high",
                "provenance": {"origin": "synthesis", "source_refs": ["Linear:ERI-8"], "confidence": "high"},
            },
            {
                "id": "evidence_graph_module_scope",
                "type": "Evidence",
                "summary": "The current graph module defines Source, ResearchItem, Claim, CITES, and HAS_CLAIM records.",
                "provenance": {"origin": "research", "source_refs": ["overture/graph.py"], "confidence": "high"},
            },
            {
                "id": "risk_flat_summary_loses_ticket_context",
                "type": "Risk",
                "label": "Flat summary loses context",
                "summary": "Ticket generation may lose why a candidate exists if graph topology is not preserved.",
                "mitigation": "Keep evidence, assumptions, and graph relationships in separate brief fields.",
                "provenance": {"origin": "synthesis", "confidence": "medium"},
            },
            {
                "id": "ticketcandidate_implement_graph_context_synthesis",
                "type": "TicketCandidate",
                "label": "Implement graph-context synthesis",
                "title": "Implement graph-context synthesis brief",
                "scope": "Add a synthesis function that accepts graph context and returns stable brief sections for ticket generation.",
                "validation_plan": [
                    "Run synthesis on the Overture MVP sample graph and confirm a draft is generated.",
                    "Confirm candidate ticket title, scope, validation, and source graph nodes are populated.",
                ],
                "readiness": "ready",
                "provenance": {
                    "origin": "synthesis",
                    "source_node_ids": [
                        "idea_overture_mvp_knowledge_graph",
                        "need_preserve_topology_and_provenance",
                        "risk_flat_summary_loses_ticket_context",
                    ],
                    "source_refs": ["Linear:ERI-9"],
                    "confidence": "high",
                },
            },
        ),
        edges=(
            {
                "id": "idea_overture_mvp_knowledge_graph__suggests__ticketcandidate_implement_graph_context_synthesis",
                "type": "suggests",
                "from": "idea_overture_mvp_knowledge_graph",
                "to": "ticketcandidate_implement_graph_context_synthesis",
            },
            {
                "id": "risk_flat_summary_loses_ticket_context__blocks__ticketcandidate_implement_graph_context_synthesis",
                "type": "blocks",
                "from": "risk_flat_summary_loses_ticket_context",
                "to": "ticketcandidate_implement_graph_context_synthesis",
            },
        ),
    )
