#!/usr/bin/env python3
"""Compose trusted Emscripten JavaScript with untrusted preview data files."""
from hashlib import sha256
from pathlib import Path
import json
import re
import sys


def replace_glue(root: Path, trusted_js: Path, runtime_provenance: dict | None = None):
    root = root.resolve()
    if trusted_js.is_symlink() or not trusted_js.is_file():
        raise ValueError("Trusted Emscripten JavaScript artifact missing")
    js = trusted_js.read_bytes()
    if not js or len(js) > 20_000_000:
        raise ValueError("Invalid trusted Emscripten JavaScript")
    pointer_path = root / "browser/current.json"
    if pointer_path.is_symlink() or not pointer_path.is_file():
        raise ValueError("Build pointer missing")
    pointer = json.loads(pointer_path.read_text())
    relative = pointer.get("build")
    if not isinstance(relative, str) or not re.fullmatch(
            r"builds/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[a-f0-9]{40}/", relative):
        raise ValueError("Invalid build pointer")
    build = (root / relative).resolve()
    if not build.is_relative_to(root) or not build.is_dir():
        raise ValueError("Build escaped staging directory")
    manifest_path = build / "build-info.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Build manifest missing")
    manifest = json.loads(manifest_path.read_text())
    artifacts = manifest.get("artifacts")
    data_names = ("micropython.wasm", "micropython.data")
    if not isinstance(artifacts, dict) or set(artifacts) != set(data_names):
        raise ValueError("Unexpected build artifacts")
    for name in data_names:
        path = build / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid build artifact: {name}")
    js_path = build / "micropython.js"
    if js_path.exists() or js_path.is_symlink():
        raise ValueError("Untrusted JavaScript was included in the browser payload")
    js_path.write_bytes(js)
    artifacts["micropython.js"] = {"bytes": len(js), "sha256": sha256(js).hexdigest()}
    names = ("micropython.js", *data_names)
    for name in data_names:
        data = (build / name).read_bytes()
        artifacts[name] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
    if runtime_provenance is not None:
        manifest["trusted_runtime"] = runtime_provenance
    artifact_set = sha256("".join(artifacts[name]["sha256"] for name in sorted(names)).encode()).hexdigest()
    manifest["artifact_set_sha256"] = artifact_set
    pointer["version"] = artifact_set[:16]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    pointer_path.write_text(json.dumps(pointer, indent=2) + "\n")


if __name__ == "__main__":
    replace_glue(Path(sys.argv[1]), Path(sys.argv[2]))
