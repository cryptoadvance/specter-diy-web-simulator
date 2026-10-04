from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser"))
import source_project as module


class SourceProjectTests(unittest.TestCase):
    def test_specter_diy_forks_are_recognized_by_project_name(self):
        for repository in (
            "cryptoadvance/specter-diy",
            "Schnuartz/specter-diy",
            "randomcontributor/specter-diy",
        ):
            with self.subTest(repository=repository):
                self.assertTrue(module.is_specter_diy_repository(repository))

    def test_playground_is_not_specter_diy(self):
        self.assertFalse(module.is_specter_diy_repository("randomcontributor/specter-playground"))


if __name__ == "__main__":
    unittest.main()
