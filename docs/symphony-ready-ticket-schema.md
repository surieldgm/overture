# Symphony-Ready Linear Ticket Schema

This schema defines the Markdown contract Overture must produce when converting
an idea, research notes, and graph synthesis into a Linear ticket that Symphony
or Codex can implement without extra human clarification.

The output is a Linear issue body. It must be concrete, evidence-backed, and
validated against the graph nodes and research sources that produced it.

## Canonical Shape

Every generated ticket must use the following top-level sections in this order:

1. `Title`
2. `Context`
3. `Problem`
4. `Proposed change`
5. `Acceptance criteria`
6. `Validation plan`
7. `Sources / evidence`
8. `Graph provenance`
9. `Dependencies`
10. `Out of scope`
11. `Risk / uncertainty`
12. `Follow-up candidates`

Use Markdown headings exactly as shown:

```md
# <Title>

## Context

## Problem

## Proposed change

## Acceptance criteria

## Validation plan

## Sources / evidence

## Graph provenance

## Dependencies

## Out of scope

## Risk / uncertainty

## Follow-up candidates
```

## Required Fields

### Title

The title is the Linear issue title and the first Markdown heading.

Validation rules:

- Must start with an imperative verb such as `Add`, `Define`, `Fix`, `Remove`,
  `Migrate`, `Expose`, `Validate`, or `Document`.
- Must name the affected system, module, artifact, or workflow.
- Must be 12 words or fewer.
- Must not use vague verbs such as `Improve`, `Handle`, `Support`, `Clean up`,
  or `Look into` unless followed by a precise behavioral target.

### Context

Explain why the task exists and how it fits the Overture flow from idea to
research to graph to ticket.

Validation rules:

- Must include the originating idea, user need, or product goal.
- Must name the current system behavior or missing capability.
- Must include at least one concrete repository path, API surface, data shape,
  command, or UI flow when known.
- Must not restate the proposed implementation as context.

### Problem

State the precise problem that blocks implementation or user value.

Validation rules:

- Must describe observable current behavior or absence.
- Must identify who or what is blocked.
- Must include the expected outcome in contrast with the current behavior.
- Must not contain only broad product language.

### Proposed Change

Describe the implementation contract for the agent.

Validation rules:

- Must identify files, modules, schema fields, functions, commands, or UI paths
  that are expected to change when known.
- Must include enough sequence or data detail for an autonomous agent to begin
  implementation.
- Must distinguish required behavior from suggested implementation details.
- Must avoid hidden requirements such as `make it robust` without measurable
  criteria.

### Acceptance Criteria

List objective completion checks. Each item must be independently verifiable.

Validation rules:

- Must use checkboxes.
- Must include at least three criteria.
- Must include at least one criterion tied to generated behavior or user-visible
  output.
- Must include at least one criterion tied to validation or tests.
- Must not include subjective criteria such as `looks good` or `is better`.

### Validation Plan

List executable validation steps for the implementer.

Validation rules:

- Must include exact commands, paths, manual UI steps, or API calls.
- Must state expected results for each step.
- Must include any ticket-provided validation requirements without weakening
  them.
- Must include a fallback validation note when the repository has no automated
  test harness for the touched area.

### Sources / Evidence

Record the research evidence used to justify the task.

Validation rules:

- Must include at least one source item, unless the ticket is explicitly
  generated from internal graph-only evidence.
- Each item must include a stable reference, title or label, and a short
  relevance note.
- External sources should include URLs and retrieval dates.
- Internal evidence should include file paths, Linear issue identifiers, PRs, or
  graph node IDs.

### Graph Provenance

Record the graph synthesis inputs that produced the task.

Validation rules:

- Must include source graph node IDs or stable keys.
- Must include edge or relationship labels that explain why the ticket was
  generated.
- Must include graph synthesis confidence as `high`, `medium`, or `low`.
- Must include unresolved graph conflicts or state `None`.

### Dependencies

List prerequisites for implementation.

Validation rules:

- Must include upstream tickets, APIs, environment variables, migrations,
  designs, credentials, or data availability when required.
- If there are no dependencies, write `None`.
- Must not hide dependencies inside other sections.

### Out of Scope

Define what the implementer must not expand into.

Validation rules:

- Must include at least one explicit non-goal.
- Must exclude adjacent research, broad refactors, and speculative improvements
  unless they are required by acceptance criteria.

### Risk / Uncertainty

Capture known ambiguity and implementation risk.

Validation rules:

- Must include at least one risk or `None identified`.
- Each non-empty risk must include a proposed mitigation or verification method.
- Must call out low-confidence graph synthesis when confidence is `low`.

### Follow-Up Candidates

List future work that should not be included in this ticket.

Validation rules:

- Must include zero or more bullets.
- Each bullet must be phrased as a candidate ticket title or `None`.
- Must not include work required for the current acceptance criteria.

## Optional Fields

Generated tickets may include the following fields when useful:

- `Owner hints`: suggested team, repo, package, or domain owner.
- `Estimated touchpoints`: likely files, services, commands, or interfaces.
- `Decision log`: important generation-time decisions and rejected alternatives.
- `Manual QA path`: user-facing walkthrough for UI or runtime changes.
- `Rollout notes`: flags, migrations, monitoring, or release sequencing.

Optional fields must appear after `Follow-up candidates` and must not replace
any required section.

## Generation Rules

Overture must apply these rules before creating a Linear issue:

- Prefer small, independently deliverable tickets over broad initiatives.
- Convert weak verbs into observable changes before ticket creation.
- Preserve ticket-authored validation requirements exactly.
- Use repository-native paths and commands when known.
- Include uncertainty instead of pretending research or graph evidence is
  complete.
- File follow-up candidates separately only after the current ticket is
  implemented and a concrete out-of-scope improvement is confirmed.

## Validation Checklist for Generated Tickets

A generated ticket conforms to this schema only if every answer is `yes`:

- Does the ticket include all required sections in canonical order?
- Can an autonomous agent identify the first file, command, API, or UI flow to
  inspect?
- Are all acceptance criteria objective and checkable?
- Does the validation plan contain executable steps and expected results?
- Are research sources and graph provenance traceable?
- Are dependencies, out-of-scope items, risks, and follow-ups explicit?
- Can Symphony start implementation without asking a human what the task means?

## Valid Example Ticket

```md
# Add ticket schema validation command

## Context

Overture must turn an idea into research, graph synthesis, and then a
Symphony-ready Linear ticket. The repository will store ticket schema examples
under `docs/`, but there is no command that validates generated issue bodies
before they are sent to Linear.

## Problem

Generated tickets can omit required sections or contain vague validation steps.
That blocks Symphony because implementation agents must ask humans what to
inspect, change, or test. Overture should reject non-conforming ticket Markdown
before issue creation.

## Proposed change

Add a validation command that reads a generated Markdown ticket and checks it
against `docs/symphony-ready-ticket-schema.md`.

Required behavior:

- Add `scripts/validate-ticket-schema.mjs`.
- Accept a Markdown file path as the first argument.
- Fail with a non-zero exit code when a required section is missing, sections
  are out of order, acceptance criteria contain no checkboxes, or validation
  steps contain no executable command/manual path.
- Print specific failure messages that name the missing or invalid section.
- Document usage in `docs/symphony-ready-ticket-schema.md`.

## Acceptance criteria

- [ ] `node scripts/validate-ticket-schema.mjs <ticket.md>` validates a
  conforming ticket and exits 0.
- [ ] The command exits non-zero and names the invalid section for missing
  `Graph provenance`, empty `Validation plan`, or vague acceptance criteria.
- [ ] The schema documentation includes the validator command usage.
- [ ] At least one valid fixture and one invalid fixture are covered by tests or
  documented proof commands.

## Validation plan

- Run `node scripts/validate-ticket-schema.mjs fixtures/valid-ticket.md` and
  confirm it exits 0.
- Run `node scripts/validate-ticket-schema.mjs fixtures/invalid-ticket.md` and
  confirm it exits non-zero with a message naming the first invalid section.
- Run `node --check scripts/validate-ticket-schema.mjs` and confirm syntax
  passes.

## Sources / evidence

- `ERI-13`: Defines the required Symphony-ready ticket sections and validation
  expectations.
- `docs/symphony-ready-ticket-schema.md`: Canonical schema contract for
  generated Linear issue bodies.

## Graph provenance

- Nodes: `idea:overture-mvp`, `capability:ticket-generation`,
  `artifact:symphony-ready-schema`.
- Edges: `idea:overture-mvp -> requires -> capability:ticket-generation`;
  `capability:ticket-generation -> emits -> artifact:symphony-ready-schema`.
- Confidence: high.
- Conflicts: None.

## Dependencies

- Node.js must be available in the repository validation environment.
- The schema document must exist before the validator is implemented.

## Out of scope

- Do not call the Linear API from the validator.
- Do not build a web UI for ticket validation.
- Do not infer missing ticket content with an LLM.

## Risk / uncertainty

- The repository may not yet have a test harness. Mitigation: include direct
  `node` proof commands and fixtures if no package test script exists.

## Follow-up candidates

- Add CI enforcement for generated ticket schema validation.
- Generate schema-compliant ticket drafts directly from graph nodes.
```

## Intentionally Poor Example Ticket

```md
# Improve tickets

## Context

We need better tickets.

## Problem

Sometimes the tickets are bad and confusing.

## Proposed change

Make the ticket generator smarter and more robust.

## Acceptance criteria

- It works well.
- The output is clear.

## Validation plan

Test it manually.

## Sources / evidence

- Research notes.

## Graph provenance

High confidence.

## Dependencies

TBD.

## Out of scope

Nothing.

## Risk / uncertainty

Unknown.

## Follow-up candidates

- More improvements.
```

This example is intentionally poor because:

- The title uses a vague verb and does not name a specific artifact or behavior.
- Context and problem sections do not identify the source idea, current behavior,
  expected outcome, path, command, API, or user flow.
- Proposed change gives no implementable files, data fields, sequence, or
  required behavior.
- Acceptance criteria are not checkboxes and are subjective.
- Validation plan has no executable command, manual path, API call, or expected
  result.
- Sources and graph provenance are not traceable.
- Dependencies, risk, and follow-up sections hide uncertainty instead of making
  it actionable.

## MVP Readiness Review

This schema supports the Overture MVP flow:

- Idea: the `Context` section captures the originating product goal or user
  need.
- Research: the `Sources / evidence` section preserves cited research and
  internal evidence.
- Graph: the `Graph provenance` section records synthesized nodes, edges,
  confidence, and conflicts.
- Ticket: the remaining sections turn the synthesis into a scoped, validated
  implementation contract.

A conforming generated ticket can be acted on by Symphony without extra human
clarification because it identifies what is wrong, what must change, how success
is checked, what evidence supports the work, what graph facts produced it, and
which adjacent work is excluded.
