#!/usr/bin/env python3
"""Ensure cleanup only deletes artifacts bound to this PR and workflow run."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import prune_firmware_artifacts as cleaner


REPOSITORY = "alice/specter-diy-web-simulator"
TOKEN = "workflow-token"


class FirmwareArtifactCleanupTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = {
            101: {"id": 101, "name": "specter-firmware-pr-19", "expired": False,
                  "workflow_run": {"id": 201}},
            102: {"id": 102, "name": "specter-firmware-pr-19-run-202-attempt-1", "expired": False,
                  "workflow_run": {"id": 202}},
            103: {"id": 103, "name": "specter-firmware-pr-20-run-203-attempt-1", "expired": False,
                  "workflow_run": {"id": 203}},
            104: {"id": 104, "name": "specter-firmware-pr-19-run-204-attempt-1", "expired": False,
                  "workflow_run": {"id": 204}},
            105: {"id": 105, "name": "specter-firmware", "expired": False,
                  "workflow_run": {"id": 205}},
            106: {"id": 106, "name": "specter-firmware-pr-19-run-206-attempt-2", "expired": False,
                  "workflow_run": {"id": 206}},
            107: {"id": 107, "name": "specter-firmware_PR-19_aaaaaaaaaaaa", "expired": False,
                  "workflow_run": {"id": 207}},
            108: {"id": 108, "name": "specter-firmware_PR-19_aaaaaaaaaaaa_attempt-2", "expired": False,
                  "workflow_run": {"id": 208}},
            109: {"id": 109, "name": "specter-firmware_PR-20_aaaaaaaaaaaa", "expired": False,
                  "workflow_run": {"id": 209}},
            110: {"id": 110, "name": "specter-firmware_PR-19_invalid", "expired": False,
                  "workflow_run": {"id": 210}},
        }
        self.calls = []

    def request_fn(self, method, path, token):
        self.calls.append((method, path, token))
        artifact_id = int(path.rsplit("/", 1)[1])
        if method == "GET":
            return self.artifacts.get(artifact_id)
        if method == "DELETE":
            self.artifacts.pop(artifact_id, None)
            return None
        self.fail(f"Unexpected method: {method}")

    def test_replaces_only_prior_firmware_bound_to_trusted_state(self):
        result = cleaner.prune(REPOSITORY, 19, [
            {"artifact_id": 101, "workflow_run_id": 201},
            {"artifact_id": 103, "workflow_run_id": 203},
            {"artifact_id": 104, "workflow_run_id": 999},
            {"artifact_id": 106, "workflow_run_id": 206},
        ], TOKEN, self.request_fn)
        self.assertEqual(result["deleted"], [101, 106])
        self.assertEqual(self.artifacts[102]["name"], "specter-firmware-pr-19-run-202-attempt-1")
        self.assertIn(103, self.artifacts)
        self.assertIn(104, self.artifacts)
        self.assertEqual(
            {item["artifact_id"]: item["reason"] for item in result["skipped"]},
            {103: "identity-mismatch", 104: "identity-mismatch"},
        )
        self.assertTrue(all(call[2] == TOKEN for call in self.calls))

    def test_commit_named_artifacts_are_pr_and_run_scoped(self):
        result = cleaner.prune(REPOSITORY, 19, [
            {"artifact_id": 107, "workflow_run_id": 207},
            {"artifact_id": 108, "workflow_run_id": 208},
            {"artifact_id": 109, "workflow_run_id": 209},
            {"artifact_id": 110, "workflow_run_id": 210},
        ], TOKEN, self.request_fn)
        self.assertEqual(result["deleted"], [107, 108])
        self.assertIn(109, self.artifacts)
        self.assertIn(110, self.artifacts)
        self.assertEqual(len(result["skipped"]), 2)

    def test_duplicate_ids_are_deleted_once(self):
        result = cleaner.prune(REPOSITORY, 19, [
            {"artifact_id": 101, "workflow_run_id": 201},
            {"artifact_id": 101, "workflow_run_id": 201},
        ], TOKEN, self.request_fn)
        self.assertEqual(result["deleted"], [101])
        self.assertEqual(sum(call[0] == "DELETE" for call in self.calls), 1)

    def test_invalid_repository_pr_or_artifact_reference_fails_closed(self):
        with self.assertRaises(ValueError):
            cleaner.prune("alice/../other", 19, [], TOKEN, self.request_fn)
        with self.assertRaises(ValueError):
            cleaner.prune(REPOSITORY, 0, [], TOKEN, self.request_fn)
        with self.assertRaises(ValueError):
            cleaner.prune(REPOSITORY, 19, [{"artifact_id": True, "workflow_run_id": 201}],
                          TOKEN, self.request_fn)
        with self.assertRaises(ValueError):
            cleaner.prune(REPOSITORY, 19, [
                {"artifact_id": artifact_id, "workflow_run_id": run_id}
                for artifact_id, run_id in ((1, 1), (2, 2), (3, 3), (4, 4), (5, 5))
            ], TOKEN, self.request_fn)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
