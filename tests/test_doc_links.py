import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_TO_CHECK = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "onboarding-walkthrough.md",
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


class DocLinkTests(unittest.TestCase):
    def test_repository_markdown_links_point_to_existing_files(self) -> None:
        missing: list[str] = []
        for doc_path in DOCS_TO_CHECK:
            for target in _repository_link_targets(doc_path):
                if not target.exists():
                    missing.append(f"{doc_path.relative_to(REPO_ROOT)} -> {target.relative_to(REPO_ROOT)}")

        self.assertEqual(missing, [])


def _repository_link_targets(doc_path: Path) -> list[Path]:
    targets: list[Path] = []
    for match in MARKDOWN_LINK.finditer(doc_path.read_text(encoding="utf-8")):
        raw_target = match.group(1).strip()
        parsed = urlparse(raw_target)
        if parsed.scheme or raw_target.startswith("#"):
            continue

        path_text = unquote(parsed.path)
        if not path_text:
            continue

        target = (doc_path.parent / path_text).resolve()
        try:
            target.relative_to(REPO_ROOT)
        except ValueError:
            continue
        targets.append(target)

    return targets


if __name__ == "__main__":
    unittest.main()
