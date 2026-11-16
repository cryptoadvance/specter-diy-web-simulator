from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


NORMALIZER = Path(__file__).resolve().parents[1] / "browser" / "normalize-glue.py"


class NormalizeGlueTests(unittest.TestCase):
    def test_removes_temp_markers_under_different_tmpdirs(self):
        for directory in ("/tmp", "/home/ubuntu/.hermes/cache/scratch"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as temp:
                glue = Path(temp) / "micropython.js"
                marker = f"{directory}/tmpabc123.js"
                glue.write_text(
                    "\n".join(
                        (
                            f"// include: {marker}",
                            f"// end include: {marker}",
                            "// include: shell.js",
                            "// include: node_shell_read.js",
                        )
                    )
                )

                result = subprocess.run(
                    [sys.executable, str(NORMALIZER), str(glue)],
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                normalized = glue.read_text()
                self.assertNotIn(marker, normalized)
                self.assertIn("// include: shell.js", normalized)
                self.assertIn("// include: node_shell_read.js", normalized)


if __name__ == "__main__":
    unittest.main()
