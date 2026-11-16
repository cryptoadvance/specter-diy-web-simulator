#!/usr/bin/env python3
"""Capacity-triggered PR preview eviction tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import prune_pages


SERVICE = "alice/specter-diy-web-simulator"


def add_preview(root: Path, number: int, sha: str, updated: str, payload_bytes: int = 4096):
    route = root / "pr" / str(number) / sha
    route.mkdir(parents=True)
    (route / "index.html").write_bytes(b"x" * payload_bytes)
    record = {
        "head_sha": sha,
        "request_id": f"specter-pr-{number}-{sha}-123-1",
        "source_updated_at": updated,
        "source_repository": "bob/specter-diy",
        "preview_url": f"https://alice.github.io/specter-diy-web-simulator/pr/{number}/{sha}/",
        "firmware_url": f"https://github.com/{SERVICE}/actions/runs/123/artifacts/{number}",
        "run_url": f"https://github.com/{SERVICE}/actions/runs/123",
        "workflow_run_id": 123,
        "run_attempt": 1,
        "simulator_sha": "f" * 40,
    }
    state = {
        "latest_source_updated_at": updated,
        "latest_source_sha": sha,
        "latest_request_id": record["request_id"],
        "latest_action": "build",
        "workflow_run_id": 123,
        "run_attempt": 1,
        "status": "success",
        "base_repository": "cryptoadvance/specter-diy",
        "base_sha": "b" * 40,
        "base_ref": "master",
        "head_repository": "bob/specter-diy",
        "head_ref": "feature",
        "simulator_repository": SERVICE,
        "simulator_sha": "f" * 40,
        "successful_previews": [record],
    }
    state_path = root / ".preview-state" / "pr" / f"{number}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    status_path = root / "status" / "pr" / f"{number}.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        "status": "success", "preview_url": record["preview_url"],
        "firmware_url": record["firmware_url"], "successful_previews": [record],
    }), encoding="utf-8")


class PrunePagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pages = Path(self.temp.name)

    def test_does_nothing_while_public_tree_is_under_budget(self):
        add_preview(self.pages, 10, "a" * 40, "2026-01-01T00:00:00Z")
        add_preview(self.pages, 99, "b" * 40, "2026-02-01T00:00:00Z")
        result = prune_pages.prune(self.pages, current_pr=99, budget_bytes=100_000)
        self.assertEqual(result["evicted_pr_numbers"], [])
        self.assertTrue((self.pages / "pr/10").is_dir())

    def test_capacity_pressure_evicts_oldest_other_pr_and_keeps_firmware_record(self):
        add_preview(self.pages, 10, "a" * 40, "2026-01-01T00:00:00Z")
        add_preview(self.pages, 20, "b" * 40, "2026-02-01T00:00:00Z")
        add_preview(self.pages, 99, "c" * 40, "2026-03-01T00:00:00Z")
        before = prune_pages.public_tree_bytes(self.pages)
        budget = before - 4096 + 256
        result = prune_pages.prune(self.pages, current_pr=99, budget_bytes=budget)
        self.assertEqual(result["evicted_pr_numbers"], [10])
        self.assertFalse((self.pages / "pr/10").exists())
        self.assertTrue((self.pages / "pr/20").is_dir())
        self.assertTrue((self.pages / "pr/99").is_dir())

        state = json.loads((self.pages / ".preview-state/pr/10.json").read_text())
        record = state["successful_previews"][0]
        self.assertEqual(state["status"], "capacity-evicted")
        self.assertIsNone(record["preview_url"])
        self.assertTrue(record["preview_evicted"])
        self.assertIn("artifacts/10", record["firmware_url"])
        status = json.loads((self.pages / "status/pr/10.json").read_text())
        self.assertEqual(status["status"], "capacity-evicted")
        self.assertIsNone(status["preview_url"])

    def test_evicts_prs_in_oldest_preview_order_until_below_budget(self):
        add_preview(self.pages, 20, "b" * 40, "2026-02-01T00:00:00Z")
        add_preview(self.pages, 10, "a" * 40, "2026-01-01T00:00:00Z")
        add_preview(self.pages, 99, "c" * 40, "2026-03-01T00:00:00Z")
        before = prune_pages.public_tree_bytes(self.pages)
        budget = before - (2 * 4096) + 256
        result = prune_pages.prune(self.pages, current_pr=99, budget_bytes=budget)
        self.assertEqual(result["evicted_pr_numbers"], [10, 20])
        self.assertTrue((self.pages / "pr/99").is_dir())

    def test_fails_without_deleting_current_pr_if_it_alone_exceeds_budget(self):
        add_preview(self.pages, 99, "c" * 40, "2026-03-01T00:00:00Z")
        before = prune_pages.public_tree_bytes(self.pages)
        with self.assertRaisesRegex(RuntimeError, "current PR is protected"):
            prune_pages.prune(self.pages, current_pr=99, budget_bytes=before - 1)
        self.assertTrue((self.pages / "pr/99").is_dir())


if __name__ == "__main__":
    unittest.main()
