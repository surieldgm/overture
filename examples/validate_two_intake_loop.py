from pathlib import Path
import os
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overture.fixture import run_overture_fixture


DEFAULT_LOOP_DIR = Path("/tmp/loop")


def main() -> int:
    base_dir = Path(os.environ.get("OVERTURE_TWO_INTAKE_LOOP_DIR", DEFAULT_LOOP_DIR))
    _reset_dir(base_dir)

    run_overture_fixture(
        base_dir / "run1",
        idea="Add idea persistence to Overture",
        graph_store_base_path=base_dir,
    )
    run_overture_fixture(
        base_dir / "run2",
        idea="Query persisted ideas in synthesis briefs",
        graph_store_base_path=base_dir,
    )

    draft_path = base_dir / "run2" / "ticket" / "symphony-ticket-draft.md"
    provenance = _graph_provenance_section(draft_path.read_text(encoding="utf-8"))
    prior_node_ids = sorted(set(re.findall(r"prior:[A-Za-z0-9_:\\-\\.]+", provenance)))
    if not prior_node_ids:
        print("no prior nodes in graph provenance")
        print("## Graph provenance")
        print(provenance)
        return 1

    for node_id in prior_node_ids:
        print(node_id)
    return 0


def _reset_dir(path: Path) -> None:
    if path.exists():
        for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            else:
                child.rmdir()
    path.mkdir(parents=True, exist_ok=True)


def _graph_provenance_section(markdown: str) -> str:
    match = re.search(r"^## Graph provenance\n(?P<body>.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL)
    return match.group("body").strip() if match else "<missing graph provenance section>"


if __name__ == "__main__":
    raise SystemExit(main())
