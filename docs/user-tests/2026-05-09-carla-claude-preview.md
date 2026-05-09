# ERI-103 — Carla persona run (fresh server)

## Run metadata
- Executed: 2026-05-09T03:54:00.227530+00:00
- Persona: Carla (Designer #1)
- Base URL: http://127.0.0.1:8765
- Store directory: /tmp/overture-mwiz-test-carla
- LLM client: overture.research_llm.codex_cli_client
- Canonical cookie policy: `overture_auth` + `overture_session`

## Step-by-step execution with accessibility snapshots
### Step 1: /auth/login
- Method: GET
- HTTP: 200 OK
- Note: open wizard sign-in
- Cookies before: `{}`
- Set-Cookie response: (none)
- Title: Sign in to Overture - Overture
- Headings: Overture Wizard, Sign in to Overture
- Inputs: email, viewport
- Buttons: Send magic link
- Aria labels: Breadcrumbs, Wizard steps, page
- Validation messages: (none)
- Accessibility snapshot: title=Sign in to Overture - Overture | headings=['Overture Wizard', 'Sign in to Overture'] | inputs=['email', 'viewport'] | buttons=['Send magic link'] | aria=['Breadcrumbs', 'Wizard steps', 'page']
- Snapshot file: `/tmp/m-wiz-test-carla-snapshots/step-01.json`

### Step 2: /auth/magic-link
- Method: POST
- HTTP: 200 OK
- Note: submit email
- Cookies before: `{}`
- Set-Cookie response: (none)
- Title: Magic link sent - Overture
- Headings: Overture Wizard, Magic link sent
- Inputs: viewport
- Buttons: (none)
- Aria labels: Breadcrumbs, Wizard steps, page
- Validation messages: (none)
- Accessibility snapshot: title=Magic link sent - Overture | headings=['Overture Wizard', 'Magic link sent'] | inputs=['viewport'] | buttons=[] | aria=['Breadcrumbs', 'Wizard steps', 'page']
- Snapshot file: `/tmp/m-wiz-test-carla-snapshots/step-02.json`

### Step 3: /auth/consume
- Method: GET
- HTTP: 200 OK
- Note: consume magic link
- Cookies before: `{"overture_auth": "eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJ5V21JSkd1Zk5YZHo5aGFwIiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.qxuu15L8UK1J-y-s3pv5ibHIEMZJ15_FBAvrZvubWU0"}`
- Set-Cookie response: overture_auth=eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJ5V21JSkd1Zk5YZHo5aGFwIiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.qxuu15L8UK1J-y-s3pv5ibHIEMZJ15_FBAvrZvubWU0; HttpOnly; Max-Age=28800; Path=/; SameSite=Lax
- Title: Sign in confirmed - Overture
- Headings: Overture Wizard, Sign in confirmed
- Inputs: viewport
- Buttons: (none)
- Aria labels: Breadcrumbs, Wizard steps, page
- Validation messages: (none)
- Accessibility snapshot: title=Sign in confirmed - Overture | headings=['Overture Wizard', 'Sign in confirmed'] | inputs=['viewport'] | buttons=[] | aria=['Breadcrumbs', 'Wizard steps', 'page']
- Snapshot file: `/tmp/m-wiz-test-carla-snapshots/step-03.json`

### Step 4: /intake
- Method: GET
- HTTP: 200 OK
- Note: open intake form
- Cookies before: `{"overture_auth": "eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJKbzBYOC05TVlfbEZwd1VaIiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.j4XURrjRh6Wvwb-dzmefrVJghDccn_00dzHuUjiEMYE", "overture_session": "W0ec-ay_imciUtsI8we65kVAm9nZV2to"}`
- Set-Cookie response: overture_auth=eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJKbzBYOC05TVlfbEZwd1VaIiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.j4XURrjRh6Wvwb-dzmefrVJghDccn_00dzHuUjiEMYE; HttpOnly; Max-Age=28800; Path=/; SameSite=Lax
overture_session=W0ec-ay_imciUtsI8we65kVAm9nZV2to; Path=/; HttpOnly; SameSite=Lax
- Title: Intake - Overture
- Headings: Overture Wizard, Intake
- Inputs: idea, viewport
- Buttons: Start research approval
- Aria labels: Breadcrumbs, Curated examples, Wizard steps, page
- Validation messages: (none)
- Accessibility snapshot: title=Intake - Overture | headings=['Overture Wizard', 'Intake'] | inputs=['idea', 'viewport'] | buttons=['Start research approval'] | aria=['Breadcrumbs', 'Curated examples', 'Wizard steps', 'page']
- Snapshot file: `/tmp/m-wiz-test-carla-snapshots/step-04.json`

### Step 5: /intake
- Method: POST
- HTTP: 303 See Other
- Note: submit idea
- Cookies before: `{"overture_auth": "eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJaSzIyaWw4cEpVV05GSS04IiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.J2fwPJn9xOPrE1uiJn072rz9y0BCF9ot3_QYpq0X04I", "overture_session": "{\"designer_email\":\"carla@dogfood.test\",\"intake_id\":\"idea_bfa7d86930f55f8ca300c9c0be1da8ef\",\"user_email\":\"carla@dogfood.test\",\"user_id\":\"carla@dogfood.test\"}"}`
- Set-Cookie response: overture_auth=eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJaSzIyaWw4cEpVV05GSS04IiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.J2fwPJn9xOPrE1uiJn072rz9y0BCF9ot3_QYpq0X04I; HttpOnly; Max-Age=28800; Path=/; SameSite=Lax
overture_session="{\"designer_email\":\"carla@dogfood.test\"\054\"intake_id\":\"idea_bfa7d86930f55f8ca300c9c0be1da8ef\"\054\"user_email\":\"carla@dogfood.test\"\054\"user_id\":\"carla@dogfood.test\"}"; HttpOnly; Path=/; SameSite=Lax
- Title: 
- Headings: (none)
- Inputs: (none)
- Buttons: (none)
- Aria labels: (none)
- Validation messages: (none)
- Accessibility snapshot: title= | headings=[] | inputs=[] | buttons=[] | aria=[]
- Snapshot file: `/tmp/m-wiz-test-carla-snapshots/step-05.json`

### Step 6: /research/approval
- Method: GET
- HTTP: 400 Bad Request
- Note: load research approval for the persisted idea
- Cookies before: `{"overture_auth": "eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJ1d2RUZUQ0MFhFSklmaVZMIiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.v_2YxZnmoUyc7yvI6vwK3hsmx6HkmAQdoCF8cHL6RNM", "overture_session": "{}"}`
- Set-Cookie response: overture_auth=eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJ1d2RUZUQ0MFhFSklmaVZMIiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.v_2YxZnmoUyc7yvI6vwK3hsmx6HkmAQdoCF8cHL6RNM; HttpOnly; Max-Age=28800; Path=/; SameSite=Lax
overture_session="{}"; HttpOnly; Path=/; SameSite=Lax
- Title: Research approval - Overture
- Headings: Overture Wizard, Research approval
- Inputs: viewport
- Buttons: (none)
- Aria labels: Breadcrumbs, Wizard steps, page
- Validation messages: No intake is stored in this session. Return to intake before approving research sources.
- Accessibility snapshot: title=Research approval - Overture | headings=['Overture Wizard', 'Research approval'] | inputs=['viewport'] | buttons=[] | aria=['Breadcrumbs', 'Wizard steps', 'page']
- Snapshot file: `/tmp/m-wiz-test-carla-snapshots/step-06.json`

### Step 7: /research/approval
- Method: POST
- HTTP: 400 Bad Request
- Note: submit source approvals
- Cookies before: `{"overture_auth": "eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJlc2tsaU5zUER0MnBZXzg0IiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.SclglxM66D3tLJer9aP8qTByzYOVNkTe08O-9iMFr2A", "overture_session": "{\"designer_email\":\"carla@dogfood.test\",\"user_email\":\"carla@dogfood.test\",\"user_id\":\"carla@dogfood.test\"}"}`
- Set-Cookie response: overture_auth=eyJlbWFpbCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCIsImV4cCI6MTc3ODMyNzYzOSwibm9uY2UiOiJlc2tsaU5zUER0MnBZXzg0IiwidXNlcl9pZCI6ImNhcmxhQGRvZ2Zvb2QudGVzdCJ9.SclglxM66D3tLJer9aP8qTByzYOVNkTe08O-9iMFr2A; HttpOnly; Max-Age=28800; Path=/; SameSite=Lax
overture_session="{\"designer_email\":\"carla@dogfood.test\"\054\"user_email\":\"carla@dogfood.test\"\054\"user_id\":\"carla@dogfood.test\"}"; HttpOnly; Path=/; SameSite=Lax
- Title: Research approval - Overture
- Headings: Overture Wizard, Research approval
- Inputs: viewport
- Buttons: (none)
- Aria labels: Breadcrumbs, Wizard steps, page
- Validation messages: No intake is stored in this session.
- Accessibility snapshot: title=Research approval - Overture | headings=['Overture Wizard', 'Research approval'] | inputs=['viewport'] | buttons=[] | aria=['Breadcrumbs', 'Wizard steps', 'page']
- Snapshot file: `/tmp/m-wiz-test-carla-snapshots/step-07.json`

## Status log
- /auth/login (GET): 200 OK
- /auth/magic-link (POST): 200 OK
- /auth/consume (GET): 200 OK
- /intake (GET): 200 OK
- /intake (POST): 303 See Other
- /research/approval (GET): 400 Bad Request
- /research/approval (POST): 400 Bad Request

## Friction log
- P0: `/research/approval` never receives `intake_id` in session context and renders "No intake is stored in this session."
- P1: `POST /research/approval` returns `400 Bad Request` with "No intake is stored in this session." and does not advance to synthesis.
- Evidence: cookie sequence shows `/intake` POST response sets `overture_session` to JSON with `intake_id`; subsequent `/research/approval` request resets it to `"{}"` and loses `intake_id`.

## Outcome
- Result: Carla path blocked at research approval; export/synthesis/ticket steps were not reached in this run.
- Cookie and error evidence captured in `/tmp/m-wiz-test-carla-snapshots/step-*.json` and this report.
