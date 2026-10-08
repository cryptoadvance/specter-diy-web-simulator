#!/usr/bin/env python3
"""Security and Markdown regression tests for fork machine-user comments."""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import report_preview as bot
from report_preview import MARKER

SERVICE = "cryptoadvance/specter-diy-web-simulator"
BASE = "cryptoadvance/specter-diy"
SITE = "https://cryptoadvance.github.io/specter-diy-web-simulator/"

SIM_SHA = "9" * 40
HEAD_SHA = "a" * 40
UPDATED = "2026-10-08T12:30:00.000000Z"
USER = "specter-preview-test"
TOKEN = "fake-pat"


def request(action="build"):
    return {
        "request_id": "specter-pr-12-" + HEAD_SHA + "-99-1",
        "action": action, "base_repository": BASE,
        "base_sha": "b" * 40, "base_ref": "master",
        "pr_number": 12, "head_repository": "outside/specter-diy",
        "head_sha": HEAD_SHA, "head_ref": "feature",
        "source_updated_at": UPDATED,
    }


def state(req, outcome="success", history=None):
    preview = {
        "head_sha": req["head_sha"],
        "preview_url": "https://cryptoadvance.github.io/specter-diy-web-simulator/pr/12/" + HEAD_SHA + "/",
        "firmware_url": "https://github.com/" + SERVICE + "/actions/runs/99/artifacts/123",
        "run_url": "https://github.com/" + SERVICE + "/actions/runs/99",
        "workflow_run_id": 99,
    }
    return {
        "latest_request_id": req["request_id"],
        "latest_action": req["action"],
        "latest_source_sha": req["head_sha"],
        "latest_source_updated_at": UPDATED,
        "workflow_run_id": 99, "run_attempt": 1, "status": outcome,
        "base_repository": BASE, "base_sha": req["base_sha"],
        "base_ref": req["base_ref"], "head_repository": req["head_repository"],
        "head_ref": req["head_ref"],
        "simulator_repository": SERVICE, "simulator_sha": SIM_SHA,
        "successful_previews": [preview] if history is None else history,
    }


def live_pr(req):
    return {
        "number": 12, "state": "closed" if req["action"] == "delete" else "open",
        "updated_at": UPDATED,
        "base": {"repo": {"full_name": BASE}, "sha": req["base_sha"], "ref": "master"},
        "head": {"repo": {"full_name": req["head_repository"]}, "sha": HEAD_SHA, "ref": "feature"},
    }


class MachineUserReporterTests(unittest.TestCase):
    def setUp(self):
        self.work = TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.pages = Path(self.work.name)
        p = self.pages / ".preview-state/pr/12.json"
        p.parent.mkdir(parents=True)
        self.state_path = p
        self.calls = []
        self.comments = [
            {"id": 11, "user": {"login": USER}, "body": MARKER + " older"},
            {"id": 12, "user": {"login": "some-other-contributor"}, "body": MARKER + " unrelated"},
            {"id": 13, "user": {"login": USER}, "body": "Unmarked personal message"},
        ]

    def mock_api(self, method, path, token, data=None):
        self.calls.append((method, path, token, data))
        self.assertEqual(token, TOKEN)
        if method == "GET" and path == "/user":
            return {"type": "User", "login": USER}
        if method == "GET" and path.startswith("/repos/" + BASE + "/issues/12/comments?"):
            return self.comments
        if method == "POST":
            return {"id": 51, "user": {"login": USER}}
        if method == "PATCH":
            return {"id": int(path.rsplit("/", 1)[-1]), "user": {"login": USER}}
        if method == "DELETE":
            return None
        raise AssertionError("Unexpected API: " + method + " " + path)

    def invoke(self, req=None, outcome="success", request_fn=None):
        req = req or request()
        return bot.report(req, self.pages, SERVICE, SIM_SHA, 99, 1,
                          outcome, TOKEN, USER, request_fn or self.mock_api,
                          pull_fetcher=lambda *_: live_pr(req))

    def writes(self):
        return [(method, path) for method, path, *_ in self.calls
                if method in ("POST", "PATCH", "DELETE")]

    def test_existing_comment_patched_in_place_without_duplicate(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req)))
        output = self.invoke()
        self.assertTrue(output["applied"])
        self.assertEqual(output["removed_comments"], 0)
        self.assertEqual(self.writes(), [
            ("PATCH", f"/repos/{BASE}/issues/comments/11")
        ])
        body = [d["body"] for a, _, _, d in self.calls if a == "PATCH"][0]
        self.assertIn("🧪 **Specter PR Build**", body)
        self.assertIn("<summary>Build provenance</summary>", body)
        self.assertIn("🖥️ [Open browser simulator]", body)
        self.assertIn("⬇️ [Download firmware from the same commit]", body)
        self.assertIn("Never use real funds or enter a real seed phrase", body)
        self.assertIn("Use dedicated test hardware for firmware builds", body)
        self.assertIn(MARKER, body)
        self.assertNotIn("### Latest", body)

    def test_no_existing_comment_creates_exactly_one(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req)))
        self.comments = []
        self.invoke()
        self.assertEqual(self.writes(), [("POST", f"/repos/{BASE}/issues/12/comments")])

    def test_extra_owned_marked_duplicate_is_removed_after_patch(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req)))
        self.comments.append({"id": 16, "user": {"login": USER}, "body": MARKER + " newer"})
        out = self.invoke()
        self.assertEqual(out["removed_comments"], 1)
        self.assertEqual(self.writes(), [
            ("PATCH", f"/repos/{BASE}/issues/comments/11"),
            ("DELETE", f"/repos/{BASE}/issues/comments/16"),
        ])

    def test_unchanged_comment_causes_no_api_writes(self):
        req = request()
        st = state(req)
        self.state_path.write_text(json.dumps(st))
        self.comments[0]["body"] = bot.comment_body(st, "build", "success", 12, SITE, SERVICE)
        self.invoke()
        self.assertEqual(self.writes(), [])

    def test_failed_patch_keeps_old_comment_and_duplicates(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req)))
        self.comments.append({"id": 16, "user": {"login": USER}, "body": MARKER + " newer"})
        def fail_patch(method, path, token, data=None):
            if method == "PATCH":
                raise RuntimeError("simulated API outage")
            return self.mock_api(method, path, token, data)
        with self.assertRaisesRegex(RuntimeError, "simulated API outage"):
            self.invoke(request_fn=fail_patch)
        self.assertFalse(any(method == "DELETE" for method, *_ in self.calls))

    def test_unconfirmed_patch_never_deletes_duplicates(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req)))
        self.comments.append({"id": 16, "user": {"login": USER}, "body": MARKER + " newer"})
        def bad_patch(method, path, token, data=None):
            if method == "PATCH":
                self.calls.append((method, path, token, data))
                return {"id": 66, "user": {"login": USER}}
            return self.mock_api(method, path, token, data)
        with self.assertRaisesRegex(ValueError, "update was not confirmed"):
            self.invoke(request_fn=bad_patch)
        self.assertFalse(any(method == "DELETE" for method, *_ in self.calls))

    def test_unconfirmed_first_post_response(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req)))
        self.comments = []
        def missing_id(method, path, token, data=None):
            if method == "POST":
                self.calls.append((method, path, token, data))
                return {"user": {"login": USER}}
            return self.mock_api(method, path, token, data)
        with self.assertRaisesRegex(ValueError, "creation was not confirmed"):
            self.invoke(request_fn=missing_id)
        self.assertFalse(any(method == "DELETE" for method, *_ in self.calls))

    def test_foreign_authentication_rejected_without_writes(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req)))
        def wrong_user(method, path, token, data=None):
            if path == "/user":
                return {"login": "wrong-account", "type": "User"}
            return self.mock_api(method, path, token, data)
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.invoke(request_fn=wrong_user)
        self.assertEqual(self.writes(), [])

    def test_only_upstream_specter_target_allowed(self):
        req = request()
        req["base_repository"] = "schnuartz-ai/specter-diy"
        with self.assertRaisesRegex(ValueError, "only writes"):
            self.invoke(req)
        self.assertEqual(self.writes(), [])

    def test_stale_state_rejected_without_writes(self):
        req = request()
        st = state(req)
        st["latest_source_sha"] = "f" * 40
        self.state_path.write_text(json.dumps(st))
        self.assertEqual(self.invoke()["status"], "stale-state")
        self.assertEqual(self.writes(), [])

    def test_closed_pr_deletes_only_own_marked_comment(self):
        req = request("delete")
        self.state_path.write_text(json.dumps(state(req, "deleted")))
        out = self.invoke(req, "deleted")
        self.assertEqual(out["removed_comments"], 1)
        self.assertEqual(self.writes(), [
            ("DELETE", f"/repos/{BASE}/issues/comments/11")
        ])

    def test_failed_build_keeps_last_success_and_warning(self):
        req = request()
        st = state(req, outcome="failure")
        body = bot.comment_body(st, "build", "failure", 12, SITE, SERVICE)
        self.assertIn("❌", body)
        self.assertIn("Latest build failed", body)
        self.assertIn("Open browser simulator", body)
        self.assertIn("Never use real funds", body)

    def test_success_without_preview_stays_clear(self):
        req = request()
        st = state(req, history=[])
        body = bot.comment_body(st, "build", "success", 12, SITE, SERVICE)
        self.assertNotIn("Open browser simulator", body)
        self.assertIn("No successful browser preview", body)


    def test_capacity_eviction_updates_only_own_comment_without_dead_preview(self):
        req = request()
        evicted = state(req, "capacity-evicted")
        evicted["successful_previews"][0]["preview_url"] = None
        evicted["successful_previews"][0]["preview_evicted"] = True
        self.state_path.write_text(json.dumps(evicted))
        result = bot.report_capacity_evictions(
            [12], self.pages, SERVICE, SIM_SHA, TOKEN, USER,
            request_fn=self.mock_api, pull_fetcher=lambda *_: live_pr(req))
        self.assertEqual(result, [{"pr_number": 12, "status": "reported", "removed_comments": 0}])
        self.assertEqual(self.writes(), [
            ("PATCH", f"/repos/{BASE}/issues/comments/11")
        ])
        body = [d["body"] for a, _, _, d in self.calls if a == "PATCH"][0]
        self.assertIn("Browser preview removed to stay within GitHub Pages limits", body)
        self.assertIn("Download firmware from the same commit", body)
        self.assertNotIn("Open browser simulator", body)

    def test_wrong_simulator_cannot_comment_on_real_specter(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req)))
        with self.assertRaisesRegex(ValueError, "Only the paired production"):
            bot.report(req, self.pages, "schnuartz-ai/specter-diy-web-simulator",
                       SIM_SHA, 99, 1, "success", TOKEN, USER,
                       request_fn=self.mock_api)
        self.assertEqual(self.writes(), [])


if __name__ == "__main__":
    unittest.main()
