# Overture

Overture is a Python CLI package for turning raw product ideas into durable
intake records, curated research notes, graph records, synthesis briefs, and
Symphony-ready ticket drafts.

## Requirements

- Python 3.11 or newer
- `pip` for local editable installs

The package currently uses the Python standard library at runtime.

## Setup

From the repository root:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

You can also run the CLI without installing the package by using
`python -m overture` from the repository root.

## CLI Usage

Create an intake record from a raw idea:

```sh
python -m overture intake "Build a GraphRAG system that turns research into Symphony tickets"
```

By default, intake records are written under `.overture/intake/`. Use
`--store-dir` to write them somewhere else:

```sh
python -m overture intake "Document the MVP validation path" --store-dir /tmp/overture-intake
```

Run the deterministic end-to-end fixture:

```sh
python -m overture fixture --output-dir /tmp/overture-fixture
```

The fixture writes staged artifacts for intake, research, graph, synthesis, and
ticket draft output. The generated ticket draft is written to:

```text
/tmp/overture-fixture/ticket/symphony-ticket-draft.md
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

## Manual Testing

Use these checks when validating changes manually:

1. Run an intake command with a temporary output directory.
2. Confirm the command prints the created JSON path and stable intake ID.
3. Open the JSON file and confirm it contains `raw_text`, `source_type`,
   `normalized_summary`, `created_at`, and `id`.
4. Run the fixture command with a temporary output directory.
5. Confirm the command prints paths for `intake`, `research`, `graph`,
   `synthesis`, and `ticket_draft`.
6. Inspect the generated ticket draft and confirm it contains the documented
   ticket sections in order.
7. When research approval behavior changes, run the research command with
   `OVERTURE_LLM_CLIENT=fake`, approve at least one suggested source, and
   confirm `/tmp/overture-store/research/<intake-id>.json` contains approved
   `items`.
8. When export behavior changes, run `python -m overture export <ticket-path>
   --team-id <linear-team-id> --dry-run` and confirm it prints the issue title
   and body without calling Linear.

Example:

```sh
python -m overture intake "Manual smoke test for Overture" --store-dir /tmp/overture-intake
python -m overture fixture --output-dir /tmp/overture-fixture
python -m overture export examples/overture_mvp_linear_issue_draft.md --team-id team-id --dry-run
sed -n '1,160p' /tmp/overture-fixture/ticket/symphony-ticket-draft.md
```

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
