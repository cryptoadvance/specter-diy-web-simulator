#!/usr/bin/env python3
"""The privileged publisher must never copy a PR-provided browser shell."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
import json
from hashlib import sha256

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from publish_preview import TRUSTED_WEB, publish_files, validate_artifact_tree
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser"))
from replace_glue import replace_glue


SHA = "a" * 40
BUILD = f"builds/contributor/specter-diy/{SHA}/"


class TrustBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.web = self.root / "artifact/web"
        (self.web / "browser").mkdir(parents=True)
        (self.web / BUILD).mkdir(parents=True)
        (self.web / "browser/current.json").write_text(
            f'{{"build":"{BUILD}","version":"0000000000000000"}}')
        for name in ("build-info.json", "micropython.js", "micropython.wasm", "micropython.data"):
            (self.web / BUILD / name).write_bytes(name.encode())

    def test_only_firmware_files_cross_the_artifact_boundary(self):
        validate_artifact_tree(self.web, BUILD)
        for name in ("index.html", "browser/site.js", "browser/runtime-worker.js",
                     "assets/evil.css", "browser/runtime/evil.py"):
            path = self.web / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<script>phish()</script>")
            with self.assertRaisesRegex(ValueError, "Unexpected browser artifact"):
                validate_artifact_tree(self.web, BUILD)
            path.unlink()

    def test_published_shell_is_the_trusted_simulator(self):
        # Even if an old artifact contains a shell, it cannot replace ours.
        for name in ("index.html", "browser/site.js", "browser/runtime-worker.js"):
            path = self.web / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<script>phish()</script>")
        pages = self.root / "pages"
        publish_files(self.web, pages, 431, SHA)
        published = pages / "pr/431"
        for name in ("browser/site.js", "browser/runtime-worker.js"):
            self.assertEqual((published / name).read_bytes(), (TRUSTED_WEB / name).read_bytes())
        self.assertNotIn("phish()", (published / "index.html").read_text())
        self.assertIn("NEVER ENTER A REAL SEED PHRASE", (published / "index.html").read_text())
        self.assertEqual((published / BUILD / "micropython.wasm").read_bytes(), b"micropython.wasm")
        self.assertEqual((published / "browser/current.json").read_bytes(),
                         (self.web / "browser/current.json").read_bytes())

    def test_unknown_build_files_cannot_be_published(self):
        extra = self.web / BUILD / "phishing.html"
        extra.write_text("<form>seed</form>")
        with self.assertRaisesRegex(ValueError, "Unexpected browser artifact"):
            validate_artifact_tree(self.web, BUILD)

    def test_pr_generated_javascript_is_replaced_by_trusted_runtime(self):
        artifacts = {name: {} for name in ("micropython.js", "micropython.wasm", "micropython.data")}
        (self.web / BUILD / "build-info.json").write_text(json.dumps({"artifacts": artifacts}))
        trusted = self.root / "trusted-micropython.js"
        trusted.write_bytes(b"trusted JavaScript")
        replace_glue(self.web, trusted)
        self.assertEqual((self.web / BUILD / "micropython.js").read_bytes(), trusted.read_bytes())
        manifest = json.loads((self.web / BUILD / "build-info.json").read_text())
        self.assertEqual(manifest["artifacts"]["micropython.js"]["sha256"],
                         sha256(trusted.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
