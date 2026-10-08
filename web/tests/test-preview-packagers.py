#!/usr/bin/env python3
"""Package only generated assets tied to the request's exact source SHA."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import sys
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from package_browser import package
from record_firmware import record
from firmware_artifact_names import firmware_filenames


BASE = "alice/specter-diy"
SOURCE = "bob/specter-diy"
SERVICE = "alice/specter-diy-web-simulator"
SIM_SHA = "b" * 40
BUILD_ARTIFACTS = ("micropython.js", "micropython.wasm", "micropython.data")
ARTIFACTS = ("micropython.wasm", "micropython.data")
BASE_SHA = "d" * 40


class PreviewPackagerTests(unittest.TestCase):
    def test_browser_package_has_exact_files_and_provenance(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "web"
            sha = "a" * 40
            build_path = f"builds/{SOURCE}/{sha}/"
            build = root / build_path
            build.mkdir(parents=True)
            artifacts = {}
            for name in BUILD_ARTIFACTS:
                data = f"{name}:{sha}".encode()
                (build / name).write_bytes(data)
                artifacts[name] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
            artifact_set = sha256("".join(artifacts[name]["sha256"] for name in sorted(artifacts)).encode()).hexdigest()
            (build / "build-info.json").write_text(json.dumps({
                "source": {"repository": SOURCE, "commit": sha},
                "simulator": {"repository": SERVICE, "commit": SIM_SHA},
                "artifacts": artifacts, "artifact_set_sha256": artifact_set,
            }))
            (root / "browser").mkdir()
            (root / "browser/current.json").write_text(json.dumps({
                "build": build_path, "version": artifact_set[:16],
            }))
            metadata = {"base_repository": BASE, "head_repository": SOURCE,
                        "base_sha": BASE_SHA, "base_ref": "main",
                        "head_sha": sha, "pr_number": 12, "request_id": f"specter-pr-12-{sha}-99-1",
                        "source_updated_at": "2026-09-30T12:00:00.000000Z",
                        "simulator_repository": SERVICE, "simulator_sha": SIM_SHA}
            archive = Path(temp) / "browser.tar.gz"
            manifest = package(root, archive, metadata)
            self.assertEqual(manifest["source_sha"], sha)
            self.assertEqual(manifest["base_sha"], BASE_SHA)
            self.assertEqual(manifest["request_id"], metadata["request_id"])
            with tarfile.open(archive, "r:gz") as tar:
                names = set(tar.getnames())
            self.assertEqual(names, {
                "manifest.json", "browser/current.json", build_path + "build-info.json",
                *(build_path + name for name in ARTIFACTS),
            })
            self.assertNotIn(build_path + "micropython.js", names)
            with tarfile.open(archive, "r:gz") as tar:
                packaged_info = json.load(tar.extractfile(build_path + "build-info.json"))
            self.assertEqual(set(packaged_info["artifacts"]), set(ARTIFACTS))

    def test_firmware_record_binds_both_binaries_to_exact_checkout(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
            (source / "bin").mkdir()
            for name in ("specter-diy.bin", "specter-diy.hex"):
                (source / "bin" / name).write_bytes(name.encode())
            subprocess.run(["git", "-C", str(source), "add", "bin"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
            sha = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
            metadata = {"base_repository": BASE, "head_repository": SOURCE, "head_sha": sha,
                        "pr_number": 12, "request_id": f"specter-pr-12-{sha}-99-1",
                        "source_updated_at": "2026-09-30T12:00:00.000000Z",
                        "simulator_repository": SERVICE, "simulator_sha": SIM_SHA}
            output = Path(temp) / "firmware-artifact"
            provenance = record(source, output, metadata)
            self.assertEqual(provenance["source_sha"], sha)
            names = firmware_filenames(12, sha)
            self.assertEqual(set(provenance["files"]), set(names))
            for original, renamed in zip(("specter-diy.bin", "specter-diy.hex"), names):
                self.assertEqual((output / renamed).read_bytes(), original.encode())


if __name__ == "__main__":
    unittest.main()
