#!/usr/bin/env python3
"""Ensure downloaded PR firmware has meaningful ZIP and internal file names."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from firmware_artifact_names import firmware_artifact_name, firmware_base_name, firmware_filenames
import record_firmware


SHA = "47e6588891f34eb907c23501bb61bb76fc71af50"
SIM_SHA = "c" * 40


def metadata():
    return {
        "base_repository": "cryptoadvance/specter-diy",
        "head_repository": "schnuartz-ai/specter-diy",
        "head_sha": SHA,
        "pr_number": 440,
        "request_id": "specter-pr-440-test",
        "source_updated_at": "2026-10-08T08:00:00Z",
        "simulator_repository": "cryptoadvance/specter-diy-web-simulator",
        "simulator_sha": SIM_SHA,
    }


class FirmwareArtifactNamesTests(unittest.TestCase):
    def test_exact_requested_download_and_inner_filenames(self):
        basename = "specter-firmware_PR-440_47e6588891f3"
        self.assertEqual(firmware_base_name(440, SHA), basename)
        self.assertEqual(firmware_artifact_name(440, SHA), basename)
        self.assertEqual(firmware_artifact_name(440, SHA, 2), basename + "_attempt-2")
        self.assertEqual(firmware_filenames(440, SHA), (basename + ".bin", basename + ".hex"))

    def test_rejects_untrusted_filename_parameters(self):
        for pr_number, head_sha, attempt in (
            (0, SHA, 1), (True, SHA, 1), (440, "../../wrong", 1),
            (440, SHA.upper(), 1), (440, SHA, 0), (440, SHA, True),
        ):
            with self.subTest(pr_number=pr_number, head_sha=head_sha, attempt=attempt):
                with self.assertRaises(ValueError):
                    firmware_artifact_name(pr_number, head_sha, attempt)

    def test_stage_firmware_and_output_download_name(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            (source / "bin").mkdir(parents=True)
            original = {".bin": b"firmware binary", ".hex": b"firmware hex"}
            for extension, data in original.items():
                (source / "bin" / ("specter-diy" + extension)).write_bytes(data)
            staged = root / "firmware"
            output = root / "github-output"
            data = metadata()
            env = {
                "BASE_REPOSITORY": data["base_repository"],
                "HEAD_REPOSITORY": data["head_repository"],
                "HEAD_SHA": data["head_sha"],
                "PR_NUMBER": str(data["pr_number"]),
                "REQUEST_ID": data["request_id"],
                "SOURCE_UPDATED_AT": data["source_updated_at"],
                "SIMULATOR_REPOSITORY": data["simulator_repository"],
                "SIMULATOR_SHA": data["simulator_sha"],
                "SPECTER_SOURCE_DIR": str(source),
                "FIRMWARE_ARTIFACT_DIR": str(staged),
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_OUTPUT": str(output),
            }
            with patch.dict(os.environ, env), patch.object(
                record_firmware.subprocess, "check_output", return_value=SHA + "\n"
            ):
                record_firmware.main()
            base = firmware_base_name(440, SHA)
            self.assertEqual(output.read_text(), "firmware_name=" + base + "\n")
            self.assertEqual({p.name for p in staged.iterdir()},
                             {base + ".bin", base + ".hex", "source.json"})
            provenance = json.loads((staged / "source.json").read_text())
            self.assertEqual(provenance["source_sha"], SHA)
            self.assertEqual(set(provenance["files"]), {base + ".bin", base + ".hex"})
            for extension, contents in original.items():
                self.assertEqual((staged / (base + extension)).read_bytes(), contents)
                self.assertEqual(provenance["files"][base + extension]["sha256"],
                                 sha256(contents).hexdigest())


if __name__ == "__main__":
    unittest.main()
