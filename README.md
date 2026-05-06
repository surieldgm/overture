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

Example:

```sh
python -m overture intake "Manual smoke test for Overture" --store-dir /tmp/overture-intake
python -m overture fixture --output-dir /tmp/overture-fixture
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
