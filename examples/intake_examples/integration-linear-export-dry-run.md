# Integration Intake Example: Linear Export Dry Run

**Idea shape:** Integration

**M1 source:** `README.md`, `examples/validate_linear_export.py`, and
`tests/test_export_cli.py` exercise the export path from a generated Markdown
ticket into a Linear issue payload.

## Raw Intake

```text
Validate an export-ready ticket payload before creating a Linear issue
```

## Research Summary

- `docs/symphony-ready-ticket-schema.md`: Exported tickets must keep required
  sections in canonical order with validation, evidence, and graph provenance.
- `examples/overture_mvp_linear_issue_draft.md`: The repository already keeps a
  representative Symphony-ready ticket draft for export validation.
- `tests/test_export_cli.py`: Dry-run export validates payload shape without
  requiring Linear credentials or creating a remote issue.

## Brief

### Problem

Linear export is the handoff boundary between Overture and external issue
tracking. A malformed payload can turn a good intake and brief into a bad
implementation ticket.

### User Need

Operators need a credential-free dry run that validates the generated Markdown
ticket before any Linear issue is created.

### Relevant Evidence

- The README documents `python -m overture export ... --dry-run`.
- The export CLI tests assert malformed tickets fail and valid generated
  fixtures pass.
- The ticket schema document defines the sections export should protect.

### Candidate Ticket Breakdown

- **Title:** Validate Linear export dry run
- **Readiness:** Ready
- **Scope:** Keep dry-run export validation available for generated ticket
  Markdown and report the Linear payload that would be created.
- **Validation plan:** Run the export dry-run example and the export CLI tests.

## Ticket

# Validate Linear export dry run

## Context

Overture produces Symphony-ready Markdown tickets, but Linear creation is an
external integration boundary. M1 validation uses dry-run export to prove a
ticket payload is valid before it reaches Linear.

## Problem

Without a dry-run validation path, malformed ticket Markdown can become a Linear
issue or force operators to rely on credentials just to check payload shape.

## Proposed change

Validate export-ready Markdown through the existing export command before
creating a Linear issue, and keep dry-run output focused on the title and
payload that would be sent.

## Acceptance criteria

- [ ] Dry-run export accepts a valid generated ticket fixture.
- [ ] Dry-run export rejects malformed ticket Markdown with a clear error.
- [ ] Dry-run export does not require `LINEAR_API_KEY`.

## Validation plan

- Run `python examples/validate_linear_export.py`.
- Run `python -m unittest tests.test_export_cli`.
- Run `python -m unittest discover -s tests`.

## Sources / evidence

- `README.md`: Manual workflow for export dry run.
- `examples/validate_linear_export.py`: Export validation example.
- `tests/test_export_cli.py`: Export CLI behavior and error handling.
- `examples/overture_mvp_linear_issue_draft.md`: Valid generated ticket input.

## Graph provenance

- Nodes: `userinput_validate_linear_export`, `capability_ticket_draft`,
  `capability_linear_export`, `constraint_dry_run_without_credentials`,
  `ticketcandidate_validate_linear_export`.
- Edges: `userinput_validate_linear_export -> exercises ->
  capability_ticket_draft`; `capability_ticket_draft -> feeds ->
  capability_linear_export`; `constraint_dry_run_without_credentials ->
  constrains -> capability_linear_export`; `capability_linear_export ->
  suggests -> ticketcandidate_validate_linear_export`.
- Confidence: high.
- Conflicts: None.

## Dependencies

- Existing export CLI and ticket schema validation.

## Out of scope

- Do not create a real Linear issue during dry-run validation.
- Do not change Linear authentication behavior.

## Risk / uncertainty

- Dry-run output can drift from real create payloads. Mitigation: keep dry-run
  and create paths sharing the same payload validation code.

## Follow-up candidates

- Add a fixture that snapshots the exact Linear payload body.

