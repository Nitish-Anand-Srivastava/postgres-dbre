from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.validation import catalog
from tools.validation.checks import check_repository_map


BRANCH = f"{chr(0x251C)}{chr(0x2500) * 2} "
LAST_BRANCH = f"{chr(0x2514)}{chr(0x2500) * 2} "


class RepositoryMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        for category in catalog.ALL_EXPECTED_CATEGORIES:
            (self.root / category).mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_map(self, entries: list[str], extra_lines: list[str] | None = None) -> None:
        lines = ["toolkit/", *(f"{BRANCH}{entry}/" for entry in entries)]
        if lines:
            lines[-1] = lines[-1].replace(BRANCH, LAST_BRANCH, 1)
        lines.extend(extra_lines or [])
        (self.root / "README.md").write_text(
            "## 13. Repository map (visual navigation)\n\n"
            "```text\n"
            + "\n".join(lines)
            + "\n```\n",
            encoding="utf-8",
        )

    def test_accepts_every_catalog_category_exactly_once(self) -> None:
        self._write_map(list(catalog.ALL_EXPECTED_CATEGORIES))

        self.assertEqual(check_repository_map(self.root), [])

    def test_reports_missing_duplicate_nonexistent_and_synthetic_entries(self) -> None:
        categories = list(catalog.ALL_EXPECTED_CATEGORIES)
        missing = categories.pop()
        duplicate = categories[0]
        self._write_map(
            [*categories, duplicate],
            [f"{BRANCH}not-a-real-directory/", "Incident"],
        )

        messages = [issue.message for issue in check_repository_map(self.root)]
        self.assertTrue(any(f"'{missing}/'" in message and "found 0" in message for message in messages))
        self.assertTrue(any(f"'{duplicate}/'" in message and "found 2" in message for message in messages))
        self.assertTrue(any("not-a-real-directory/" in message for message in messages))
        self.assertTrue(any("synthetic root entry" in message and "Incident" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
