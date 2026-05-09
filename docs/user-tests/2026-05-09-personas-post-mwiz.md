# Persona re-test report (Post-MWIZ) — 2026-05-09

## Executive summary

This report consolidates:

- baseline run `docs/user-tests/2026-05-07-personas.md`
- follow-up with Codex real `docs/user-tests/2026-05-08-personas-with-codex.md`
- fresh MWIZ retests in:
  - `/tmp/m-wiz-test-carla.md`
  - `/tmp/m-wiz-test-tomas.md`
  - `/tmp/m-wiz-test-rocio.md`

Headline metric:

- **0 of 3 personas completed idea→ticket via wizard without manual session repair or cookie replay artifacts.**

## Baseline comparison table

| Baseline finding | Severity | Baseline description | Post-MWIZ status | Evidence / notes |
|---|---|---|---|---|
| #1 | Medium | Login to `/intake` requires magic-link path | Residual | Post-runs still use magic-link with no skip path.
| #2 | Low | Developer jargon in “Development outbox” and “magic-links.jsonl” copy | Residual | Still reported in baseline and Tomás/Rocío narratives; not addressed in MWIZ run traces.
| #3 | High | Codex absence requires manual server restart workaround | Closed | `2026-05-08-personas-with-codex.md` shows all three personas progress with real Codex.
| #4 | Medium | Pre-approval sources are already checked | Residual (Carryover) | `/tmp/m-wiz-test-carla.md` still records this behavior in pre-fix carryover; later files do not complete fully.
| #5 | Medium | Placeholder example URLs are accepted | Closed | `2026-05-08...` confirms 5 inspectable real sources for each persona.
| #6 | Medium | `/research/complete` missing forward action | Residual | In new MWIZ traces, this remains a brittle hop; some runs break before reaching/using it.
| #7 | Medium | Synthesis brief stays templated/incomplete | Residual (partially unverified) | Not revalidated end-to-end because one path blocks earlier; Tomás/Rocío traces still show placeholder-like quality concerns.
| #8 | Low | Candidate ticket title truncation | Residual (partially unverified) | Not confirmed as fixed in MWIZ traces.
| #9 | Critical | `/ticket` is placeholder and cannot generate draft | Residual | Tomás and Rocío traces route through `/ticket`; additional blockers occur before reliable completion.
| #10 | High | Peer onboarding is read-only for `Designer #1` | Residual | No evidence of editable peer-onboarding path in MWIZ runs.
| #11 | Critical | Semi-technical user cannot activate Codex workaround | Closed | Codex real + automatic fallback removed this hard stop.
| #12 | High | Non-graceful degradation when research fails | Residual | New session-loss bug prevents reliable continuation even after Codex success.
| #13 | Low | “Placeholder for …” empty states appear in Synthesis/Ticket | Residual | Placeholder text is less visible in `2026-05-08`, but functional blockers remain around session state.
| #14 | Medium | “Designer sign in” and “designer idea” copy blocks founder persona | Residual | Founders still inherit designer-centric framing in baseline and not explicitly retested cleanly.
| #15 | High | Founder-facing magic-link terminology is technical | Residual | New traces show founders can reach flows, but copy still not creator-language-friendly.
| #16 | Critical | Codex error is inactionable for non-technical users | Closed | Fixed alongside #3 in Codex-real verification.
| #17 | High | “Ticket Markdown” field language assumes Markdown competency | Residual | Not retested as success path is blocked; no new wording evidence.
| #18 | Medium | Idea hash in URL creates trust gap | Residual | Still unresolved in MWIZ traces; no evidence hash removal was introduced.

### New findings introduced post-MWIZ

| New finding | Severity | Description |
|---|---|---|
| A | P0 | `/research/approval` loses `intake_id` in session state; GET can render approval but POST returns `400 No intake is stored in this session` for Carla path and unstable behavior for others.
| B | P1 | `/synthesis -> /ticket` transition is non-deterministic and can redirect back to `/synthesis` unless cookie replay state is preserved exactly.

## Persona section: Carla (source `/tmp/m-wiz-test-carla.md`)

```text
### Run metadata
- Executed: 2026-05-09T03:54:00.227530+00:00
- Persona: Carla (Designer #1)
- Base URL: http://127.0.0.1:8765
- Store directory: /tmp/overture-mwiz-test-carla
- LLM client: overture.research_llm.codex_cli_client
- Canonical cookie policy: `overture_auth` + `overture_session`
```

```text
### Step-by-step execution with accessibility snapshots

1. /auth/login
- Method: GET
- HTTP: 200 OK
- Note: open wizard sign-in

2. /auth/magic-link
- Method: POST
- HTTP: 200 OK
- Note: submit email

3. /auth/consume
- Method: GET
- HTTP: 200 OK
- Note: consume magic link

4. /intake
- Method: GET
- HTTP: 200 OK
- Note: open intake form

5. /intake
- Method: POST
- HTTP: 303 See Other
- Note: submit idea

6. /research/approval
- Method: GET
- HTTP: 400 Bad Request
- Note: load research approval for the persisted idea
- Validation message: No intake is stored in this session. Return to intake before approving research sources.

7. /research/approval
- Method: POST
- HTTP: 400 Bad Request
- Note: submit source approvals
- Validation message: No intake is stored in this session.
```

Friction log in this run:

- P0: session context loses `intake_id` between `/intake` POST and `/research/approval` state.
- P1: save flow never advances to synthesis in normal cookie handling.

Outcome:

- Carla remained blocked at research approval under this MWIZ pass.

## Persona section: Tomás (source `/tmp/m-wiz-test-tomas.md`)

```text
## Test — Tomás persona wizard run — localhost:8766 (ERI-104 follow-up)
- Persona: Tomás (Designer #2, semi-technical)
- Store dir: `/tmp/overture-test-tomas`
```

```text
### Transition log

1) /intake GET
- Result: 200 (login challenge handled through magic link)

2) /auth/magic-link POST + /auth/consume
- Result: magic-link path worked, auth cookie set

3) /intake POST
- Result: 303 -> /research/approval

4) /research/approval GET + POST (one source approved)
- Result: 200 approval page, then 303 -> /research/complete

5) /synthesis GET + POST
- Result: 200 synthesis brief displayed, POST returns 303 -> /ticket

6) /ticket
- Result: normal browser-cookie replay path redirected 303 -> /synthesis
- Replay with exact Set-Cookie from /synthesis could reach /ticket in harness.

7) /ticket POST + /export
- Result: valid ticket markdown extracted; export page rendered with dry-run/export actions using replayed session state.
```

Friction log in this run:

- Medium: `/ticket` route gating loses synthesis context under standard cookie replay semantics.
- Medium: ticket submission requires careful form payload + replayed cookie to succeed.

Acceptance status:

- Tomás did not complete a reliable end-to-end idea→ticket path under a normal browser session.

## Persona section: Rocío (source `/tmp/m-wiz-test-rocio.md`)

```text
## Rocío persona validation (ERI-105)
- Persona: Rocío (non-technical founder)
- Target: `http://localhost:8767`
- Idea: Send a weekly digest email to onboarded users
- Run artifact directory: `/tmp/rocio-wizard-evidence`
```

```text
### Evidence trace (full)

1) Intake launch/redirect
2) Magic-link request
3) Magic link consumed
4) Intake / research routing entry
5) Research approval
6) Research complete
7) Synthesis
8) Ticket review
9) Ticket submission / export gate
10) Export review
11) Export dry-run
12) Flow capture log and cookies
```

Friction log in this run:

- High: browser automation path intermittently loops `/synthesis -> /ticket` due session encoding differences.
- Low: no blocking copy issue for this particular run’s rendered ticket/export outputs.

Acceptance status:

- Automation evidence reaches ticket/export under replay-like conditions.

## Residuals (P1/P2 carryover and new)

P1/P2 findings that remain open for the next milestone:

- #4 Pre-approve source selection.
- #6 `/research/complete` flow friction.
- #7 Synthesis brief quality/templated concerns.
- #8 Candidate ticket title truncation.
- #10 Peer onboarding editing path.
- #12 Graceful degradation between wizard steps.
- #14 / #15 Designer-centric copy for non-designers.
- #17 Ticket Markdown naming and founder readability.
- #18 Hash-like visible idea identity representation.
- New P0: `/research/approval` session-loss / intake-id drop.
- New P1: `/synthesis -> /ticket` non-determinism under normal cookie handling.

## Reproduction

Run the following commands for the same artifacts used in this report.

```sh
# Baseline files
ls docs/user-tests | rg "2026-05-(07|08)-personas|personas"

# MWIZ source runs
ls /tmp/m-wiz-test-*.md

# Build/verify that report exists
mkdir -p docs/user-tests
cat docs/user-tests/2026-05-09-personas-post-mwiz.md
python -m unittest discover -s tests
```

Additional exact MWIZ flow checks:

```sh
# Carla
python - <<'PY'
from pathlib import Path
print(Path('/tmp/m-wiz-test-carla.md').read_text())
PY

# Tomás
python - <<'PY'
from pathlib import Path
print(Path('/tmp/m-wiz-test-tomas.md').read_text())
PY

# Rocío
python - <<'PY'
from pathlib import Path
print(Path('/tmp/m-wiz-test-rocio.md').read_text())
PY
```

## Verification checklist used for this report

- `test -f docs/user-tests/2026-05-09-personas-post-mwiz.md`
- `rg "\|" docs/user-tests/2026-05-09-personas-post-mwiz.md`
- `python -m unittest discover -s tests`
