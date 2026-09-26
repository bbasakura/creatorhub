import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import runtime_paths


class RuntimePathsTests(unittest.TestCase):
    def test_runtime_layout_is_explicit_and_creates_subdirs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            layout = runtime_paths.ensure_runtime_layout(root, migrate_legacy=False)
            self.assertEqual(layout["root"], root.resolve())
            self.assertTrue((root / "logs").is_dir())
            self.assertTrue((root / "diagnostics").is_dir())
            self.assertTrue((root / "temp").is_dir())

    def test_environment_override_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"CREATORHUB_RUNTIME_DIR": directory}):
                self.assertEqual(runtime_paths.runtime_root("ignored"), Path(directory).resolve())

    def test_known_legacy_debug_files_migrate_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            legacy = base / "legacy"
            target = base / "target"
            legacy.mkdir()
            target.mkdir()
            (legacy / "a.txt").write_text("old", encoding="utf-8")
            (legacy / "same.txt").write_text("legacy", encoding="utf-8")
            (target / "same.txt").write_text("new", encoding="utf-8")
            moved = runtime_paths._move_legacy_files(legacy, target)
            self.assertEqual(moved, 1)
            self.assertEqual((target / "a.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual((target / "same.txt").read_text(encoding="utf-8"), "new")
            self.assertTrue((legacy / "same.txt").exists())


if __name__ == "__main__":
    unittest.main()
