#!/usr/bin/env python3
"""The Pages deployment tree excludes private ordering state."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from stage_pages_site import stage


class StagePagesSiteTests(unittest.TestCase):
    def test_stages_all_previews_and_status_but_not_publisher_state(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            persistent = root / "persistent"
            (persistent / "pr/45").mkdir(parents=True)
            (persistent / "status/pr").mkdir(parents=True)
            (persistent / ".preview-state/pr").mkdir(parents=True)
            (persistent / ".git").mkdir()
            (persistent / "pr/45/index.html").write_text("preview")
            (persistent / "status/pr/45.json").write_text("{}")
            (persistent / ".preview-state/pr/45.json").write_text("secret state")
            output = root / "site"
            stage(persistent, output)
            self.assertEqual((output / "pr/45/index.html").read_text(), "preview")
            self.assertEqual((output / "status/pr/45.json").read_text(), "{}")
            self.assertTrue((output / ".nojekyll").is_file())
            self.assertFalse((output / ".preview-state").exists())
            self.assertFalse((output / ".git").exists())


if __name__ == "__main__":
    unittest.main()
