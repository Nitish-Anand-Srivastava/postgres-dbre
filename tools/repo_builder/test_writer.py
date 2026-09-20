from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.repo_builder.writer import MANIFEST_FILENAME, sync_managed_artifacts


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SyncManagedArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

    def _sync(
        self,
        generated: dict[str, dict[str, str]],
        *,
        selected: set[str],
        full_build: bool = True,
    ) -> list[str]:
        return sync_managed_artifacts(
            str(self.root),
            generated,
            selected_categories=selected,
            full_build=full_build,
        )

    def test_removes_deleted_generated_file_and_empty_directories(self) -> None:
        relative = "performance/obsolete-workflow/scripts/01_old.sql"
        content = "SELECT 1;\n"
        self._write(relative, content)
        self._sync(
            {"performance": {relative: _digest(content)}},
            selected={"performance"},
        )

        removed = self._sync({"performance": {}}, selected={"performance"})

        self.assertEqual(removed, [relative])
        self.assertFalse((self.root / relative).exists())
        self.assertFalse((self.root / "performance").exists())

    def test_preserves_untracked_files_when_pruning_directories(self) -> None:
        relative = "performance/obsolete-workflow/scripts/01_old.sql"
        content = "SELECT 1;\n"
        self._write(relative, content)
        self._write("performance/obsolete-workflow/notes.txt", "keep me\n")
        self._sync(
            {"performance": {relative: _digest(content)}},
            selected={"performance"},
        )

        self._sync({"performance": {}}, selected={"performance"})

        self.assertFalse((self.root / relative).exists())
        self.assertEqual(
            (self.root / "performance/obsolete-workflow/notes.txt").read_text(encoding="utf-8"),
            "keep me\n",
        )

    def test_preserves_stale_looking_file_not_owned_by_manifest(self) -> None:
        relative = "performance/obsolete-workflow/scripts/01_managed.sql"
        untracked = "performance/obsolete-workflow/scripts/02_user_owned.sql"
        content = "SELECT 1;\n"
        self._write(relative, content)
        self._write(untracked, "SELECT 2;\n")
        self._sync(
            {"performance": {relative: _digest(content)}},
            selected={"performance"},
        )

        self._sync({"performance": {}}, selected={"performance"})

        self.assertFalse((self.root / relative).exists())
        self.assertEqual((self.root / untracked).read_text(encoding="utf-8"), "SELECT 2;\n")

    def test_matches_generated_hash_across_line_endings(self) -> None:
        relative = "performance/obsolete-workflow/README.md"
        generated = "line one\nline two\n"
        self._write(relative, generated.replace("\n", "\r\n"))
        self._sync(
            {"performance": {relative: _digest(generated)}},
            selected={"performance"},
        )

        removed = self._sync({"performance": {}}, selected={"performance"})

        self.assertEqual(removed, [relative])
        self.assertFalse((self.root / relative).exists())

    def test_refuses_to_delete_modified_managed_file(self) -> None:
        relative = "performance/obsolete-workflow/scripts/01_old.sql"
        original = "SELECT 1;\n"
        self._write(relative, original)
        self._sync(
            {"performance": {relative: _digest(original)}},
            selected={"performance"},
        )
        self._write(relative, "SELECT 2;\n")

        with self.assertRaisesRegex(RuntimeError, "modified content"):
            self._sync({"performance": {}}, selected={"performance"})

        self.assertEqual((self.root / relative).read_text(encoding="utf-8"), "SELECT 2;\n")

    def test_partial_build_preserves_unselected_category_manifest(self) -> None:
        performance = "performance/workflow/README.md"
        locking = "concurrency-and-locking/workflow/README.md"
        self._write(performance, "performance\n")
        self._write(locking, "locking\n")
        self._sync(
            {
                "performance": {performance: _digest("performance\n")},
                "concurrency-and-locking": {locking: _digest("locking\n")},
            },
            selected={"performance", "concurrency-and-locking"},
        )

        self._sync(
            {"performance": {performance: _digest("performance\n")}},
            selected={"performance"},
            full_build=False,
        )

        manifest = json.loads((self.root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        self.assertIn("concurrency-and-locking", manifest["categories"])
        self.assertTrue((self.root / locking).exists())

    def test_rejects_manifest_path_outside_its_category(self) -> None:
        manifest = {
            "version": 1,
            "categories": {"performance": {"../README.md": _digest("unsafe\n")}},
        }
        (self.root / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "unsafe generator manifest path"):
            self._sync({}, selected=set())


if __name__ == "__main__":
    unittest.main()
