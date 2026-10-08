#!/usr/bin/env python3
"""Comment ownership, latest/previous rendering, and stale-result checks."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import report_preview as reporter


SERVICE = "cryptoadvance/specter-diy-web-simulator"
BASE = "cryptoadvance/specter-diy"
SIM_SHA = "9" * 40
UPDATED = "2026-10-01T12:00:00.000000Z"
TOKEN = "installation-token"


def request(action="build", sha="c" * 40):
    return {
        "request_id": f"specter-pr-19-{sha}-100-1",
        "action": action,
        "base_repository": BASE,
        "base_sha": "b" * 40,
        "base_ref": "master",
        "pr_number": 19,
        "head_repository": "alice/specter-diy",
        "head_sha": sha,
        "head_ref": "feature",
        "source_updated_at": UPDATED,
    }


def successful(sha, run_id, artifact_id):
    root = "https://cryptoadvance.github.io/specter-diy-web-simulator/pr/19/"
    run = f"https://github.com/{SERVICE}/actions/runs/{run_id}"
    return {
        "head_sha": sha,
        "request_id": f"specter-pr-19-{sha}-100-1",
        "source_repository": "alice/specter-diy",
        "preview_url": root + sha + "/",
        "firmware_url": f"{run}/artifacts/{artifact_id}",
        "run_url": run,
        "workflow_run_id": run_id,
        "run_attempt": 1,
        "simulator_sha": SIM_SHA,
    }


def state(req, result="failure", run_id=202, history=None):
    return {
        "latest_source_updated_at": req["source_updated_at"],
        "latest_source_sha": req["head_sha"],
        "latest_request_id": req["request_id"],
        "latest_action": req["action"],
        "workflow_run_id": run_id,
        "run_attempt": 1,
        "status": result,
        "base_repository": req["base_repository"],
        "base_sha": req["base_sha"],
        "base_ref": req["base_ref"],
        "head_repository": req["head_repository"],
        "head_ref": req["head_ref"],
        "simulator_repository": SERVICE,
        "simulator_sha": SIM_SHA,
        "latest_run_url": f"https://github.com/{SERVICE}/actions/runs/{run_id}",
        "successful_previews": history or [],
    }


def live_pr(req, status="open"):
    return {
        "number": req["pr_number"],
        "state": status,
        "updated_at": req["source_updated_at"],
        "base": {"repo": {"full_name": BASE}, "sha": req["base_sha"], "ref": req["base_ref"]},
        "head": {"repo": {"full_name": req["head_repository"]},
                 "sha": req["head_sha"], "ref": req["head_ref"]},
    }


class PreviewReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pages = Path(self.temp.name)
        self.state_path = self.pages / ".preview-state/pr/19.json"
        self.state_path.parent.mkdir(parents=True)
        self.comments = [
            {"id": 1, "user": {"login": "specter-preview[bot]"},
             "body": "old preview\n" + reporter.MARKER},
            {"id": 2, "user": {"login": "specter-preview[bot]"},
             "body": "duplicate\n" + reporter.MARKER},
            {"id": 3, "user": {"login": "someone-else[bot]"},
             "body": "unrelated\n" + reporter.MARKER},
            {"id": 4, "user": {"login": "specter-preview[bot]"}, "body": "unmarked"},
        ]
        self.calls = []

    def request_fn(self, method, path, token, data=None):
        self.calls.append((method, path, token, data))
        if method == "GET" and "/issues/19/comments?" in path:
            return self.comments
        return None

    def run_report(self, req, result="failure", run_id=202, pull=None):
        return reporter.report(
            req, self.pages, SERVICE, SIM_SHA, run_id, 1, result, TOKEN, "specter-preview",
            request_fn=self.request_fn,
            pull_fetcher=lambda *_: pull if pull is not None else live_pr(req),
        )

    def test_failed_commit_reposts_only_its_app_comments_with_two_successes(self):
        req = request()
        a, b = "a" * 40, "b" * 40
        state(req, history=[successful(b, 201, 301), successful(a, 200, 300)])
        self.state_path.write_text(json.dumps(state(req, history=[
            successful(b, 201, 301), successful(a, 200, 300)])))
        result = self.run_report(req)
        self.assertEqual(result, {"applied": True, "status": "failure", "removed_comments": 2})
        deletes = [call[1] for call in self.calls if call[0] == "DELETE"]
        self.assertEqual(deletes, [
            f"/repos/{BASE}/issues/comments/1", f"/repos/{BASE}/issues/comments/2",
        ])
        posts = [call for call in self.calls if call[0] == "POST"]
        self.assertEqual(len(posts), 1)
        body = posts[0][3]["body"]
        self.assertIn("Latest build `ccccccc` failed.", body)
        self.assertIn("[Open browser simulator](https://cryptoadvance.github.io/specter-diy-web-simulator/pr/19/" + b + "/)", body)
        self.assertIn("[Open previous browser simulator](https://cryptoadvance.github.io/specter-diy-web-simulator/pr/19/" + a + "/)", body)
        self.assertIn("[Firmware artifact](https://github.com/cryptoadvance/specter-diy-web-simulator/actions/runs/201/artifacts/301)", body)
        self.assertNotIn("/actions/runs/200/artifacts/300", body)
        self.assertIn("[Failed build logs](https://github.com/cryptoadvance/specter-diy-web-simulator/actions/runs/202)", body)
        self.assertEqual(body.count(reporter.MARKER), 1)
        self.assertTrue(all(call[2] == TOKEN for call in self.calls))

    def test_success_comment_lists_latest_then_previous(self):
        req = request(sha="d" * 40)
        a, b, c = "a" * 40, "b" * 40, "d" * 40
        success_state = state(req, result="success", run_id=202,
                              history=[successful(c, 202, 302), successful(b, 201, 301)])
        self.state_path.write_text(json.dumps(success_state))
        self.run_report(req, result="success")
        body = next(call[3]["body"] for call in self.calls if call[0] == "POST")
        self.assertLess(body.index("### Latest"), body.index("### Previous"))
        self.assertIn(f"`{c[:7]}` → [Open browser simulator]", body)
        self.assertIn("[Firmware artifact](https://github.com/cryptoadvance/specter-diy-web-simulator/actions/runs/202/artifacts/302)", body)
        self.assertIn(f"`{b[:7]}` → [Open previous browser simulator]", body)
        self.assertNotIn(a, body)
        self.assertNotIn("/actions/runs/201/artifacts/301", body)
        self.assertLess(next(i for i, call in enumerate(self.calls) if call[0] == "DELETE"),
                        next(i for i, call in enumerate(self.calls) if call[0] == "POST"))

    def test_stale_run_or_live_pr_never_touches_comments(self):
        req = request()
        self.state_path.write_text(json.dumps(state(req, run_id=201)))
        result = self.run_report(req, run_id=202)
        self.assertEqual(result["status"], "stale-state")
        self.assertEqual(self.calls, [])

        self.state_path.write_text(json.dumps(state(req)))
        result = self.run_report(req, pull=live_pr({**req, "head_sha": "e" * 40}))
        self.assertEqual(result["status"], "stale-pr")
        self.assertEqual(self.calls, [])

    def test_close_removes_only_owned_marked_comments_and_posts_nothing(self):
        req = request(action="delete")
        self.state_path.write_text(json.dumps(state(req, result="deleted", history=[])))
        result = self.run_report(req, result="deleted", pull=live_pr(req, "closed"))
        self.assertEqual(result, {"applied": True, "status": "deleted", "removed_comments": 2})
        self.assertEqual([call[1] for call in self.calls if call[0] == "DELETE"], [
            f"/repos/{BASE}/issues/comments/1", f"/repos/{BASE}/issues/comments/2",
        ])
        self.assertFalse(any(call[0] == "POST" for call in self.calls))


if __name__ == "__main__":
    unittest.main()
