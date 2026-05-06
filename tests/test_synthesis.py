from overture.synthesis import BRIEF_SECTION_ORDER, GraphContext, synthesize_graph_context


def test_synthesizes_overture_mvp_graph_into_structured_brief() -> None:
    graph = GraphContext(
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
                "desired_outcome": "Trace generated tickets back to ideas, evidence, claims, risks, and constraints.",
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
                "label": "Graph must be non-hierarchical",
                "statement": "Typed graph edges are required to preserve non-hierarchical relationships between Overture concepts.",
                "claim_kind": "interpretation",
                "confidence": "high",
                "provenance": {
                    "origin": "synthesis",
                    "source_node_ids": ["userinput_overture_mvp_intake"],
                    "source_refs": ["Linear:ERI-8"],
                    "confidence": "high",
                },
            },
            {
                "id": "claim_ticket_priority_assumption",
                "type": "Claim",
                "label": "Ticket priority assumption",
                "statement": "The first implementation ticket should focus on structured synthesis before ticket generation.",
                "claim_kind": "assumption",
                "confidence": "medium",
                "provenance": {
                    "origin": "synthesis",
                    "source_node_ids": ["idea_overture_mvp_knowledge_graph"],
                    "confidence": "medium",
                },
            },
            {
                "id": "evidence_graph_module_scope",
                "type": "Evidence",
                "label": "Graph module scope observation",
                "summary": "The current graph module defines Source, ResearchItem, Claim, CITES, and HAS_CLAIM records.",
                "content": "overture/graph.py currently models research ingestion records and does not provide a graph-context synthesis brief.",
                "provenance": {
                    "origin": "research",
                    "source_node_ids": ["source_repo_graph_module"],
                    "source_refs": ["overture/graph.py"],
                    "confidence": "high",
                },
            },
            {
                "id": "component_graph_context_synthesizer",
                "type": "Component",
                "label": "Graph context synthesizer",
                "summary": "A deterministic module that turns relevant graph nodes, edges, claims, and evidence into a structured brief.",
                "provenance": {
                    "origin": "synthesis",
                    "source_node_ids": ["idea_overture_mvp_knowledge_graph", "need_preserve_topology_and_provenance"],
                    "source_refs": ["Linear:ERI-9"],
                    "confidence": "high",
                },
            },
            {
                "id": "risk_flat_summary_loses_ticket_context",
                "type": "Risk",
                "label": "Flat summary loses context",
                "summary": "Ticket generation may lose why a candidate exists if graph topology is not preserved.",
                "mitigation": "Keep evidence, assumptions, and graph relationships in separate brief fields.",
                "provenance": {
                    "origin": "synthesis",
                    "source_node_ids": ["need_preserve_topology_and_provenance", "claim_graph_must_be_non_hierarchical"],
                    "source_refs": ["Linear:ERI-9"],
                    "confidence": "medium",
                },
            },
            {
                "id": "ticketcandidate_implement_graph_context_synthesis",
                "type": "TicketCandidate",
                "label": "Implement graph-context synthesis",
                "title": "Implement graph-context synthesis brief",
                "scope": "Add a synthesis function that accepts graph context and returns stable brief sections for ticket generation.",
                "validation_plan": [
                    "Run synthesis on the Overture MVP sample graph.",
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
                "id": "idea_overture_mvp_knowledge_graph__derived_from__userinput_overture_mvp_intake",
                "type": "derived_from",
                "from": "idea_overture_mvp_knowledge_graph",
                "to": "userinput_overture_mvp_intake",
            },
            {
                "id": "need_preserve_topology_and_provenance__derived_from__idea_overture_mvp_knowledge_graph",
                "type": "derived_from",
                "from": "need_preserve_topology_and_provenance",
                "to": "idea_overture_mvp_knowledge_graph",
            },
            {
                "id": "evidence_graph_module_scope__supports__component_graph_context_synthesizer",
                "type": "supports",
                "from": "evidence_graph_module_scope",
                "to": "component_graph_context_synthesizer",
            },
            {
                "id": "component_graph_context_synthesizer__addresses__need_preserve_topology_and_provenance",
                "type": "addresses",
                "from": "component_graph_context_synthesizer",
                "to": "need_preserve_topology_and_provenance",
            },
            {
                "id": "idea_overture_mvp_knowledge_graph__suggests__ticketcandidate_implement_graph_context_synthesis",
                "type": "suggests",
                "from": "idea_overture_mvp_knowledge_graph",
                "to": "ticketcandidate_implement_graph_context_synthesis",
            },
        ),
    )

    brief = synthesize_graph_context(graph)

    assert brief.section_order == BRIEF_SECTION_ORDER
    assert "research-backed graph knowledge" in brief.problem
    assert "show why insights exist" in brief.user_need
    assert len(brief.relevant_evidence.evidence) == 1
    assert brief.relevant_evidence.evidence[0].source_refs == ("overture/graph.py",)
    assert [claim.id for claim in brief.relevant_evidence.evidence_backed_claims] == ["claim_graph_must_be_non_hierarchical"]
    assert [claim.id for claim in brief.relevant_evidence.assumptions] == ["claim_ticket_priority_assumption"]
    assert any(concept.id == "component_graph_context_synthesizer" for concept in brief.connected_concepts)
    assert any(concept.label == "Graph context synthesizer" for concept in brief.connected_concepts)
    assert "First candidate: Implement graph-context synthesis brief." in brief.proposed_capability
    assert "Flat summary loses context" in brief.risks_uncertainty[0]
    assert brief.open_questions
    assert brief.candidate_ticket_breakdown[0].title == "Implement graph-context synthesis brief"
    assert brief.candidate_ticket_breakdown[0].validation_plan
    assert "need_preserve_topology_and_provenance" in brief.candidate_ticket_breakdown[0].source_node_ids


def test_synthesis_accepts_mapping_context_and_returns_fallback_ticket() -> None:
    brief = synthesize_graph_context(
        {
            "nodes": [
                {
                    "id": "idea_minimal",
                    "type": "Idea",
                    "summary": "Turn graph context into ticket-ready synthesis.",
                }
            ],
            "edges": [],
            "claims": [],
            "evidence": [],
        }
    )

    assert brief.candidate_ticket_breakdown[0].id == "ticketcandidate_synthesize_graph_context"
    assert brief.to_dict()["section_order"] == BRIEF_SECTION_ORDER
