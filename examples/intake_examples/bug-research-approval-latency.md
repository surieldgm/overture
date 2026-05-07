# Bug Intake Example: Research Approval Latency

**Idea shape:** Bug / friction

**M1 source:** `tests/test_friction_cli.py` records the confirmed M1 friction
entry and seeds it back into intake as real operator feedback.

## Raw Intake

```text
Confirmed operator friction [slow] in session m1 run run-1: research approval took too long
```

## Research Summary

- `tests/test_friction_cli.py`: Confirmed friction entries are converted into
  backlog intake records with `source_type` set to `friction`.
- `README.md`: The research step can prompt the operator for manual approval of
  each suggested source.
- M1 dogfooding signal: approval latency was recorded as slow enough to merit a
  confirmed follow-up intake.

## Brief

### Problem

Manual source approval can take long enough that the operator loses momentum
and context before the ticket draft exists.

### User Need

Designers need the research approval step to keep decisions fast and explicit
without weakening the requirement that approved sources are inspected.

### Relevant Evidence

- The confirmed M1 friction note says research approval took too long.
- The CLI docs describe manual approval as part of the research path.
- The backlog seeding path preserves confirmed friction as intake material so it
  can become implementation work.

### Candidate Ticket Breakdown

- **Title:** Fix research approval latency
- **Readiness:** Ready
- **Scope:** Reduce operator wait time in the approval step while preserving
  explicit source approval.
- **Validation plan:** Seed the confirmed friction entry, run the research path,
  and verify the improved approval behavior remains visible and testable.

## Ticket

# Fix research approval latency

## Context

During M1 dogfooding, the operator recorded confirmed slow-path friction:
`research approval took too long`. The same friction system can turn confirmed
operator notes back into Overture intake records.

## Problem

When research approval feels slow, designers may approve sources mechanically or
abandon the intake before the brief and ticket can demonstrate value.

## Proposed change

Streamline the research approval interaction so each candidate source has a
clear decision path, minimal repeated waiting, and enough context for a fast
approve, skip, or reject choice.

## Acceptance criteria

- [ ] Confirmed slow research-approval friction can be seeded into an intake.
- [ ] The research approval prompt presents each source decision clearly.
- [ ] The approval path keeps approved-source provenance in the research output.

## Validation plan

- Run `python -m unittest tests.test_friction_cli`.
- Run the documented fake-client research command and confirm research JSON is
  still written after approval decisions.
- Run `python -m unittest discover -s tests`.

## Sources / evidence

- `tests/test_friction_cli.py`: Confirmed M1 friction and backlog intake
  seeding.
- `README.md`: Manual and fake-client research approval workflow.
- `overture/backlog_seeder.py`: Confirmed friction to intake conversion.

## Graph provenance

- Nodes: `m1_friction_research_approval_slow`,
  `userinput_research_approval_latency`, `need_fast_source_approval`,
  `capability_research_approval`, `ticketcandidate_fix_research_latency`.
- Edges: `m1_friction_research_approval_slow -> seeds ->
  userinput_research_approval_latency`; `userinput_research_approval_latency ->
  expresses -> need_fast_source_approval`; `need_fast_source_approval ->
  constrains -> capability_research_approval`; `capability_research_approval ->
  suggests -> ticketcandidate_fix_research_latency`.
- Confidence: high.
- Conflicts: None.

## Dependencies

- Existing research approval CLI behavior.

## Out of scope

- Do not remove manual source approval.
- Do not introduce an LLM-only approval bypass.

## Risk / uncertainty

- Faster prompts could hide source quality details. Mitigation: preserve source
  title, URL, and summary at the decision point.

## Follow-up candidates

- Add approval timing metrics by source candidate.

