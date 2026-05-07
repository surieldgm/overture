# Feature Intake Example: Idea Persistence

**Idea shape:** Feature

**M1 source:** `tests/test_dogfooding_day_one_smoke.py` and
`examples/validate_two_intake_loop.py` use this intake as the first run in the
M1 dogfooding loop.

## Raw Intake

```text
Add idea persistence to Overture
```

## Research Summary

- `docs/symphony-ready-ticket-schema.md`: Generated tickets need canonical
  sections, acceptance criteria, validation plans, evidence, graph provenance,
  dependencies, boundaries, risks, and follow-up candidates.
- `docs/minimal-knowledge-graph-schema.md`: Overture's graph model preserves
  provenance for ideas, needs, claims, evidence, risks, components, and ticket
  candidates.
- M1 dogfooding signal: the second dogfooding run queries prior graph context,
  so the first run must leave persisted idea nodes that later synthesis can
  cite.

## Brief

### Problem

The first dogfooding run needs to leave durable idea context. Without persisted
idea records, a later intake cannot prove that synthesis is using prior product
knowledge instead of only the current raw sentence.

### User Need

Maintainers need Overture to persist idea-stage graph records so follow-on
intakes can reference earlier work during synthesis and ticket drafting.

### Relevant Evidence

- The M1 two-run smoke path asserts that the second draft cites `prior:` graph
  nodes from the first run.
- The graph schema document requires stable node identifiers and source
  references.
- The ticket schema document requires graph provenance in the resulting Linear
  draft.

### Candidate Ticket Breakdown

- **Title:** Add idea persistence to Overture
- **Readiness:** Ready
- **Scope:** Persist idea nodes from intake through graph storage and expose
  them to later synthesis runs.
- **Validation plan:** Run the two-intake loop and confirm the second draft
  cites a prior node from the first run.

## Ticket

# Add idea persistence to Overture

## Context

M1 dogfooding runs Overture repeatedly against related product ideas. The first
run, `Add idea persistence to Overture`, is expected to leave graph context that
the second run can reuse when drafting a ticket.

## Problem

If idea nodes are only transient, later synthesis briefs cannot cite prior work.
That makes the idea-aware iteration loop look like a one-shot ticket generator
instead of a system that carries product memory forward.

## Proposed change

Persist intake-derived idea records in the graph store and make them available
to subsequent synthesis runs as prior context.

## Acceptance criteria

- [ ] Intake-derived idea nodes are written with stable identifiers.
- [ ] Later synthesis runs can load prior idea nodes from the graph store.
- [ ] Generated tickets include prior idea node IDs in graph provenance when
      prior context is used.

## Validation plan

- Run `python examples/validate_two_intake_loop.py`.
- Confirm the command prints at least one `prior:` node ID.
- Run `python -m unittest discover -s tests`.

## Sources / evidence

- `tests/test_dogfooding_day_one_smoke.py`: M1 two-run dogfooding smoke path.
- `examples/validate_two_intake_loop.py`: Manual validation for prior graph
  context.
- `docs/minimal-knowledge-graph-schema.md`: Graph provenance rules.

## Graph provenance

- Nodes: `userinput_add_idea_persistence`, `idea_persistence`,
  `component_graph_store`, `capability_prior_context`,
  `ticketcandidate_add_idea_persistence`.
- Edges: `userinput_add_idea_persistence -> derived_from -> idea_persistence`;
  `idea_persistence -> requires -> component_graph_store`;
  `component_graph_store -> enables -> capability_prior_context`;
  `capability_prior_context -> demonstrates -> ticketcandidate_add_idea_persistence`.
- Confidence: high.
- Conflicts: None.

## Dependencies

- Existing graph store behavior.

## Out of scope

- Do not add a new graph database.
- Do not change ticket export behavior.

## Risk / uncertainty

- Prior context can become noisy if too many nodes are loaded. Mitigation:
  preserve the current prior-context limit and validate with the two-run loop.

## Follow-up candidates

- Add a reviewer view for choosing which prior nodes should influence a brief.

