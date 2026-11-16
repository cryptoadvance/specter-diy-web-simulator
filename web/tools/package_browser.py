#!/usr/bin/env python3
"""Package only the expected generated browser data as a deterministic tar."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
import json
import os
import re
import tarfile


BUILD_ARTIFACTS = ("micropython.js", "micropython.wasm", "micropython.data")
ARTIFACTS = ("micropython.wasm", "micropython.data")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or unsafe browser file: {path}")
    return path.read_bytes()


def _assert_no_symlink_path(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Browser path escaped simulator web root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink in browser output path")


def package(web: Path, output: Path, metadata: dict) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", metadata["head_repository"]):
        raise ValueError("Invalid source repository")
    if not re.fullmatch(r"[a-f0-9]{40}", metadata["head_sha"]):
        raise ValueError("Invalid source SHA")
    if not SHA_RE.fullmatch(metadata["base_sha"]):
        raise ValueError("Invalid base SHA")
    if not isinstance(metadata["base_ref"], str) or not metadata["base_ref"] or len(metadata["base_ref"]) > 255:
        raise ValueError("Invalid base ref")
    _assert_no_symlink_path(web, web / "browser/current.json")
    pointer = json.loads(_read_regular(web / "browser/current.json"))
    build_rel = pointer.get("build", "")
    expected_rel = f"builds/{metadata['head_repository']}/{metadata['head_sha']}/"
    if build_rel != expected_rel:
        raise ValueError("Browser pointer does not identify the dispatched source")
    if not re.fullmatch(r"builds/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[a-f0-9]{40}/", build_rel):
        raise ValueError("Invalid browser build pointer")
    build = web / PurePosixPath(build_rel)
    _assert_no_symlink_path(web, build)
    resolved = build.resolve()
    if not resolved.is_relative_to(web.resolve()):
        raise ValueError("Browser build escaped the simulator web directory")
    build_info = json.loads(_read_regular(build / "build-info.json"))
    if build_info.get("source", {}).get("repository", "").lower() != metadata["head_repository"].lower():
        raise ValueError("Browser provenance has the wrong source repository")
    if build_info.get("source", {}).get("commit") != metadata["head_sha"]:
        raise ValueError("Browser provenance has the wrong source SHA")
    if build_info.get("simulator", {}).get("repository", "").lower() != metadata["simulator_repository"].lower():
        raise ValueError("Browser provenance has the wrong simulator repository")
    if build_info.get("simulator", {}).get("commit") != metadata["simulator_sha"]:
        raise ValueError("Browser provenance has the wrong simulator SHA")
    if set(build_info.get("artifacts", {})) != set(BUILD_ARTIFACTS):
        raise ValueError("Unexpected browser artifact list")

    # The PR build is an untrusted producer. Its generated Emscripten JavaScript
    # must not cross the artifact boundary; only the data and WASM do.
    artifacts = build_info["artifacts"]
    for name in BUILD_ARTIFACTS:
        data = _read_regular(build / name)
        record = artifacts[name]
        if record.get("bytes") != len(data) or record.get("sha256") != sha256(data).hexdigest():
            raise ValueError(f"Browser artifact hash mismatch: {name}")

    packaged_artifacts = {name: artifacts[name] for name in ARTIFACTS}
    artifact_set = sha256("".join(packaged_artifacts[name]["sha256"] for name in sorted(ARTIFACTS)).encode()).hexdigest()
    packaged_info = dict(build_info)
    packaged_info["artifacts"] = packaged_artifacts
    packaged_info["artifact_set_sha256"] = artifact_set
    packaged_pointer = dict(pointer)
    packaged_pointer["version"] = artifact_set[:16]
    entries: dict[str, bytes] = {
        "browser/current.json": (json.dumps(packaged_pointer, sort_keys=True, indent=2) + "\n").encode(),
        build_rel + "build-info.json": (json.dumps(packaged_info, sort_keys=True, indent=2) + "\n").encode(),
    }
    for name in ARTIFACTS:
        entries[build_rel + name] = _read_regular(build / name)

    file_records = {
        name: {"bytes": len(data), "sha256": sha256(data).hexdigest()}
        for name, data in sorted(entries.items())
    }
    manifest = {
        "schema": 1,
        "kind": "browser-preview",
        "base_repository": metadata["base_repository"],
        "base_sha": metadata["base_sha"],
        "base_ref": metadata["base_ref"],
        "source_repository": metadata["head_repository"],
        "source_sha": metadata["head_sha"],
        "pr_number": metadata["pr_number"],
        "request_id": metadata["request_id"],
        "source_updated_at": metadata["source_updated_at"],
        "simulator_repository": metadata["simulator_repository"],
        "simulator_sha": metadata["simulator_sha"],
        "build_path": build_rel,
        "files": file_records,
    }
    entries["manifest.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for name, data in sorted(entries.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, BytesIO(data))
    return manifest


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
        "base_sha": os.environ["BASE_SHA"],
        "base_ref": os.environ["BASE_REF"],
    }
    package(Path(os.environ["SIMULATOR_WEB_DIR"]),
            Path(os.environ["BROWSER_ARCHIVE"]), metadata)


if __name__ == "__main__":
    main()
