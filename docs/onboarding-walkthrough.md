# First-Time Operator Walkthrough

Use this walkthrough when you have an idea and need to turn it into a reviewed
Linear ticket draft without founder context. Run every command from the
repository root. The generated files stay under `/tmp/overture-onboarding`, so
the repository stays clean.

For inspiration before writing your own idea, skim the curated examples library:

- [Curated intake examples](../examples/intake_examples/README.md)

## 1. Setup

Command:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Expected output shape:

```text
Obtaining file:///.../overture
...
Successfully installed overture-0.1.0
```

What just happened:

You created a local Python environment and installed the Overture command line
tool from this checkout. After this step, `python -m overture ...` runs the same
code that the tests use.

## 2. Intake

Command:

```sh
python -m overture intake "Turn signup feedback into a polished Linear ticket" --store-dir /tmp/overture-onboarding/intake
```

Expected output shape:

```text
/tmp/overture-onboarding/intake/idea_<hash>.json
idea_<hash>
```

What just happened:

Overture saved your raw idea as an intake record. The first line is the JSON
file path. The second line is the intake ID; keep it for the research approval
step.

## 3. Research Approval

Command:

```sh
OVERTURE_LLM_CLIENT=fake python -m overture research <intake-id> --store-dir /tmp/overture-onboarding
```

Expected output shape:

```text
Title: <suggested source title>
URL: <suggested source URL>
Summary: <plain-language source summary>
Approve source? [y/n/s]:

Title: <suggested source title>
URL: <suggested source URL>
Summary: <plain-language source summary>
Approve source? [y/n/s]:

/tmp/overture-onboarding/research/<intake-id>.json
```

What just happened:

Overture suggested research sources for your intake. Type `y` for sources you
have inspected and want to approve, or `s` to skip a source. The final line is
the research JSON file that stores the approved source summaries and claims.

If the step fails or you skipped every source, run setup again and rerun this
step.

## 4. Brief Review

Command:

```sh
python -m overture run "Turn signup feedback into a polished Linear ticket" --output-dir /tmp/overture-onboarding/run --stop-at-stage synthesis --quiet-progress
```

Expected output shape:

```text
/tmp/overture-onboarding/run/synthesis/synthesis-brief.json
```

Command:

```sh
sed -n '1,120p' /tmp/overture-onboarding/run/synthesis/synthesis-brief.json
```

Expected output shape:

```json
{
  "candidate_ticket_breakdown": [
    {
      "id": "ticketcandidate_<id>",
      "readiness": "ready",
      "scope": "...",
      "source_node_ids": ["..."],
      "title": "...",
      "validation_plan": ["..."]
    }
  ],
  "connected_concepts": [...],
  "open_questions": [...]
}
```

What just happened:

Overture ran the pipeline through synthesis and stopped before writing the final
ticket draft. Review the `candidate_ticket_breakdown`, `connected_concepts`, and
`open_questions` fields. Those names match the ticket review vocabulary used by
the CLI and generated Symphony-ready ticket.

If the brief does not match the idea you meant to submit, rerun the intake step
with a clearer idea sentence and then rerun this step.

## 5. Ticket Review

Command:

```sh
python -m overture run "Turn signup feedback into a polished Linear ticket" --output-dir /tmp/overture-onboarding/final --quiet-progress
```

Expected output shape:

```text
/tmp/overture-onboarding/final/ticket/symphony-ticket-draft.md
```

Command:

```sh
sed -n '1,180p' /tmp/overture-onboarding/final/ticket/symphony-ticket-draft.md
```

Expected output shape:

```md
# <ticket title>

## Context
...

## Problem
...

## Proposed change
...

## Acceptance criteria
- [ ] ...

## Validation plan
- ...

## Sources / evidence
- ...

## Graph provenance
- Nodes: ...
- Edges: ...
```

What just happened:

Overture wrote a Symphony-ready ticket draft. Review the title, acceptance
criteria, validation plan, sources / evidence, and graph provenance before
exporting. These are the fields Symphony expects when it turns a Linear ticket
into implementation work.

If the draft is not ready, revise the idea sentence and rerun the intake,
research approval, and review steps.

## 6. Export

Command:

```sh
python -m overture export /tmp/overture-onboarding/final/ticket/symphony-ticket-draft.md --team-id <linear-team-id> --dry-run
```

Expected output shape:

```text
would create: title=<ticket title>
## Context
...
## Problem
...
## Proposed change
...
## Acceptance criteria
...
```

What just happened:

The dry run validated the ticket draft and printed the Linear issue payload
without creating a Linear issue. When the payload looks right and you have a
real Linear team ID plus `LINEAR_API_KEY`, remove `--dry-run` to create the
Linear ticket.

If export fails, run setup again and rerun this step.
