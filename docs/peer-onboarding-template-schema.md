# Peer Onboarding Template Schema

The peer onboarding template has one active schema version:
`2026-05-07`. It is intentionally minimal so Designer #1 can transfer
session knowledge to Designer #2 without turning the artifact into a separate
editing product.

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

All fields are optional in the first iteration. Empty templates initialize
string fields as `""`, list fields as `[]`, and wizard step notes as one empty
note object per wizard step.
