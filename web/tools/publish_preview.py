#!/usr/bin/env python3
"""Apply a preview request to the trusted persistent Pages tree.

The browser archive and firmware artifact are untrusted input. This program
only parses and copies allowlisted regular files; it never imports or executes
anything from either artifact.
"""
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
import json
import os
import re
import shutil
import sys
import tarfile

from validate_preview_request import fetch_pull, parse_time, canonical_time
from preview_csp import restrict_preview_csp
from firmware_artifact_names import firmware_filenames
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser"))
from replace_glue import replace_glue


ARTIFACTS = ("micropython.wasm", "micropython.data")
MAX_BROWSER_ARCHIVE = 160 * 1024 * 1024
MAX_FIRMWARE_FILE = 32 * 1024 * 1024
MAX_RUNTIME_SIZE = 20_000_000
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def _json_object(data: bytes | str) -> dict:
    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key in artifact JSON")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("Invalid JSON constant")

    value = json.loads(data, object_pairs_hook=no_duplicate_keys, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Artifact JSON must contain an object")
    return value


def _assert_no_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise ValueError(f"Symlink is not allowed: {root}")
    if not root.exists():
        return
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories + files:
            if (current_path / name).is_symlink():
                raise ValueError("Symlinks are not allowed in the Pages tree")


def _ensure_safe_parent(root: Path, parent: Path) -> None:
    root = root.resolve()
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ValueError("Publication path escaped Pages tree") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink in publication path")
        if current.exists() and not current.is_dir():
            raise ValueError("Non-directory in publication path")
        current.mkdir(exist_ok=True)


def _remove_tree(root: Path, target: Path) -> None:
    if target.is_symlink():
        raise ValueError("Refusing to remove a symlink from the Pages tree")
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError("Expected a directory in the Pages tree")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Removal target escaped Pages tree")
    shutil.rmtree(target)


def _remove_superseded_previews(pages: Path, pr_number: int, keep_sha: str) -> None:
    """Keep only this PR's newest successful immutable preview online."""
    root = pages / "pr" / str(pr_number)
    if root.is_symlink():
        raise ValueError("Refusing to remove a symlink from the Pages tree")
    if not root.exists():
        return
    if not root.is_dir():
        raise ValueError("Expected a PR preview directory")
    _assert_no_symlinks(root)
    for child in root.iterdir():
        if child.name == keep_sha:
            continue
        if child.is_dir():
            _remove_tree(pages, child)
        elif child.is_file():
            child.unlink()
        else:
            raise ValueError("Unexpected entry in the PR preview directory")
    try:
        root.rmdir()
    except OSError:
        pass


def _write_json(root: Path, path: Path, value: dict) -> None:
    _ensure_safe_parent(root, path.parent)
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlink in the Pages tree")
    temporary = path.with_name(path.name + ".tmp")
    if temporary.is_symlink():
        raise ValueError("Refusing to replace a symlink in the Pages tree")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _expected_browser_paths(request: dict) -> set[str]:
    build_path = f"builds/{request['head_repository']}/{request['head_sha']}/"
    return {
        "manifest.json",
        "browser/current.json",
        build_path + "build-info.json",
        *(build_path + name for name in ARTIFACTS),
    }


def _safe_extract_browser(archive_path: Path, destination: Path, request: dict,
                          simulator_repository: str, simulator_sha: str) -> dict:
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("Missing browser artifact archive")
    if archive_path.stat().st_size > MAX_BROWSER_ARCHIVE:
        raise ValueError("Browser artifact archive exceeds size limit")
    expected_paths = _expected_browser_paths(request)
    entries: dict[str, bytes] = {}
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) != len(expected_paths):
                raise ValueError("Unexpected number of files in browser archive")
            total = 0
            for member in members:
                name = member.name
                posix = PurePosixPath(name)
                if ("\\" in name or posix.is_absolute() or
                        any(part in ("", ".", "..") for part in posix.parts) or
                        re.match(r"^[A-Za-z]:", name)):
                    raise ValueError("Unsafe path in browser archive")
                if name not in expected_paths:
                    raise ValueError("Unexpected browser artifact path")
                if name in entries:
                    raise ValueError("Duplicate path in browser archive")
                if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
                    raise ValueError("Only regular files are allowed in browser archive")
                if member.mode & 0o111:
                    raise ValueError("Executable file mode is not allowed in browser archive")
                if member.size < 0 or member.size > MAX_BROWSER_ARCHIVE:
                    raise ValueError("Invalid file size in browser archive")
                total += member.size
                if total > MAX_BROWSER_ARCHIVE:
                    raise ValueError("Expanded browser archive exceeds size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Unreadable browser archive member")
                data = source.read(member.size + 1)
                if len(data) != member.size:
                    raise ValueError("Browser archive member size mismatch")
                entries[name] = data
    except (tarfile.TarError, OSError) as exc:
        raise ValueError("Malformed browser archive") from exc
    if set(entries) != expected_paths:
        raise ValueError("Browser archive is missing required files")

    manifest = _json_object(entries["manifest.json"])
    expected_metadata = {
        "schema": 1,
        "kind": "browser-preview",
        "base_repository": request["base_repository"],
        "base_sha": request["base_sha"],
        "base_ref": request["base_ref"],
        "source_repository": request["head_repository"],
        "source_sha": request["head_sha"],
        "pr_number": request["pr_number"],
        "request_id": request["request_id"],
        "source_updated_at": request["source_updated_at"],
        "simulator_repository": simulator_repository,
        "simulator_sha": simulator_sha,
        "build_path": f"builds/{request['head_repository']}/{request['head_sha']}/",
    }
    for key, expected in expected_metadata.items():
        actual = manifest.get(key)
        if isinstance(actual, str) and isinstance(expected, str):
            if actual.lower() != expected.lower() if key.endswith("repository") else actual != expected:
                raise ValueError(f"Browser provenance mismatch: {key}")
        elif actual != expected:
            raise ValueError(f"Browser provenance mismatch: {key}")

    file_records = manifest.get("files")
    expected_records = expected_paths - {"manifest.json"}
    if not isinstance(file_records, dict) or set(file_records) != expected_records:
        raise ValueError("Browser provenance has an unexpected file list")
    for name, record in file_records.items():
        data = entries[name]
        if (not isinstance(record, dict) or record.get("bytes") != len(data) or
                record.get("sha256") != sha256(data).hexdigest()):
            raise ValueError(f"Browser artifact hash mismatch: {name}")

    pointer = _json_object(entries["browser/current.json"])
    build_rel = expected_metadata["build_path"]
    if pointer.get("build") != build_rel:
        raise ValueError("Browser pointer identifies a different build")
    info_path = f"{build_rel}build-info.json"
    build_info = _json_object(entries[info_path])
    if (build_info.get("source", {}).get("repository", "").lower() != request["head_repository"].lower() or
            build_info.get("source", {}).get("commit") != request["head_sha"]):
        raise ValueError("Browser build provenance does not match the PR")
    if (build_info.get("simulator", {}).get("repository", "").lower() != simulator_repository.lower() or
            build_info.get("simulator", {}).get("commit") != simulator_sha):
        raise ValueError("Browser build used different simulator tooling")
    artifacts = build_info.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACTS):
        raise ValueError("Browser build has an unexpected artifact set")
    artifact_hashes = []
    prefix = build_rel
    for name in sorted(ARTIFACTS):
        data = entries[prefix + name]
        record = artifacts[name]
        digest = sha256(data).hexdigest()
        if record.get("bytes") != len(data) or record.get("sha256") != digest:
            raise ValueError(f"Browser build hash mismatch: {name}")
        artifact_hashes.append(digest)
    artifact_set = sha256("".join(artifact_hashes).encode()).hexdigest()
    if (build_info.get("artifact_set_sha256") != artifact_set or
            pointer.get("version") != artifact_set[:16]):
        raise ValueError("Browser artifact set hash mismatch")

    destination.mkdir(parents=True, exist_ok=True)
    for name, data in entries.items():
        if name == "manifest.json":
            continue
        relative = PurePosixPath(name)
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError("Symlink appeared during browser extraction")
        target.write_bytes(data)
    return manifest


def _validate_firmware(directory: Path, request: dict, simulator_repository: str,
                       simulator_sha: str) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Missing firmware Actions artifact")
    firmware_files = firmware_filenames(request["pr_number"], request["head_sha"])
    expected_names = {*firmware_files, "source.json"}
    actual_names = set()
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink > 1:
            raise ValueError("Firmware artifact contains a symlink or non-file")
        actual_names.add(path.name)
    if actual_names != expected_names:
        raise ValueError("Firmware artifact has an unexpected file set")

    provenance = _json_object((directory / "source.json").read_text(encoding="utf-8"))
    expected = {
        "schema": 1,
        "kind": "firmware",
        "base_repository": request["base_repository"],
        "source_repository": request["head_repository"],
        "source_sha": request["head_sha"],
        "pr_number": request["pr_number"],
        "request_id": request["request_id"],
        "source_updated_at": request["source_updated_at"],
        "simulator_repository": simulator_repository,
        "simulator_sha": simulator_sha,
    }
    for key, value in expected.items():
        actual = provenance.get(key)
        if isinstance(actual, str) and isinstance(value, str):
            if actual.lower() != value.lower() if key.endswith("repository") else actual != value:
                raise ValueError(f"Firmware provenance mismatch: {key}")
        elif actual != value:
            raise ValueError(f"Firmware provenance mismatch: {key}")
    files = provenance.get("files")
    if not isinstance(files, dict) or set(files) != set(firmware_files):
        raise ValueError("Firmware provenance has an unexpected file list")
    for name in firmware_files:
        path = directory / name
        if path.stat().st_size == 0 or path.stat().st_size > MAX_FIRMWARE_FILE:
            raise ValueError("Firmware artifact has an invalid size")
        data = path.read_bytes()
        record = files[name]
        if record.get("bytes") != len(data) or record.get("sha256") != sha256(data).hexdigest():
            raise ValueError(f"Firmware artifact hash mismatch: {name}")
    return provenance


def _validate_trusted_runtime(directory: Path, request: dict,
                              simulator_repository: str, simulator_sha: str) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Missing trusted runtime Actions artifact")
    actual_names = set()
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink > 1:
            raise ValueError("Trusted runtime artifact contains a symlink or non-file")
        actual_names.add(path.name)
    if actual_names != {"micropython.js", "runtime.json"}:
        raise ValueError("Trusted runtime artifact has an unexpected file set")

    runtime_path = directory / "micropython.js"
    if runtime_path.stat().st_size == 0 or runtime_path.stat().st_size > MAX_RUNTIME_SIZE:
        raise ValueError("Trusted JavaScript runtime has an invalid size")
    runtime_manifest_path = directory / "runtime.json"
    if runtime_manifest_path.stat().st_size > 64 * 1024:
        raise ValueError("Trusted runtime manifest exceeds size limit")
    runtime = _json_object(runtime_manifest_path.read_bytes())
    expected = {
        "schema": 1,
        "kind": "trusted-browser-runtime",
        "base_repository": request["base_repository"],
        "base_sha": request["base_sha"],
        "base_ref": request["base_ref"],
        "simulator_repository": simulator_repository,
        "simulator_sha": simulator_sha,
    }
    for key, value in expected.items():
        actual = runtime.get(key)
        if isinstance(actual, str) and isinstance(value, str):
            if actual.lower() != value.lower() if key.endswith("repository") else actual != value:
                raise ValueError(f"Trusted runtime provenance mismatch: {key}")
        elif actual != value:
            raise ValueError(f"Trusted runtime provenance mismatch: {key}")
    files = runtime.get("files")
    if not isinstance(files, dict) or set(files) != {"micropython.js"}:
        raise ValueError("Trusted runtime provenance has an unexpected file list")
    js = runtime_path.read_bytes()
    record = files["micropython.js"]
    digest = sha256(js).hexdigest()
    if (not isinstance(record, dict) or record.get("bytes") != len(js) or
            record.get("sha256") != digest):
        raise ValueError("Trusted JavaScript runtime hash mismatch")
    return {
        "source": {
            "repository": request["base_repository"],
            "commit": request["base_sha"],
            "ref": request["base_ref"],
        },
        "simulator": {"repository": simulator_repository, "commit": simulator_sha},
        "artifact": {"bytes": len(js), "sha256": digest},
    }


def _validate_live_pr(request: dict, token: str, pull_fetcher) -> bool:
    pr = pull_fetcher(request["base_repository"], request["pr_number"], token)
    if int(pr.get("number", -1)) != request["pr_number"]:
        return False
    base = pr.get("base") or {}
    if (base.get("repo") or {}).get("full_name", "").lower() != request["base_repository"].lower():
        return False
    if request["action"] == "build" and (
            base.get("sha") != request["base_sha"] or base.get("ref") != request["base_ref"]):
        return False
    head = pr.get("head") or {}
    if head.get("sha") != request["head_sha"]:
        return False
    live_updated = parse_time(pr.get("updated_at", ""))
    if live_updated < parse_time(request["source_updated_at"]):
        return False
    live_repository = (head.get("repo") or {}).get("full_name", "")
    if request["action"] == "delete":
        return pr.get("state") == "closed" and (
            not live_repository or not request["head_repository"] or
            live_repository.lower() == request["head_repository"].lower())
    return (pr.get("state") == "open" and
            live_repository.lower() == request["head_repository"].lower() and
            head.get("ref") == request["head_ref"])


def _load_state(path: Path) -> dict | None:
    if path.is_symlink():
        raise ValueError("Preview state path is a symlink")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("Invalid preview state record")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        parse_time(state["latest_source_updated_at"])
        if not re.fullmatch(r"[a-f0-9]{40}", state["latest_source_sha"]):
            raise ValueError("Invalid SHA in preview state")
        if not isinstance(state["latest_request_id"], str):
            raise ValueError("Invalid request ID in preview state")
        return state
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid preview state record") from exc


def _is_newer(request: dict, run_id: int, run_attempt: int, state: dict | None) -> bool:
    if state is None:
        return True
    candidate_time = parse_time(request["source_updated_at"])
    state_time = parse_time(state["latest_source_updated_at"])
    if candidate_time != state_time:
        return candidate_time > state_time
    candidate_order = (run_id, run_attempt)
    previous_order = (int(state.get("workflow_run_id", 0)), int(state.get("run_attempt", 0)))
    return candidate_order > previous_order


def _copy_trusted_shell(trusted_web: Path, destination: Path) -> None:
    for required in ("index.html", "browser", "assets"):
        source = trusted_web / required
        if source.is_symlink() or not source.exists():
            raise ValueError(f"Trusted browser shell is missing {required}")
        if source.is_dir():
            _assert_no_symlinks(source)
            shutil.copytree(source, destination / required, dirs_exist_ok=True)
        else:
            shutil.copyfile(source, destination / required)

    preview_index = destination / "index.html"
    preview_index.write_text(
        restrict_preview_csp(preview_index.read_text(encoding="utf-8")),
        encoding="utf-8",
    )


def _valid_firmware_url(value: str, repository: str, run_id: int) -> str:
    owner, name = repository.split("/", 1)
    expected = re.compile(
        rf"^https://github\.com/{re.escape(owner)}/{re.escape(name)}/actions/runs/{run_id}/artifacts/[1-9][0-9]*$"
    )
    if not expected.fullmatch(value or ""):
        raise ValueError("Invalid firmware artifact URL")
    return value


def _firmware_artifact_reference(value: str, repository: str,
                                 expected_run_id: int | None = None) -> dict | None:
    owner, name = repository.split("/", 1)
    match = re.fullmatch(
        rf"https://github\.com/{re.escape(owner)}/{re.escape(name)}/actions/runs/([1-9][0-9]*)/artifacts/([1-9][0-9]*)",
        value or "",
    )
    if not match:
        return None
    run_id, artifact_id = map(int, match.groups())
    if expected_run_id is not None and run_id != expected_run_id:
        return None
    return {"workflow_run_id": run_id, "artifact_id": artifact_id}


def _firmware_artifact_references(successful: list, repository: str) -> list[dict]:
    references = []
    for item in successful:
        if not isinstance(item, dict):
            continue
        expected_run_id = item.get("workflow_run_id")
        if type(expected_run_id) is not int or expected_run_id <= 0:
            continue
        reference = _firmware_artifact_reference(
            item.get("firmware_url", ""), repository, expected_run_id
        )
        if reference and reference not in references:
            references.append(reference)
    return references


def _tree_digest(root: Path) -> str:
    digest = sha256()
    _assert_no_symlinks(root)
    for path in sorted((item for item in root.rglob("*") if item.is_file()),
                       key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _legacy_success(pages: Path, state: dict | None, pr_number: int,
                    simulator_repository: str, site_base: str) -> dict | None:
    """Adopt a previously verified mutable preview once, without rewriting it."""
    if not state or state.get("status") != "success" or state.get("latest_action") != "build":
        return None
    sha = state.get("latest_source_sha", "")
    request_id = state.get("latest_request_id", "")
    if not re.fullmatch(r"[a-f0-9]{40}", sha) or not isinstance(request_id, str):
        return None
    old = pages / "pr" / str(pr_number)
    if not old.is_dir() or old.is_symlink():
        return None
    _assert_no_symlinks(old)
    records = []
    builds = old / "builds"
    if not builds.is_dir():
        return None
    for info_path in builds.glob(f"*/*/{sha}/build-info.json"):
        info = _json_object(info_path.read_bytes())
        source = info.get("source") or {}
        repository = source.get("repository", "")
        simulator = info.get("simulator") or {}
        if (not REPOSITORY_RE.fullmatch(repository) or source.get("commit") != sha or
                not re.fullmatch(r"[a-f0-9]{40}", simulator.get("commit", "")) or
                not info_path.is_relative_to(builds / repository / sha)):
            continue
        records.append((repository, simulator["commit"]))
    if len(set(records)) != 1:
        return None
    source_repository, simulator_sha = records[0]
    legacy_status_path = pages / "status" / "pr" / f"{pr_number}.json"
    try:
        legacy_status = _json_object(legacy_status_path.read_bytes())
        legacy_run_url = legacy_status["run_url"]
        legacy_run = re.fullmatch(
            rf"https://github\.com/{re.escape(simulator_repository)}/actions/runs/([1-9][0-9]*)",
            legacy_run_url,
        )
        if (legacy_status.get("status") != "success" or
                legacy_status.get("request_id") != request_id or
                legacy_status.get("source_sha") != sha or
                legacy_status.get("source_repository", "").lower() != source_repository.lower() or
                legacy_status.get("preview_url") != site_base + f"pr/{pr_number}/" or
                not legacy_run or int(legacy_run.group(1)) != int(state.get("workflow_run_id", 0))):
            return None
        run_id = int(legacy_run.group(1))
        firmware_url = _valid_firmware_url(
            legacy_status.get("firmware_url", ""), simulator_repository, run_id
        )
        run_attempt = int(state.get("run_attempt", 0))
        if run_attempt <= 0:
            return None
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    immutable = pages / "pr" / str(pr_number) / sha
    _ensure_safe_parent(pages, immutable.parent)
    if immutable.exists():
        return None
    shutil.copytree(old, immutable, symlinks=False)
    return {
        "head_sha": sha,
        "request_id": request_id,
        "workflow_run_id": run_id,
        "run_attempt": run_attempt,
        "simulator_sha": simulator_sha,
        "preview_url": site_base + f"pr/{pr_number}/{sha}/",
        "firmware_url": firmware_url,
        "run_url": legacy_run_url,
        "source_repository": source_repository,
    }


def publish(request: dict, pages: Path, browser_archive: Path, firmware_dir: Path,
            trusted_runtime_dir: Path, trusted_web: Path, result: str, simulator_repository: str,
            simulator_sha: str, run_id: int, run_attempt: int, firmware_url: str,
            github_token: str, pull_fetcher=fetch_pull) -> dict:
    if result not in ("success", "failure", "cancelled", "deleted"):
        raise ValueError("Invalid final build result")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", simulator_repository):
        raise ValueError("Invalid simulator repository")
    if not re.fullmatch(r"[a-f0-9]{40}", simulator_sha):
        raise ValueError("Invalid simulator SHA")
    if pages.is_symlink():
        raise ValueError("Pages tree must not be a symlink")
    pages.mkdir(parents=True, exist_ok=True)
    _assert_no_symlinks(pages)

    state_path = pages / ".preview-state" / "pr" / f"{request['pr_number']}.json"
    previous = _load_state(state_path)
    current_firmware_artifact = _firmware_artifact_reference(
        firmware_url, simulator_repository, run_id
    )
    if not _is_newer(request, run_id, run_attempt, previous):
        return {"applied": False, "status": "stale",
                "firmware_artifacts_to_prune": [current_firmware_artifact]
                if current_firmware_artifact else []}
    if not _validate_live_pr(request, github_token, pull_fetcher):
        return {"applied": False, "status": "stale",
                "firmware_artifacts_to_prune": [current_firmware_artifact]
                if current_firmware_artifact else []}

    effective = result
    owner, repository_name = os.environ["GITHUB_REPOSITORY"].split("/", 1)
    site_base = f"https://{owner.lower()}.github.io/{repository_name}/"
    successful = list((previous or {}).get("successful_previews", []))
    if request["action"] != "delete" and not successful and previous and previous.get("status") == "success":
        adopted = _legacy_success(pages, previous, request["pr_number"],
                                  simulator_repository, site_base)
        if adopted:
            successful = [adopted]

    firmware_artifacts_to_prune = []

    if request["action"] == "delete":
        effective = "deleted"
        firmware_artifacts_to_prune = _firmware_artifact_references(
            successful, simulator_repository
        )
        _remove_tree(pages, pages / "pr" / str(request["pr_number"]))
        status_file = pages / "status" / "pr" / f"{request['pr_number']}.json"
        if status_file.is_symlink():
            raise ValueError("Refusing to remove a symlink from the Pages tree")
        status_file.unlink(missing_ok=True)
    elif result == "success":
        try:
            _valid_firmware_url(firmware_url, os.environ["GITHUB_REPOSITORY"], run_id)
            _validate_firmware(firmware_dir, request, simulator_repository, simulator_sha)
            runtime_provenance = _validate_trusted_runtime(
                trusted_runtime_dir, request, simulator_repository, simulator_sha
            )
            with TemporaryDirectory(prefix="preview-archive-") as temp:
                extracted = Path(temp) / "unpacked"
                extracted.mkdir()
                _safe_extract_browser(browser_archive, extracted, request,
                                     simulator_repository, simulator_sha)
                replace_glue(extracted, trusted_runtime_dir / "micropython.js", runtime_provenance)
                preview = pages / "pr" / str(request["pr_number"]) / request["head_sha"]
                staged = Path(temp) / "preview"
                staged.mkdir()
                _copy_trusted_shell(trusted_web, staged)
                shutil.copytree(extracted / "browser", staged / "browser", dirs_exist_ok=True)
                shutil.copytree(extracted / "builds", staged / "builds", dirs_exist_ok=True)
                _assert_no_symlinks(staged)
                _ensure_safe_parent(pages, preview.parent)
                if preview.exists():
                    if preview.is_symlink() or not preview.is_dir() or _tree_digest(preview) != _tree_digest(staged):
                        raise ValueError("Commit-specific preview already exists with different content")
                else:
                    shutil.copytree(staged, preview)
                effective = "success"
        except Exception as exc:
            print(f"Preview artifact rejected: {type(exc).__name__}: {exc}")
            effective = "failure"

    run_url = f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}"
    preview_url = site_base + f"pr/{request['pr_number']}/{request['head_sha']}/"
    if effective == "success":
        firmware_artifacts_to_prune = _firmware_artifact_references(
            successful, simulator_repository
        )
        _remove_superseded_previews(pages, request["pr_number"], request["head_sha"])
        item = {
            "head_sha": request["head_sha"],
            "request_id": request["request_id"],
            "source_updated_at": request["source_updated_at"],
            "source_repository": request["head_repository"],
            "preview_url": preview_url,
            "firmware_url": firmware_url,
            "run_url": run_url,
            "workflow_run_id": run_id,
            "run_attempt": run_attempt,
            "simulator_sha": simulator_sha,
        }
        successful = [item]
    elif effective in ("failure", "cancelled") and current_firmware_artifact:
        firmware_artifacts_to_prune = [current_firmware_artifact]

    if effective == "success" and current_firmware_artifact:
        current_id = current_firmware_artifact["artifact_id"]
        firmware_artifacts_to_prune = [
            reference for reference in firmware_artifacts_to_prune
            if reference["artifact_id"] != current_id
        ]

    status = {
        "request_id": request["request_id"],
        "status": effective,
        "latest_run_url": run_url,
        "pr_number": request["pr_number"],
        "source_repository": request["head_repository"] or None,
        "source_sha": request["head_sha"],
        "source_updated_at": request["source_updated_at"],
        "preview_url": successful[0]["preview_url"] if successful else None,
        "firmware_url": successful[0].get("firmware_url") if successful else None,
        "successful_previews": successful,
        "failed_source_sha": request["head_sha"] if effective in ("failure", "cancelled") else None,
        "run_url": run_url,
    }
    state = {
        "latest_source_updated_at": request["source_updated_at"],
        "latest_source_sha": request["head_sha"],
        "latest_request_id": request["request_id"],
        "latest_action": request["action"],
        "workflow_run_id": run_id,
        "run_attempt": run_attempt,
        "status": effective,
        "base_repository": request["base_repository"],
        "base_sha": request["base_sha"],
        "base_ref": request["base_ref"],
        "head_repository": request["head_repository"],
        "head_ref": request["head_ref"],
        "simulator_repository": simulator_repository,
        "simulator_sha": simulator_sha,
        "successful_previews": [] if effective == "deleted" else successful,
    }
    _write_json(pages, state_path, state)
    if effective != "deleted":
        _write_json(pages, pages / "status" / "pr" / f"{request['pr_number']}.json", status)
    return {
        "applied": True,
        "status": effective,
        "successful_previews": state["successful_previews"],
        "firmware_artifacts_to_prune": firmware_artifacts_to_prune,
    }


def main() -> None:
    request = {
        "request_id": os.environ["REQUEST_ID"],
        "action": os.environ["ACTION"],
        "base_repository": os.environ["BASE_REPOSITORY"],
        "base_sha": os.environ["BASE_SHA"],
        "base_ref": os.environ["BASE_REF"],
        "pr_number": int(os.environ["PR_NUMBER"]),
        "head_repository": os.environ.get("HEAD_REPOSITORY", ""),
        "head_sha": os.environ["HEAD_SHA"],
        "head_ref": os.environ.get("HEAD_REF", ""),
        "source_updated_at": canonical_time(parse_time(os.environ["SOURCE_UPDATED_AT"])),
    }
    result = publish(
        request=request,
        pages=Path(os.environ["PAGES_DIR"]),
        browser_archive=Path(os.environ.get("BROWSER_ARCHIVE", "")),
        firmware_dir=Path(os.environ.get("FIRMWARE_DIR", "")),
        trusted_runtime_dir=Path(os.environ.get("TRUSTED_RUNTIME_DIR", "")),
        trusted_web=Path(os.environ["TRUSTED_WEB_DIR"]),
        result=os.environ["BUILD_RESULT"],
        simulator_repository=os.environ["SIMULATOR_REPOSITORY"],
        simulator_sha=os.environ["SIMULATOR_SHA"],
        run_id=int(os.environ["GITHUB_RUN_ID"]),
        run_attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),
        firmware_url=os.environ.get("FIRMWARE_URL", ""),
        github_token=os.environ["GH_TOKEN"],
    )
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"applied={str(result['applied']).lower()}\n")
            stream.write(f"status={result['status']}\n")
            stream.write(
                "firmware_artifacts_to_prune="
                + json.dumps(result.get("firmware_artifacts_to_prune", []), separators=(",", ":"))
                + "\n"
            )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
