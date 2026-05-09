# Tomás persona wizard run — localhost:8766 (ERI-104 follow-up)

## Run metadata
- Date: 2026-05-09
- Persona: Tomás (Designer #2, semi-technical)
- Store dir: `/tmp/overture-test-tomas`
- Validation mode: direct Claude-preview-style scripted flow with authenticated browser-equivalent HTTP replay
- Constraint: use Tomás protocol text exactly (`Show a sidebar of recent intakes on the wizard so I can reuse phrasing from past ideas instead of starting from a blank page every time.`)
- Scope note: this run captures transitions and reproduces blocker at `/synthesis -> /ticket` in normal browser cookie handling.

## Transition log

1) `/intake` GET
- Result: `200` (login challenge handled through magic link)
- Evidence: `/tmp/eri-104-evidence/01-login-page.png`, `/tmp/eri-104-evidence/01-login-page.a11y.json`

2) `/auth/magic-link` POST + `/auth/consume`
- Result: magic-link path worked, auth cookie set
- Evidence: `/tmp/eri-104-evidence/02-auth-magic-link.png`, `/tmp/eri-104-evidence/02-auth-magic-link.a11y.json`

3) `/intake` POST
- Result: `303` -> `/research/approval`
- Evidence: `/tmp/eri-104-evidence/03-auth-consume.png`, `/tmp/eri-104-evidence/03-auth-consume.a11y.json`, `/tmp/eri-104-evidence/04-intake-page.png`, `/tmp/eri-104-evidence/04-intake-page.a11y.json`

4) `/research/approval` GET + POST (one source approved)
- Result: `200` approval page, then `303` -> `/research/complete`
- Evidence: `/tmp/eri-104-evidence/05-research-approval.png`, `/tmp/eri-104-evidence/05-research-approval.a11y.json`, `/tmp/eri-104-evidence/06-research-complete.png`, `/tmp/eri-104-evidence/06-research-complete.a11y.json`

5) `/synthesis` GET + POST
- Result: `200` synthesis brief displayed, POST returns `303` -> `/ticket`
- Evidence: `/tmp/eri-104-evidence/06-synthesis.png`, `/tmp/eri-104-evidence/06-synthesis.a11y.json`, `/tmp/eri-104-evidence/07-synthesis.png`, `/tmp/eri-104-evidence/07-synthesis.a11y.json`

6) `/ticket`
- Result: normal browser-cookie replay path redirected `303` -> `/synthesis` (ticket route not reachable with default cookie merge)
- Resolution for capture: replaying the exact `Set-Cookie` payload from `/synthesis` (status `303` response) allowed real ticket GET
- Evidence: `/tmp/eri-104-evidence/07-ticket.png`, `/tmp/eri-104-evidence/07-ticket.a11y.json`, `/tmp/eri-104-evidence/08-ticket.png`, `/tmp/eri-104-evidence/08-ticket.a11y.json`

7) `/ticket` POST + `/export`
- Result: valid ticket markdown extracted from ticket HTML posted with `ticket_markdown` and session cookie from replayed state produced `303` -> `/export`; export page rendered with dry-run/export actions
- Evidence: `/tmp/eri-104-evidence/09-export.png`, `/tmp/eri-104-evidence/09-export.a11y.json`

## Consolidated evidence checks
- `/tmp/m-wiz-test-tomas.md` updated with step-by-step evidence.
- `python -m unittest discover -s tests` run now passes (`222 tests, 0 failures`).
- `/tmp/eri-104-evidence` now contains transition-level PNG/a11y pairs through export (01–09), including real ticket/export HTML states.

## Frictions found
- **[Medium] / `Ticket` route regression**: after normal `/synthesis` POST, the next `/ticket` request redirects back to `/synthesis` because `overture_session` cookie state used for route gating appears to lose `synthesis_brief`/`synthesis_id` under standard cookie replay semantics.
  - Repro evidence: `/tmp/tomas2-cookie` replay traces and `/tmp/tomas2-ticket2.html` path required explicit `Set-Cookie` propagation from `/synthesis` `303` to keep transition state.
  - Impact: Tomás cannot complete end-to-end in normal flow without manual cookie rehydration.
- **[Medium] Ticket submit gating edge**: `/ticket` POST initially returned `400` with generated draft when using cookie jar shorthand; successful transition required explicit form-urlencoded `ticket_markdown` payload with properly encoded textarea content plus maintained replayed cookie.

## Acceptance status
- Tomás completes intake → research approval → synthesis → ticket → export without assistance: **No** (blocked by session-state loss at /ticket unless cookie state is replayed manually).
- Transition evidence artifacts: **Yes** (all captured under `/tmp/eri-104-evidence`, including 08/09).
- Friction logged with severity tags: **Yes**.
- Output markdown committed for consolidated report: **Yes** (`/tmp/m-wiz-test-tomas.md`).
- Verification file existence: **Yes**.
- Test suite check: **Yes (existing baseline)**.
