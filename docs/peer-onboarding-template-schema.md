# Peer Onboarding Template Schema

The peer onboarding template has one active schema version:
`2026-05-07`. It now supports a second-generation handoff so Designer #1 and
Designer #2 can transfer session knowledge to Designer #3 without turning the
artifact into a separate editing product.

## Top-level object

- `schema_version`: string. Current value is `2026-05-07`.
- `author`: structured object with `id` and `email` strings for the template
  author.
- `sections`: ordered list of section objects. Viewers sort by `order` and
  tolerate extra future sections.

## Sections

1. `intake_worked`: "What intake worked"
   - `summary`: free text.
   - `example_prompts`: list of free-text prompts.
2. `research_approval`: "What research approval looked like"
   - `approval_summary`: free text.
   - `approved_source_traits`: list of free-text traits.
3. `wizard_watchouts`: "What to watch out for at each wizard step"
   - `step_notes`: structured list of `{step, note}` objects for Intake,
     Research, Synthesis, Ticket, and Export.
4. `sprint5_observation_patterns`: "Sprint 5 observation patterns to carry forward"
   - `pattern_summary`: free text grounded in `component_observation_log`.
   - `handoff_adjustments`: list of concrete changes for Designer #3, grounded
     in `component_observation_log`.

All fields are optional in the first iteration. Empty templates initialize
string fields as `""`, list fields as `[]`, and wizard step notes as one empty
note object per wizard step.

## Generations

- Generation 1 is Designer #1's original filled artifact for Designer #2.
- Generation 2 is Designer #1 and Designer #2's jointly authored filled
  artifact for Designer #3. It instantiates `component_peer_template_v2`,
  references the original artifact, and cites `component_observation_log` for
  Sprint 5 friction patterns.
- The viewer route renders the newest generation by default and includes an
  available-generations list so first-generation and second-generation artifacts
  remain distinguishable.
