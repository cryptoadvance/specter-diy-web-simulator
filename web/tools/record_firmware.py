#!/usr/bin/env python3
"""Stage the exact firmware files and provenance for a preview artifact."""
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import shutil
import subprocess

from firmware_artifact_names import firmware_artifact_name, firmware_filenames


def record(source: Path, output: Path, metadata: dict) -> dict:
    actual_sha = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual_sha != metadata["head_sha"]:
        raise ValueError("Firmware checkout does not match the dispatched source SHA")
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    if (source / "bin").is_symlink():
        raise ValueError("Firmware output directory must not be a symlink")
    names = firmware_filenames(metadata["pr_number"], metadata["head_sha"])
    for source_name, target_name in zip(("specter-diy.bin", "specter-diy.hex"), names):
        source_file = source / "bin" / source_name
        if source_file.is_symlink() or not source_file.is_file() or source_file.stat().st_size == 0:
            raise ValueError(f"Missing or unsafe firmware artifact: {source_name}")
        target = output / target_name
        shutil.copyfile(source_file, target)
        data = target.read_bytes()
        hashes[target_name] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
    provenance = {
        "schema": 1,
        "kind": "firmware",
        "base_repository": metadata["base_repository"],
        "source_repository": metadata["head_repository"],
        "source_sha": metadata["head_sha"],
        "pr_number": metadata["pr_number"],
        "request_id": metadata["request_id"],
        "source_updated_at": metadata["source_updated_at"],
        "simulator_repository": metadata["simulator_repository"],
        "simulator_sha": metadata["simulator_sha"],
        "files": hashes,
    }
    (output / "source.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def main() -> None:
    metadata = {
        "base_repository": os.environ["BASE_REPOSITORY"],
        "head_repository": os.environ["HEAD_REPOSITORY"],
        "head_sha": os.environ["HEAD_SHA"],
        "pr_number": int(os.environ["PR_NUMBER"]),
        "request_id": os.environ["REQUEST_ID"],
        "source_updated_at": os.environ["SOURCE_UPDATED_AT"],
        "simulator_repository": os.environ["SIMULATOR_REPOSITORY"],
        "simulator_sha": os.environ["SIMULATOR_SHA"],
    }
    if not re.fullmatch(r"[a-f0-9]{40}", metadata["simulator_sha"]):
        raise ValueError("Invalid simulator SHA")
    record(Path(os.environ["SPECTER_SOURCE_DIR"]), Path(os.environ["FIRMWARE_ARTIFACT_DIR"]), metadata)
    name = firmware_artifact_name(
        metadata["pr_number"], metadata["head_sha"],
        int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
    )
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"firmware_name={name}\n")


if __name__ == "__main__":
    main()
