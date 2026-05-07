# Overture

Overture is a Python CLI package for turning raw product ideas into durable
intake records, curated research notes, graph records, synthesis briefs, and
Symphony-ready ticket drafts.

## Requirements

- Python 3.11 or newer
- `pip` for local editable installs

The package currently uses the Python standard library at runtime.

## Local UI Host

Start the local wizard scaffold from the repository root:

```sh
python -m overture ui
```

The host binds to `localhost` on port `8765` by default and serves the wizard at
`http://localhost:8765/intake`. Use `--port` to choose another local port. The
server rejects non-loopback bind addresses and non-loopback clients; session
state is held in memory on the server and keyed by an opaque session id cookie.

Current placeholder routes are:

- `/intake`
- `/research`
- `/synthesis`
- `/ticket`
- `/export`

## Setup

From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

You can also run the CLI without installing the package by using
`python -m overture` from the repository root.

First-time non-technical operators should start with the
[First-Time Operator Walkthrough](docs/onboarding-walkthrough.md), which covers
setup, intake, research approval, brief review, ticket review, and export in
order.

## CLI Usage

Validate a first-run workspace before running the pipeline:

```sh
LINEAR_API_KEY=<key> python -m overture setup --workspace /tmp/overture-workspace
```

The setup command reports pass/fail status for environment, write permission,
and import checks, then creates empty workspace directories under
`.overture/`. It does not install dependencies or write secrets to disk.

Create an intake record from a raw idea:

```sh
python -m overture intake "Build a GraphRAG system that turns research into Symphony tickets"
```

By default, intake records are written under `.overture/intake/`. Use
`--store-dir` to write them somewhere else:

```sh
python -m overture intake "Document the MVP validation path" --store-dir /tmp/overture-intake
```

Start the form-based wizard UI:

```sh
python -m overture ui --store-dir /tmp/overture-store
```

Then open `http://127.0.0.1:8080/intake`, enter a raw idea, and submit it.
The UI writes intake records under `<store-dir>/intake/`, stores the resulting
intake ID in the browser session, and advances to the research approval route.
Idea text is capped at 5,000 characters and rejected visibly when over the cap.

Run the deterministic end-to-end fixture:

```sh
python -m overture fixture --output-dir /tmp/overture-fixture
```

The fixture writes staged artifacts for intake, research, graph, synthesis, and
ticket draft output. The generated ticket draft is written to:

```text
/tmp/overture-fixture/ticket/symphony-ticket-draft.md
```

Capture dogfooding friction against a metrics run:

```sh
python -m overture friction append --db-path /tmp/overture-metrics.sqlite \
  --session-id dogfood-day-1 --run-id latest --category slow \
  --note "Research approval paused long enough to lose context"
```

Query the friction log by session or run id:

```sh
python -m overture friction list --db-path /tmp/overture-metrics.sqlite \
  --session-id dogfood-day-1 --format=json
```

## Manual Workflow

Use this workflow when manually exercising the current idea-to-ticket path. The
commands below keep generated files outside the repository so repeated smoke
tests do not dirty the working tree.

1. Create an intake record:

   ```sh
   python -m overture intake "Manual smoke test for Overture" --store-dir /tmp/overture-store/intake
   ```

2. Copy the printed intake ID from the second output line.

3. Run the research approval step for that intake:

   ```sh
   python -m overture research <intake-id> --store-dir /tmp/overture-store
   ```

   By default, this asks the local Codex CLI to suggest sources and then
   prompts for manual approval of each candidate. Approve only sources you have
   inspected. For deterministic local validation without calling Codex, use the
   fake client:

   ```sh
   OVERTURE_LLM_CLIENT=fake python -m overture research <intake-id> --store-dir /tmp/overture-store
   ```

4. Inspect the generated research JSON:

   ```sh
   sed -n '1,200p' /tmp/overture-store/research/<intake-id>.json
   ```

5. Run the full deterministic fixture when you need the complete persisted MVP
   artifact set:

   ```sh
   python -m overture fixture --output-dir /tmp/overture-fixture
   ```

   The fixture writes `intake`, `research`, `graph`, `synthesis`, and
   `ticket_draft` artifacts and validates the Symphony-ready ticket draft before
   writing it.

6. Validate an export-ready ticket payload before creating a Linear issue:

   ```sh
   python -m overture export examples/overture_mvp_linear_issue_draft.md --team-id <linear-team-id> --dry-run
   ```

   To create the Linear issue, omit `--dry-run` and provide `LINEAR_API_KEY`.
   Use `--project-id` when the issue should be assigned to a Linear project.
   Overture records successful exports in `.overture/exports.sqlite`; rerunning
   the same ticket path with unchanged content prints the existing Linear URL.
   Use `--force-recreate` only when a changed ticket draft should create a new
   issue.

7. To validate prior graph context across multiple runs, execute:

   ```sh
   python examples/validate_two_intake_loop.py
   ```

## Human Testing

Use this section when a human reviewer needs to smoke test Overture from a
fresh checkout. The commands keep generated files under `/tmp` so the working
tree stays clean.

### 1. Prepare the CLI

From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

If the editable install is already active, you can skip this step. The examples
below also work with `python -m overture` from the repository root.

### 2. Verify intake output

Create an intake record in a temporary store:

```sh
python -m overture intake "Manual smoke test for Overture" --store-dir /tmp/overture-human-test/intake
```

Expected result:

- The command prints the path to the created JSON file.
- The command prints a stable intake ID on the second output line.
- The JSON file contains `raw_text`, `source_type`, `normalized_summary`,
  `created_at`, and `id`.

### 3. Verify the deterministic artifact path

Run the end-to-end fixture:

```sh
python -m overture fixture --output-dir /tmp/overture-human-test/fixture
```

Expected result:

- The command prints paths for `intake`, `research`, `graph`, `synthesis`, and
  `ticket_draft`.
- The ticket draft exists at
  `/tmp/overture-human-test/fixture/ticket/symphony-ticket-draft.md`.
- The ticket draft contains the expected Symphony ticket sections in order.

Inspect the generated ticket draft:

```sh
sed -n '1,160p' /tmp/overture-human-test/fixture/ticket/symphony-ticket-draft.md
```

### 4. Verify export dry run behavior

Validate an export-ready payload without creating a Linear issue:

```sh
python -m overture export examples/overture_mvp_linear_issue_draft.md --team-id team-id --dry-run
```

Expected result:

- The command prints the issue title and body.
- No Linear issue is created.
- No `LINEAR_API_KEY` is required for the dry run.

### 5. Optional checks for changed areas

Run these only when the matching behavior changed:

- Research approval: run
  `OVERTURE_LLM_CLIENT=fake python -m overture research <intake-id> --store-dir /tmp/overture-human-test`,
  approve at least one suggested source, and confirm
  `/tmp/overture-human-test/research/<intake-id>.json` contains approved
  `items`.
- Prior graph context: run `python examples/validate_two_intake_loop.py` and
  confirm it completes successfully.
- Curated research: run `python examples/validate_curated_research.py` and
  confirm it completes successfully.

## Validation

Run the test suite from the repository root:

```sh
python -m unittest discover -s tests
```

Run the curated research example:

```sh
python examples/validate_curated_research.py
```

Both commands should complete successfully before handing off changes.
