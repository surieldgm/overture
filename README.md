# Overture

[![CI](https://github.com/surieldgm/overture/actions/workflows/ci.yml/badge.svg)](https://github.com/surieldgm/overture/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

GraphRAG pipeline that turns raw product ideas into Symphony-ready Linear tickets with research provenance.

Overture takes a fuzzy intake string, scores it against curated or LLM-suggested sources, lifts the result into a graph of evidence, claims, and concepts, synthesizes a structured brief, renders a schema-valid Linear ticket draft, and exports it. Each stage persists durable artifacts so a downstream agent (Symphony orchestrating Codex) can pick up the ticket and act without asking a human what it means.

The package is designed for a small founder + designers team running a fast feedback loop: every stage is deterministic, scriptable, and dogfood-friendly, with multi-user, authenticated, and webhook-driven modes for team-wide rollout.

---

## Requirements

- Python 3.11 or newer
- `pip` for local editable installs

The runtime pipeline uses the Python standard library only. The local UI host runs on stdlib `http.server`. No additional dependencies are required for the canonical pipeline; optional integrations (Codex CLI for LLM-suggested research, Linear API key for export) are configured via environment variables.

## Setup

From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

You can also run the CLI without installing the package by using `python -m overture` from the repository root.

Validate the workspace before the first real run:

```sh
LINEAR_API_KEY=<key> python -m overture setup --workspace /tmp/overture-workspace
```

The setup command reports per-check pass/fail (env vars, write permission, dependency imports), then idempotently creates the workspace layout under `.overture/`. It does not install dependencies or write secrets to disk.

First-time non-technical operators should start with the [First-Time Operator Walkthrough](docs/onboarding-walkthrough.md), which covers setup, intake, research approval, brief review, ticket review, and export in order.

For environment variable reference, see [`.env.example`](.env.example).

## Quick start

Single-shot run from a raw idea string to an exported Linear ticket:

```sh
LINEAR_API_KEY=<key> python -m overture run \
  "Research-backed onboarding doc for new designers" \
  --team-id <linear-team-id> \
  --output-dir /tmp/overture-run
```

The `run` command executes intake → research → graph → synthesis → ticket draft → (optional) Linear export in one invocation, persisting every intermediate artifact so a regression at any stage is debuggable.

To dry-run without creating a Linear issue, omit `--team-id` or pass `--dry-run` on the export step.

## Pipeline commands

### Stage-by-stage flow

| Command | Purpose |
| --- | --- |
| `python -m overture setup` | Validate environment and scaffold `.overture/` |
| `python -m overture intake "<idea>"` | Persist a durable intake record (UUID5-keyed) |
| `python -m overture research <intake-id>` | LLM-suggest sources (via Codex CLI), prompt operator approval |
| `python -m overture fixture` | Deterministic end-to-end fixture for testing the full pipeline |
| `python -m overture run "<idea>"` | Single-shot pipeline from raw idea through export |
| `python -m overture export <ticket-path>` | Validate + export an existing ticket Markdown to Linear |
| `python -m overture validate-ticket-fixtures` | Schema-validate every ticket fixture in the repository (CI-grade check) |

Use `--dry-run` on `export` to validate without creating a Linear issue. Use `OVERTURE_LLM_CLIENT=fake` to run research deterministically without Codex.

### Local wizard UI

```sh
python -m overture ui
```

The host binds to `localhost:8765` by default (override with `--port`) and serves the wizard at `http://localhost:8765/intake`. Wizard routes:

- `/intake` — paste an idea, advance with intake id in session
- `/research` — review LLM-suggested sources, approve/reject per item
- `/synthesis` — read the structured brief
- `/ticket` — review and edit the generated Markdown ticket
- `/export` — dry-run preview or commit to Linear

The server rejects non-loopback bind addresses and non-loopback clients. Session state is held server-side keyed by an opaque session id cookie. Idea text is capped at 5,000 characters and rejected visibly when over the cap.

### Multi-user mode (shared backend)

For team-wide concurrent use, Overture exposes a shared graph backend over HTTP with magic-link authentication.

```sh
# Run the shared backend
OVERTURE_AUTH_SECRET=<random> python -m overture graph-server --port 8766

# Migrate an existing local SQLite store to the shared backend
python -m overture graph-migrate --source .overture/graph.sqlite --target http://localhost:8766
```

Designers point their UI clients at the shared backend; each authenticates via magic link, and every node and edge created during a session is tagged with the authenticated user identity. See [`docs/branch-protection.md`](docs/branch-protection.md) for related repo-side policies.

### Webhook ingest

Overture receives Linear status changes to compute rework signals automatically:

```sh
OVERTURE_LINEAR_WEBHOOK_SECRET=<shared-secret> \
  python -m overture graph-server --port 8766
# Linear webhook posts to http://<host>:8766/webhook/linear
```

The receiver validates HMAC signatures, deduplicates events, and feeds the rework classifier; counts persist in the metrics store.

## Operations

### Metrics summary

Stage timings and rework counts persist to `.overture/metrics.sqlite`:

```sh
python -m overture metrics
python -m overture metrics --format=json --last 5
```

The summary breaks down median/p95 stage durations, success rate, and (post-M3) per-designer rework counts.

### Friction log (dogfooding)

Operators capture friction inline during real runs and confirm what should feed the next milestone backlog:

```sh
python -m overture friction append \
  --db-path /tmp/overture-metrics.sqlite \
  --session-id dogfood-day-1 --run-id latest --category slow \
  --note "Research approval paused long enough to lose context"

python -m overture friction list \
  --db-path /tmp/overture-metrics.sqlite \
  --session-id dogfood-day-1 --format=json

python -m overture friction confirm <entry-id>
```

Categories: `slow`, `confusing`, `broken`, `surprising`, `designer-experience`, `onboarding`, `performance`, `error-handling`, `uncategorized`.

### Milestone closing

Programmatic verification + retro + next-milestone seeding:

```sh
# Verify a milestone passes its done-condition criteria
python -m overture milestone verify --config examples/m1_milestone_config.json

# Generate the milestone retrospective document
python -m overture retro --milestone "Overture MVP" \
  --started-at 2026-05-05 --completed-at 2026-05-07

# Seed the next milestone's intake records from confirmed frictions
python -m overture backlog-seed --target-milestone M2
python -m overture backlog-seed --target-milestone M4 --session-id m3
```

## Manual workflow (smoke testing changes)

Use this when manually exercising the pipeline against a fresh checkout. Generated files stay outside the repository:

1. Create an intake record:

   ```sh
   python -m overture intake "Manual smoke test for Overture" --store-dir /tmp/overture-store/intake
   ```

   Copy the printed intake id from the second output line.

2. Run the research approval step (deterministic mode without Codex):

   ```sh
   OVERTURE_LLM_CLIENT=fake python -m overture research <intake-id> --store-dir /tmp/overture-store
   ```

3. Inspect the generated research JSON:

   ```sh
   sed -n '1,200p' /tmp/overture-store/research/<intake-id>.json
   ```

4. Run the deterministic fixture for the full persisted MVP artifact set:

   ```sh
   python -m overture fixture --output-dir /tmp/overture-fixture
   sed -n '1,160p' /tmp/overture-fixture/ticket/symphony-ticket-draft.md
   ```

5. Validate an export-ready ticket payload before Linear:

   ```sh
   python -m overture export examples/overture_mvp_linear_issue_draft.md --team-id <linear-team-id> --dry-run
   ```

   Omit `--dry-run` and provide `LINEAR_API_KEY` to actually create the issue. Use `--project-id` to assign a Linear project. Successful exports record in `.overture/exports.sqlite`; rerunning the same ticket path with unchanged content prints the existing Linear URL. Use `--force-recreate` only when a changed ticket draft should create a new issue.

6. Validate prior graph context across multiple runs:

   ```sh
   python examples/validate_two_intake_loop.py
   ```

## Validation

Run the full test suite from the repository root:

```sh
python -m unittest discover -s tests
```

The CI workflow runs the same test suite on every pull request to `main` plus a schema validation step (`python -m overture validate-ticket-fixtures`). Branch protection requires both checks green before merge — see [`docs/branch-protection.md`](docs/branch-protection.md) for the canonical settings.

Run individual example scripts to validate specific paths:

```sh
python examples/validate_curated_research.py
python examples/validate_two_intake_loop.py
python examples/validate_linear_export.py
python examples/validate_metrics_summary.py
```

## Documentation

| File | Purpose |
| --- | --- |
| [docs/onboarding-walkthrough.md](docs/onboarding-walkthrough.md) | First-time non-technical operator walkthrough |
| [docs/symphony-ready-ticket-schema.md](docs/symphony-ready-ticket-schema.md) | Canonical Markdown contract Overture produces for Symphony |
| [docs/minimal-knowledge-graph-schema.md](docs/minimal-knowledge-graph-schema.md) | Graph node/edge types, provenance fields, claim semantics |
| [docs/branch-protection.md](docs/branch-protection.md) | GitHub branch protection settings for the auto-merge loop |

## Examples

| File | Purpose |
| --- | --- |
| [examples/intake_examples/](examples/intake_examples/) | Curated intake fixtures across feature, bug, and integration shapes |
| [examples/overture_mvp_linear_issue_draft.md](examples/overture_mvp_linear_issue_draft.md) | Reference ticket conforming to the Symphony-ready schema |
| [examples/validate_curated_research.py](examples/validate_curated_research.py) | Curated-source research adapter walkthrough |
| [examples/validate_two_intake_loop.py](examples/validate_two_intake_loop.py) | Cross-run prior-context validation |
| [examples/validate_linear_export.py](examples/validate_linear_export.py) | Dry-run Linear export end-to-end |
| [examples/validate_metrics_summary.py](examples/validate_metrics_summary.py) | Metrics store summary across two fixture runs |
| [examples/m1_milestone_config.json](examples/m1_milestone_config.json) | Verifier configuration template for milestone closing |

## Security

Vulnerability reports go privately to **suriel.garcia@eria.ai**. See [SECURITY.md](SECURITY.md) for scope, response timelines, and disclosure expectations. The repository runs with GitHub Secret Scanning, Push Protection, and Dependabot security updates enabled.

## License

MIT — see [LICENSE](LICENSE).
