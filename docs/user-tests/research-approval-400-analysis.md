# Research approval session-loss analysis (ERI-86)

## Summary

`POST /research/approval` returns `HTTP 400 Bad Request` with error
`No suggested sources are available for this intake.` because the active session cookie is too large for browser storage.

## Reproduction signal (from harness)

`tests/test_research_approval_session.py` reproduces this deterministically with a browser-like 4KB cookie limit.

- Command:
  ```sh
  python -m unittest tests.test_research_approval_session.ResearchApprovalSessionReproTests.test_browser_like_cookie_storage_reproduces_research_approval_400
  ```
- Observed GET path:
  - `POST /intake` then `GET /research/approval` returns `200`.
  - Candidate data are generated and stored in session state under
    `SESSION_CANDIDATES_KEY`.
- Observed POST path:
  - `POST /research/approval` returns `400` with
    `No suggested sources are available for this intake.`
  - Evidence body still contains only `decision-0=approve%3Ahttps%3A%2F%2Fexample.test%2Fsource-0` from the submitted form.

### Raw cookie/session evidence from harness

From `BrowserLikeClient` signal and test assertions:

- Response to `GET /research/approval` includes `Set-Cookie` header `overture_session=...` of **21,636 bytes** (captured in `rejected_cookie_sizes`).
- `BrowserLikeClient` enforces browser limit `4096` bytes; it records
  `rejected_cookie_sizes['overture_session'] = 21636`, so that cookie does **not** survive into stored browser cookie state.
- After POST, client cookie state still has `overture_session` and `overture_auth`, but
  does **not** include key `research_candidates`.
- Harness assertion confirms:
  - `self.assertNotIn("research_candidates", evidence.cookie_state[SESSION_COOKIE_NAME])`
  - `self.assertIn("No suggested sources are available for this intake.", evidence.response_body)`

This maps directly to the bug shape: candidates are no longer present in session state when handling
`_handle_research_post`.

## Hypothesis elimination

1. **Cookie scope / SameSite mismatch**

Rejected: both auth and session cookies are emitted with `Path=/`, `HttpOnly`, and `SameSite=Lax` (`_session_cookie`, `_opaque_session_cookie`).
The failure happens as a same-site form POST on the same path, and replayed navigation in the harness succeeds for auth and intake flows even after the regression.

2. **In-memory session backend loss between requests**

Rejected: route uses `_server_session(environ, user)` based on cookie/session id and `SessionStore`.
The server-side path is consistent per request and does not create a new session between GET and POST for the same browser cookie identity.
The regression is specifically that the browser never retains the oversized cookie payload, so the serialized session data is already missing before request handling.

3. **CSRF / anti-replay invalidation**

Rejected: there is no CSRF token or anti-replay layer in `overture/ui_host.py` around `/research/approval` POST handling. No code path rejects POSTs on token mismatch.
The error path is purely derived from missing `research_candidates` in session (`submit_research_approvals`).

## Root-cause mechanism

### Why candidates are lost

- Candidate list is stored on every response by writing session JSON through
  `_store_session_candidates` and sent to the client by `_session_cookie`.
- `_store_session_candidates` adds a `research_candidates` blob keyed by `intake_id` into the session map, then `_session_cookie` JSON-serializes the entire session into a single `Set-Cookie` value.
- For realistic candidate payloads, that serialized value exceeds common browser cookie limits.
- The harness marks this cookie as rejected (`21636 > 4096`), so the client cannot keep the full session.
- On POST, `submit_research_approvals` reads session from `session_from_environ`:
  - candidates are loaded via `_session_candidates`.
  - with `research_candidates` absent, `candidates == ()`, so it returns `ResearchReviewResult(..., error="No suggested sources are available for this intake.")`.

### Exact current failure location

- `overture/ui_host.py`
- `_handle_research_post` → `submit_research_approvals`
- `submit_research_approvals` relies on `_session_candidates(session, intake_id)` and returns 400 when this is empty.
- `prepare_research_review` + `_store_session_candidates` are where the large payload is introduced.

## Recommended fix shape for Ticket 3

Move transient approval payloads out of cookie payloads into server-side session data.

- Keep `overture_session` as a small opaque/session-id cookie (or minimal metadata only).
- Persist `research_candidates` (and ideally approvals) in server-side session storage keyed by session id + user in `SessionStore` (or equivalent store), rather than inline in the cookie.
- Ensure `/research/approval` GET and POST both read/write through that server-side map via `get_or_create` / `_store_session_*` helpers.

## Suggested implementation guardrails for Ticket 3

- Verify `Cookie` size for `overture_session` is bounded after review page render.
- Add/extend tests around candidate-loss scenario using `tests/test_research_approval_session.py`.
- Confirm POST flow remains 303 and writes `research/<id>.json`.
