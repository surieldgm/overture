import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_TO_CHECK = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "branch-protection.md",
    REPO_ROOT / "docs" / "onboarding-walkthrough.md",
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


class DocLinkTests(unittest.TestCase):
    def test_branch_protection_doc_exists_with_required_settings(self) -> None:
        doc_path = REPO_ROOT / "docs" / "branch-protection.md"
        self.assertTrue(doc_path.exists())

        doc_text = doc_path.read_text(encoding="utf-8")
        required_fragments = (
            "Last verified on 2026-05-07.",
            "Settings > Code and automation > Branches > Branch protection rules > Add rule",
            "Settings > Code and automation > Branches > Branch protection rules > Edit",
            "Branch name pattern",
            "main",
            "Require a pull request before merging",
            "Require status checks to pass before merging",
            "Require branches to be up to date before merging",
            "Python 3.11 unittest",
            "Do not allow bypassing the above settings",
            "Allow force pushes",
            "Disabled",
            "Human approval is not required by branch protection.",
            "green CI result",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, doc_text)

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
