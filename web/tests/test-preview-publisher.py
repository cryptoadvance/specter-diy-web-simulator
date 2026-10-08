#!/usr/bin/env python3
"""Adversarial artifact and persistent preview lifecycle tests."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import shutil
import sys
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import publish_preview as publisher


BASE = "alice/specter-diy"
SERVICE = "alice/specter-diy-web-simulator"
SOURCE = "bob/specter-diy"
SHA = "a" * 40
SIM_SHA = "b" * 40
BASE_SHA = "d" * 40
UPDATED = "2026-09-30T12:00:00.000000Z"
ARTIFACTS = ("micropython.wasm", "micropython.data")


def request(sha=SHA, updated=UPDATED, action="build", run_id=101):
    return {
        "request_id": f"specter-pr-19-{sha}-{run_id}-1",
        "action": action,
        "base_repository": BASE,
        "base_sha": BASE_SHA,
        "base_ref": "main",
        "pr_number": 19,
        "head_repository": SOURCE,
        "head_sha": sha,
        "head_ref": "feature",
        "source_updated_at": updated,
    }


def live_pr(req, state="open"):
    return {
        "number": req["pr_number"],
        "state": state,
        "updated_at": req["source_updated_at"],
        "base": {"repo": {"full_name": req["base_repository"]},
                 "sha": req["base_sha"], "ref": req["base_ref"]},
        "head": {
            "sha": req["head_sha"],
            "ref": req["head_ref"],
            "repo": {"full_name": req["head_repository"]} if req["head_repository"] else None,
        },
    }


def browser_archive(path: Path, req: dict, tamper=None) -> None:
    build_path = f"builds/{req['head_repository']}/{req['head_sha']}/"
    prefix = build_path
    data = {name: f"browser:{name}:{req['head_sha']}".encode() for name in ARTIFACTS}
    records = {name: {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}
               for name, payload in data.items()}
    ordered_hashes = [records[name]["sha256"] for name in sorted(records)]
    artifact_set = sha256("".join(ordered_hashes).encode()).hexdigest()
    build_info = {
        "source": {"repository": req["head_repository"], "commit": req["head_sha"]},
        "simulator": {"repository": SERVICE, "commit": SIM_SHA},
        "artifacts": records,
        "artifact_set_sha256": artifact_set,
    }
    entries = {
        "browser/current.json": json.dumps({"build": build_path, "version": artifact_set[:16]}).encode() + b"\n",
        prefix + "build-info.json": json.dumps(build_info).encode() + b"\n",
        **{prefix + name: payload for name, payload in data.items()},
    }
    manifest = {
        "schema": 1,
        "kind": "browser-preview",
        "base_repository": req["base_repository"],
        "base_sha": req["base_sha"],
        "base_ref": req["base_ref"],
        "source_repository": req["head_repository"],
        "source_sha": req["head_sha"],
        "pr_number": req["pr_number"],
        "request_id": req["request_id"],
        "source_updated_at": req["source_updated_at"],
        "simulator_repository": SERVICE,
        "simulator_sha": SIM_SHA,
        "build_path": build_path,
        "files": {name: {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}
                  for name, payload in entries.items()},
    }
    entries["manifest.json"] = json.dumps(manifest).encode()
    if tamper == "wrong-request":
        manifest["request_id"] = "specter-pr-19-wrong"
        entries["manifest.json"] = json.dumps(manifest).encode()
    elif tamper == "wrong-source":
        manifest["source_sha"] = "c" * 40
        entries["manifest.json"] = json.dumps(manifest).encode()
    elif tamper == "fake-hash":
        first = next(iter(manifest["files"].values()))
        first["sha256"] = "0" * 64
        entries["manifest.json"] = json.dumps(manifest).encode()
    elif tamper == "wrong-browser-repo":
        build_info["source"]["repository"] = "mallory/specter-diy"
        entries[prefix + "build-info.json"] = json.dumps(build_info).encode()
        record = manifest["files"][prefix + "build-info.json"]
        record.update(bytes=len(entries[prefix + "build-info.json"]),
                      sha256=sha256(entries[prefix + "build-info.json"]).hexdigest())
        entries["manifest.json"] = json.dumps(manifest).encode()
    elif tamper == "untrusted-js":
        entries[prefix + "micropython.js"] = b"PR controlled JavaScript"

    with tarfile.open(path, "w:gz") as archive:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, BytesIO(payload))


def firmware_artifact(path: Path, req: dict, tamper=None) -> None:
    # Every simulated build gets a fresh artifact directory; commit-specific names
    # must not leave old SHA files in the fixture when the test moves to a new SHA.
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    names = publisher.firmware_filenames(req["pr_number"], req["head_sha"])
    files = {name: f"firmware:{name}:{req['head_sha']}".encode() for name in names}
    records = {name: {"bytes": len(data), "sha256": sha256(data).hexdigest()}
               for name, data in files.items()}
    provenance = {
        "schema": 1,
        "kind": "firmware",
        "base_repository": req["base_repository"],
        "source_repository": req["head_repository"],
        "source_sha": req["head_sha"],
        "pr_number": req["pr_number"],
        "request_id": req["request_id"],
        "source_updated_at": req["source_updated_at"],
        "simulator_repository": SERVICE,
        "simulator_sha": SIM_SHA,
        "files": records,
    }
    if tamper == "wrong-sha":
        provenance["source_sha"] = "c" * 40
    if tamper == "fake-hash":
        provenance["files"][names[0]]["sha256"] = "f" * 64
    for name, data in files.items():
        (path / name).write_bytes(data)
    (path / "source.json").write_text(json.dumps(provenance), encoding="utf-8")
    if tamper == "unexpected":
        (path / "evil.sh").write_text("not executable")


def trusted_runtime_artifact(path: Path, req: dict, tamper=None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    js = b"trusted-runtime-js"
    (path / "micropython.js").write_bytes(js)
    runtime = {
        "schema": 1,
        "kind": "trusted-browser-runtime",
        "base_repository": req["base_repository"],
        "base_sha": req["base_sha"],
        "base_ref": req["base_ref"],
        "simulator_repository": SERVICE,
        "simulator_sha": SIM_SHA,
        "files": {"micropython.js": {"bytes": len(js), "sha256": sha256(js).hexdigest()}},
    }
    if tamper == "wrong-base":
        runtime["base_sha"] = "e" * 40
    elif tamper == "fake-hash":
        runtime["files"]["micropython.js"]["sha256"] = "0" * 64
    (path / "runtime.json").write_text(json.dumps(runtime), encoding="utf-8")


class PreviewPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pages = self.root / "pages"
        self.pages.mkdir()
        self.archive = self.root / "browser-preview-payload.tar.gz"
        self.firmware = self.root / "firmware"
        self.runtime = self.root / "trusted-runtime"
        self.trusted = self.root / "trusted-web"
        (self.trusted / "browser").mkdir(parents=True)
        (self.trusted / "assets").mkdir()
        (self.trusted / "index.html").write_text(
            '<meta http-equiv="Content-Security-Policy" content="script-src \'self\'; '
            "connect-src 'self' http://127.0.0.1:8788 ws://127.0.0.1:8788; "
            'object-src \'none\'">',
            encoding="utf-8",
        )
        (self.trusted / "browser/site.js").write_text("trusted UI")
        (self.trusted / "browser/runtime-worker.js").write_text("trusted worker")
        (self.trusted / "assets/logo.svg").write_text("trusted asset")
        self.env = patch.dict("os.environ", {"GITHUB_REPOSITORY": SERVICE})
        self.env.start()
        self.addCleanup(self.env.stop)
        trusted_runtime_artifact(self.runtime, request())

    def apply(self, req, result="success", build_tamper=None, firmware_tamper=None,
              run_id=101, live_state="open", runtime_tamper=None):
        browser_archive(self.archive, req, build_tamper)
        firmware_artifact(self.firmware, req, firmware_tamper)
        trusted_runtime_artifact(self.runtime, req, runtime_tamper)
        return publisher.publish(
            req, self.pages, self.archive, self.firmware, self.runtime, self.trusted, result,
            SERVICE, SIM_SHA, run_id, 1,
            f"https://github.com/{SERVICE}/actions/runs/{run_id}/artifacts/123",
            "token", lambda *_: live_pr(req, live_state),
        )

    def test_fork_source_publishes_correct_preview_firmware_and_status(self):
        result = self.apply(request())
        preview = self.pages / f"pr/19/{SHA}"
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["applied"])
        published_html = (preview / "index.html").read_text(encoding="utf-8")
        self.assertIn("connect-src 'self'", published_html)
        self.assertNotIn("127.0.0.1:8788", published_html)
        self.assertNotIn("localhost:8788", published_html)
        self.assertEqual((preview / "browser/site.js").read_text(), "trusted UI")
        self.assertEqual((preview / f"builds/{SOURCE}/{SHA}/micropython.wasm").read_bytes(),
                         f"browser:micropython.wasm:{SHA}".encode())
        self.assertTrue((self.pages / ".preview-state/pr/19.json").is_file())
        status = json.loads((self.pages / "status/pr/19.json").read_text())
        self.assertEqual(status["request_id"], request()["request_id"])
        self.assertEqual(status["source_repository"], SOURCE)
        self.assertEqual(status["preview_url"], f"https://alice.github.io/specter-diy-web-simulator/pr/19/{SHA}/")
        self.assertEqual(status["successful_previews"][0]["head_sha"], SHA)
        self.assertIn("artifacts/123", status["firmware_url"])
        self.assertEqual(result["firmware_artifacts_to_prune"], [])

    def test_pr_generated_javascript_is_replaced_by_trusted_runtime(self):
        req = request()
        result = self.apply(req)
        self.assertEqual(result["status"], "success")
        build = self.pages / f"pr/19/{SHA}/builds/{SOURCE}/{SHA}"
        js = (build / "micropython.js").read_bytes()
        self.assertEqual(js, b"trusted-runtime-js")
        info = json.loads((build / "build-info.json").read_text(encoding="utf-8"))
        self.assertEqual(set(info["artifacts"]), {"micropython.js", "micropython.wasm", "micropython.data"})
        self.assertEqual(info["artifacts"]["micropython.js"], {
            "bytes": len(js), "sha256": sha256(js).hexdigest(),
        })
        self.assertEqual(info["trusted_runtime"]["source"]["commit"], BASE_SHA)

    def test_trusted_runtime_provenance_and_hash_must_match(self):
        for tamper in ("wrong-base", "fake-hash"):
            with self.subTest(tamper=tamper):
                shutil.rmtree(self.pages / ".preview-state", ignore_errors=True)
                shutil.rmtree(self.pages / "status", ignore_errors=True)
                result = self.apply(request(), runtime_tamper=tamper)
                self.assertEqual(result["status"], "failure")
                self.assertFalse((self.pages / f"pr/19/{request()['head_sha']}").exists())

    def test_malicious_browser_archive_paths_symlinks_and_executables_fail_closed(self):
        req = request()
        malicious = ["traversal", "absolute", "unexpected", "untrusted-js",
                     "symlink", "nested-symlink", "executable"]
        for kind in malicious:
            with self.subTest(kind=kind):
                shutil.rmtree(self.pages / ".preview-state", ignore_errors=True)
                shutil.rmtree(self.pages / "status", ignore_errors=True)
                if (self.pages / "pr/19").exists():
                    shutil.rmtree(self.pages / "pr/19")
                immutable = self.pages / f"pr/19/{SHA}"
                immutable.mkdir(parents=True)
                (immutable / "old.html").write_text("last successful preview")
                self.apply_malicious_archive(req, kind)
                result = publisher.publish(
                    req, self.pages, self.archive, self.firmware, self.runtime, self.trusted, "success",
                    SERVICE, SIM_SHA, 101, 1,
                    f"https://github.com/{SERVICE}/actions/runs/101/artifacts/123",
                    "token", lambda *_: live_pr(req),
                )
                self.assertEqual(result["status"], "failure")
                self.assertEqual((immutable / "old.html").read_text(), "last successful preview")

    def apply_malicious_archive(self, req, kind):
        browser_archive(self.archive, req, "untrusted-js" if kind == "untrusted-js" else None)
        firmware_artifact(self.firmware, req)
        valid = {}
        with tarfile.open(self.archive, "r:gz") as archive:
            for member in archive.getmembers():
                stream = archive.extractfile(member)
                valid[member.name] = (member, stream.read() if stream else b"")
        if kind in ("traversal", "absolute", "unexpected"):
            member, data = valid.pop("browser/current.json")
            name = {"traversal": "../escape.json", "absolute": "/tmp/escape.json",
                    "unexpected": "browser/evil.sh"}[kind]
            valid[name] = (member, data)
        elif kind in ("symlink", "nested-symlink"):
            target = "browser/current.json" if kind == "symlink" else (
                f"builds/{SOURCE}/{SHA}/micropython.wasm")
            valid.pop(target)
            link = tarfile.TarInfo(target)
            link.type = tarfile.SYMTYPE
            link.linkname = "../../escape"
            valid[target] = (link, b"")
        elif kind == "executable":
            member, data = valid["browser/current.json"]
            member.mode = 0o755
            valid["browser/current.json"] = (member, data)
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, (member, data) in valid.items():
                info = tarfile.TarInfo(name)
                info.type = member.type
                info.linkname = member.linkname
                info.mode = member.mode
                info.size = len(data) if info.isfile() else 0
                archive.addfile(info, BytesIO(data) if info.isfile() else None)

    def test_malformed_archive_and_metadata_hash_repository_request_tampering_fail(self):
        for index, kind in enumerate(("malformed", "wrong-request", "wrong-source", "fake-hash", "wrong-browser-repo")):
            with self.subTest(kind=kind):
                shutil.rmtree(self.pages / ".preview-state", ignore_errors=True)
                shutil.rmtree(self.pages / "status", ignore_errors=True)
                req = request(run_id=101 + index)
                if kind == "malformed":
                    self.archive.write_bytes(b"not a tar archive")
                    firmware_artifact(self.firmware, req)
                else:
                    browser_archive(self.archive, req, kind)
                    firmware_artifact(self.firmware, req)
                result = publisher.publish(
                    req, self.pages, self.archive, self.firmware, self.runtime, self.trusted, "success",
                    SERVICE, SIM_SHA, 101 + index, 1,
                    f"https://github.com/{SERVICE}/actions/runs/{101 + index}/artifacts/123",
                    "token", lambda *_: live_pr(req),
                )
                self.assertEqual(result["status"], "failure")

    def test_firmware_sha_and_hash_mismatch_are_rejected(self):
        for index, kind in enumerate(("wrong-sha", "fake-hash", "unexpected")):
            with self.subTest(kind=kind):
                shutil.rmtree(self.pages / ".preview-state", ignore_errors=True)
                shutil.rmtree(self.pages / "status", ignore_errors=True)
                req = request(run_id=101 + index)
                browser_archive(self.archive, req)
                firmware_artifact(self.firmware, req, kind)
                result = publisher.publish(
                    req, self.pages, self.archive, self.firmware, self.runtime, self.trusted, "success",
                    SERVICE, SIM_SHA, 101 + index, 1,
                    f"https://github.com/{SERVICE}/actions/runs/{101 + index}/artifacts/123",
                    "token", lambda *_: live_pr(req),
                )
                self.assertEqual(result["status"], "failure")

    def test_failed_newer_build_keeps_latest_successful_preview_online(self):
        first = request()
        self.assertEqual(self.apply(first)["status"], "success")
        second = request(sha="c" * 40, updated="2026-10-01T12:00:00.000000Z", run_id=102)
        third = request(sha="d" * 40, updated="2026-10-02T12:00:00.000000Z", run_id=103)
        browser_archive(self.archive, second)
        firmware_artifact(self.firmware, second)
        result = publisher.publish(
            second, self.pages, self.archive, self.firmware, self.runtime, self.trusted, "success",
            SERVICE, SIM_SHA, 202, 1,
            f"https://github.com/{SERVICE}/actions/runs/202/artifacts/124",
            "token", lambda *_: live_pr(second),
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["firmware_artifacts_to_prune"], [
            {"workflow_run_id": 101, "artifact_id": 123},
        ])
        result = publisher.publish(
            third, self.pages, self.archive, self.firmware, self.runtime, self.trusted, "failure",
            SERVICE, SIM_SHA, 203, 1, "", "token", lambda *_: live_pr(third),
        )
        self.assertEqual(result["status"], "failure")
        self.assertFalse((self.pages / f"pr/19/{SHA}").exists())
        self.assertTrue((self.pages / f"pr/19/{second['head_sha']}/index.html").is_file())
        self.assertFalse((self.pages / f"pr/19/{third['head_sha']}").exists())
        state = json.loads((self.pages / ".preview-state/pr/19.json").read_text())
        self.assertEqual([entry["head_sha"] for entry in state["successful_previews"]],
                         [second["head_sha"]])
        self.assertIn("artifacts/124", state["successful_previews"][0]["firmware_url"])
        status = json.loads((self.pages / "status/pr/19.json").read_text())
        self.assertEqual(status["status"], "failure")
        self.assertEqual(status["preview_url"], state["successful_previews"][0]["preview_url"])

    def test_successful_new_commit_removes_every_older_page_for_the_pr(self):
        a = request()
        self.apply(a)
        b = request(sha="c" * 40, updated="2026-10-01T12:00:00.000000Z", run_id=102)
        browser_archive(self.archive, b)
        firmware_artifact(self.firmware, b)
        result_b = publisher.publish(b, self.pages, self.archive, self.firmware, self.runtime, self.trusted,
                                     "success", SERVICE, SIM_SHA, 202, 1,
                                     f"https://github.com/{SERVICE}/actions/runs/202/artifacts/124",
                                     "token", lambda *_: live_pr(b))
        self.assertEqual(result_b["firmware_artifacts_to_prune"], [
            {"workflow_run_id": 101, "artifact_id": 123},
        ])
        c = request(sha="d" * 40, updated="2026-10-02T12:00:00.000000Z", run_id=103)
        browser_archive(self.archive, c)
        firmware_artifact(self.firmware, c)
        result_c = publisher.publish(c, self.pages, self.archive, self.firmware, self.runtime, self.trusted,
                                     "success", SERVICE, SIM_SHA, 203, 1,
                                     f"https://github.com/{SERVICE}/actions/runs/203/artifacts/125",
                                     "token", lambda *_: live_pr(c))
        self.assertEqual(result_c["firmware_artifacts_to_prune"], [
            {"workflow_run_id": 202, "artifact_id": 124},
        ])
        state = json.loads((self.pages / ".preview-state/pr/19.json").read_text())
        self.assertEqual([item["head_sha"] for item in state["successful_previews"]],
                         [c["head_sha"]])
        self.assertIn("artifacts/125", state["successful_previews"][0]["firmware_url"])
        for sha in (a["head_sha"], b["head_sha"]):
            self.assertFalse((self.pages / f"pr/19/{sha}").exists())
        self.assertTrue((self.pages / f"pr/19/{c['head_sha']}/index.html").is_file())

    def test_existing_commit_url_is_never_replaced_on_a_repeat_build(self):
        first = request(run_id=100)
        self.assertEqual(self.apply(first, run_id=101)["status"], "success")
        preview = self.pages / f"pr/19/{SHA}"
        original = (preview / "index.html").read_bytes()
        (self.trusted / "index.html").write_text("changed trusted shell", encoding="utf-8")
        retry = request(run_id=101)
        browser_archive(self.archive, retry)
        firmware_artifact(self.firmware, retry)
        result = publisher.publish(
            retry, self.pages, self.archive, self.firmware, self.runtime, self.trusted, "success",
            SERVICE, SIM_SHA, 102, 1,
            f"https://github.com/{SERVICE}/actions/runs/102/artifacts/123",
            "token", lambda *_: live_pr(retry),
        )
        self.assertEqual(result["status"], "failure")
        self.assertEqual((preview / "index.html").read_bytes(), original)

    def test_first_new_layout_migrates_a_verified_legacy_preview_to_its_sha_url(self):
        old = request()
        preview = self.pages / "pr/19"
        build = preview / f"builds/{SOURCE}/{SHA}"
        build.mkdir(parents=True)
        (preview / "index.html").write_text("old successful browser")
        (build / "build-info.json").write_text(json.dumps({
            "source": {"repository": SOURCE, "commit": SHA},
            "simulator": {"repository": SERVICE, "commit": SIM_SHA},
        }))
        old_state = {
            "latest_source_updated_at": old["source_updated_at"],
            "latest_source_sha": SHA,
            "latest_request_id": old["request_id"],
            "latest_action": "build",
            "workflow_run_id": 101,
            "run_attempt": 1,
            "status": "success",
        }
        publisher._write_json(self.pages, self.pages / ".preview-state/pr/19.json", old_state)
        publisher._write_json(self.pages, self.pages / "status/pr/19.json", {
            "status": "success", "request_id": old["request_id"], "source_sha": SHA,
            "source_repository": SOURCE,
            "preview_url": "https://alice.github.io/specter-diy-web-simulator/pr/19/",
            "firmware_url": f"https://github.com/{SERVICE}/actions/runs/101/artifacts/123",
            "run_url": f"https://github.com/{SERVICE}/actions/runs/101",
        })
        newer = request(sha="c" * 40, updated="2026-10-01T12:00:00.000000Z", run_id=102)
        result = publisher.publish(
            newer, self.pages, self.archive, self.firmware, self.runtime, self.trusted, "failure",
            SERVICE, SIM_SHA, 202, 1, "", "token", lambda *_: live_pr(newer),
        )
        self.assertEqual(result["status"], "failure")
        self.assertEqual((self.pages / f"pr/19/{SHA}/index.html").read_text(), "old successful browser")
        state = json.loads((self.pages / ".preview-state/pr/19.json").read_text())
        self.assertEqual(state["successful_previews"][0]["head_sha"], SHA)

    def test_old_completion_cannot_overwrite_newer_success_or_close_tombstone(self):
        newest = request(sha="c" * 40, updated="2026-10-01T12:00:00.000000Z", run_id=102)
        browser_archive(self.archive, newest)
        firmware_artifact(self.firmware, newest)
        publisher.publish(newest, self.pages, self.archive, self.firmware, self.runtime, self.trusted,
                          "success", SERVICE, SIM_SHA, 202, 1,
                          f"https://github.com/{SERVICE}/actions/runs/202/artifacts/123",
                          "token", lambda *_: live_pr(newest))
        preview_file = self.pages / f"pr/19/{newest['head_sha']}/index.html"
        self.assertTrue(preview_file.is_file())
        older = request(sha=SHA, updated=UPDATED, run_id=101)
        before = (self.pages / "status/pr/19.json").read_text()
        result = self.apply(older, run_id=101)
        self.assertEqual(result["status"], "stale")
        self.assertEqual((self.pages / "status/pr/19.json").read_text(), before)
        self.assertTrue(preview_file.is_file())

        closed = request(sha="c" * 40, updated="2026-10-02T12:00:00.000000Z",
                         action="delete", run_id=103)
        (self.pages / "pr/19/a" / "index.html").parent.mkdir(parents=True)
        (self.pages / "pr/19/a" / "index.html").write_text("older immutable preview")
        deleted = publisher.publish(closed, self.pages, self.archive, self.firmware,
                                    self.runtime, self.trusted, "deleted", SERVICE, SIM_SHA,
                                    203, 1, "", "token", lambda *_: live_pr(closed, "closed"))
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(deleted["firmware_artifacts_to_prune"], [
            {"workflow_run_id": 202, "artifact_id": 123},
        ])
        self.assertFalse((self.pages / "pr/19").exists())
        self.assertFalse((self.pages / "status/pr/19.json").exists())
        old_again = self.apply(older, run_id=101)
        self.assertEqual(old_again["status"], "stale")
        state = json.loads((self.pages / ".preview-state/pr/19.json").read_text())
        self.assertEqual(state["latest_action"], "delete")
        self.assertEqual(state["successful_previews"], [])

    def test_equal_event_timestamp_uses_remote_run_order_and_other_prs_survive(self):
        preserved = self.pages / "pr/99"
        preserved.mkdir(parents=True)
        (preserved / "index.html").write_text("other PR")
        first = request(run_id=100)
        browser_archive(self.archive, first)
        firmware_artifact(self.firmware, first)
        publisher.publish(first, self.pages, self.archive, self.firmware, self.runtime, self.trusted,
                          "success", SERVICE, SIM_SHA, 301, 1,
                          f"https://github.com/{SERVICE}/actions/runs/301/artifacts/123",
                          "token", lambda *_: live_pr(first))
        second = request(run_id=101)
        browser_archive(self.archive, second)
        firmware_artifact(self.firmware, second)
        result = publisher.publish(second, self.pages, self.archive, self.firmware, self.runtime, self.trusted,
                                   "success", SERVICE, SIM_SHA, 302, 1,
                                   f"https://github.com/{SERVICE}/actions/runs/302/artifacts/123",
                                   "token", lambda *_: live_pr(second))
        self.assertEqual(result["status"], "success")
        self.assertTrue(preserved.is_dir())
        stale = publisher.publish(first, self.pages, self.archive, self.firmware, self.runtime, self.trusted,
                                  "success", SERVICE, SIM_SHA, 301, 1,
                                  f"https://github.com/{SERVICE}/actions/runs/301/artifacts/123",
                                  "token", lambda *_: live_pr(first))
        self.assertEqual(stale["status"], "stale")

    def test_symlinked_firmware_and_trusted_shell_are_rejected(self):
        req = request()
        browser_archive(self.archive, req)
        firmware_artifact(self.firmware, req)
        firmware_bin, firmware_hex = publisher.firmware_filenames(req["pr_number"], req["head_sha"])
        (self.firmware / firmware_hex).unlink()
        try:
            (self.firmware / firmware_hex).symlink_to(self.firmware / firmware_bin)
        except OSError:
            self.skipTest("Creating symlinks requires privileges on this Windows host")
        result = publisher.publish(
            req, self.pages, self.archive, self.firmware, self.runtime, self.trusted, "success",
            SERVICE, SIM_SHA, 101, 1,
            f"https://github.com/{SERVICE}/actions/runs/101/artifacts/123",
            "token", lambda *_: live_pr(req),
        )
        self.assertEqual(result["status"], "failure")


if __name__ == "__main__":
    unittest.main()
