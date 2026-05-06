# Add graph-context synthesis brief

## Context

User wants rough product ideas converted into research-backed graph knowledge and Symphony-ready Linear tickets. This task fits the Overture idea-to-research-to-graph-to-ticket flow by turning `SynthesisBrief` output from `overture/synthesis.py` into a paste-ready Linear issue draft.

## Problem

Autonomous implementation agents need graph outputs that show why insights exist and how they relate. Without a validated ticket-writing step, Symphony cannot reliably start from the synthesis output because the required Linear title, Markdown sections, validation commands, sources, and graph provenance may be missing.

## Proposed change

Generate a Linear issue draft for `ticketcandidate_implement_graph_context_synthesis`.

Required behavior:

- Accept the synthesis output as structured input.
- Use the candidate scope: Add a synthesis function that accepts graph context and returns stable brief sections for ticket generation.
- Emit a `title` field and a Markdown `description` field.
- Format the description with the canonical Symphony-ready ticket sections.
- Validate the generated payload before it is sent to Linear.

## Acceptance criteria

- [ ] The ticket writer accepts a synthesis output and selects a candidate ticket.
- [ ] The generated payload includes a Linear-ready title and Markdown description.
- [ ] The description includes context, proposed change, acceptance criteria, validation, sources, and out-of-scope.
- [ ] The description includes graph provenance with source nodes, relationships, confidence, and conflicts.
- [ ] The payload validates against the Symphony-ready ticket schema before handoff.
- [ ] The selected candidate readiness is preserved as `ready` in the generated task context.

## Validation plan

- Run synthesis on the Overture MVP sample graph and confirm a draft is generated.
- Confirm candidate ticket title, scope, validation, and source graph nodes are populated.
- Run `python -m pytest` and confirm the ticket writer tests pass.

## Sources / evidence

- `overture/graph.py`: The current graph module defines Source, ResearchItem, Claim, CITES, and HAS_CLAIM records.
- `Linear:ERI-8`: Typed graph edges are required to preserve non-hierarchical relationships between Overture concepts.

## Graph provenance

- Nodes: `idea_overture_mvp_knowledge_graph`, `need_preserve_topology_and_provenance`, `risk_flat_summary_loses_ticket_context`, `ticketcandidate_implement_graph_context_synthesis`
- Edges: suggests -> ticketcandidate_implement_graph_context_synthesis; blocks -> ticketcandidate_implement_graph_context_synthesis
- Confidence: high.
- Conflicts: None.

## Dependencies

- None.

## Out of scope

- Do not create the Linear issue automatically.
- Do not expand into unrelated graph schema or research ingestion changes.

## Risk / uncertainty

- Flat summary loses context: Ticket generation may lose why a candidate exists if graph topology is not preserved. Mitigation: Keep evidence, assumptions, and graph relationships in separate brief fields.

## Follow-up candidates

- None.
