#!/usr/bin/env python3
"""Package only the JavaScript runtime built from the validated PR base."""
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "browser"))
from verify_build import verify  # noqa: E402


SHA_RE = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_RUNTIME_SIZE = 20_000_000


def package(web: Path, output: Path, metadata: dict) -> dict:
    for key in ("base_repository", "simulator_repository"):
        if not REPOSITORY_RE.fullmatch(metadata[key]):
            raise ValueError(f"Invalid {key}")
    for key in ("base_sha", "simulator_sha"):
        if not SHA_RE.fullmatch(metadata[key]):
            raise ValueError(f"Invalid {key}")
    if not isinstance(metadata["base_ref"], str) or not metadata["base_ref"] or len(metadata["base_ref"]) > 255:
        raise ValueError("Invalid base ref")

    verify(
        web,
        expected_sha=metadata["base_sha"],
        expected_repo=metadata["base_repository"],
        expected_simulator_sha=metadata["simulator_sha"],
        expected_simulator_repo=metadata["simulator_repository"],
    )
    pointer = json.loads((web / "browser/current.json").read_text(encoding="utf-8"))
    build = web / pointer["build"]
    js_path = build / "micropython.js"
    if js_path.is_symlink() or not js_path.is_file():
        raise ValueError("Trusted JavaScript runtime is missing or unsafe")
    js = js_path.read_bytes()
    if not js or len(js) > MAX_RUNTIME_SIZE:
        raise ValueError("Trusted JavaScript runtime has an invalid size")

    if output.is_symlink():
        raise ValueError("Trusted runtime output path is unsafe")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Trusted runtime output directory is not empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "micropython.js").write_bytes(js)
    manifest = {
        "schema": 1,
        "kind": "trusted-browser-runtime",
        "base_repository": metadata["base_repository"],
        "base_sha": metadata["base_sha"],
        "base_ref": metadata["base_ref"],
        "simulator_repository": metadata["simulator_repository"],
        "simulator_sha": metadata["simulator_sha"],
        "files": {
            "micropython.js": {"bytes": len(js), "sha256": sha256(js).hexdigest()},
        },
    }
    (output / "runtime.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    package(
        Path(os.environ["SIMULATOR_WEB_DIR"]),
        Path(os.environ["TRUSTED_RUNTIME_DIR"]),
        {
            "base_repository": os.environ["BASE_REPOSITORY"],
            "base_sha": os.environ["BASE_SHA"],
            "base_ref": os.environ["BASE_REF"],
            "simulator_repository": os.environ["SIMULATOR_REPOSITORY"],
            "simulator_sha": os.environ["SIMULATOR_SHA"],
        },
    )


if __name__ == "__main__":
    main()
