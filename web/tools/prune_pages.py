#!/usr/bin/env python3
"""Evict the oldest PR previews only when the public Pages tree nears its cap."""
from pathlib import Path
import json
import os
import re
import sys

from publish_preview import _assert_no_symlinks, _load_state, _remove_tree, _write_json
from validate_preview_request import parse_time


# GitHub documents a 1 GB published-site maximum. Leave a little room for
# deployment packaging and metadata instead of publishing right at the edge.
PAGES_BUDGET_BYTES = 950_000_000
PR_NUMBER_RE = re.compile(r"[1-9][0-9]*\Z")
SHA_RE = re.compile(r"[a-f0-9]{40}\Z")


def public_tree_bytes(pages: Path) -> int:
    """Count exactly the directories copied into the GitHub Pages artifact."""
    total = 0
    for name in ("pr", "status"):
        root = pages / name
        if root.is_symlink():
            raise ValueError("Symlink in public Pages tree")
        if not root.exists():
            continue
        if not root.is_dir():
            raise ValueError("Invalid public Pages path")
        _assert_no_symlinks(root)
        for current, _directories, files in os.walk(root, followlinks=False):
            for filename in files:
                path = Path(current) / filename
                if not path.is_file():
                    raise ValueError("Invalid file in public Pages tree")
                total += path.stat().st_size
    return total


def _candidate(pages: Path, pr_number: int):
    state_path = pages / ".preview-state" / "pr" / f"{pr_number}.json"
    try:
        state = _load_state(state_path)
    except (OSError, ValueError):
        return None
    if not state:
        return None
    successful = state.get("successful_previews")
    if not isinstance(successful, list) or not successful:
        return None
    latest = successful[0]
    if not isinstance(latest, dict) or not SHA_RE.fullmatch(latest.get("head_sha", "")):
        return None
    preview_dir = pages / "pr" / str(pr_number)
    if preview_dir.is_symlink() or not preview_dir.is_dir():
        return None
    timestamp = latest.get("source_updated_at") or state.get("latest_source_updated_at")
    try:
        updated = parse_time(timestamp)
    except (TypeError, ValueError):
        return None
    return updated, pr_number, state, latest


def _mark_preview_evicted(pages: Path, pr_number: int, state: dict, latest: dict) -> None:
    state_path = pages / ".preview-state" / "pr" / f"{pr_number}.json"
    status_path = pages / "status" / "pr" / f"{pr_number}.json"
    if status_path.is_symlink():
        raise ValueError("Refusing to replace a symlink in the Pages tree")
    status = {}
    if status_path.exists():
        if not status_path.is_file() or status_path.stat().st_size > 64 * 1024:
            raise ValueError("Invalid public PR status record")
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid public PR status record") from exc
        if not isinstance(status, dict):
            raise ValueError("Invalid public PR status record")

    latest["preview_url"] = None
    latest["preview_evicted"] = True
    state["successful_previews"] = [latest]
    state["status"] = "capacity-evicted"
    status.update({
        "status": "capacity-evicted",
        "preview_url": None,
        "successful_previews": [latest],
        "preview_evicted_reason": "pages-capacity",
    })
    _write_json(pages, state_path, state)
    _write_json(pages, status_path, status)


def prune(pages: Path, current_pr: int, budget_bytes: int = PAGES_BUDGET_BYTES) -> dict:
    if pages.is_symlink() or not pages.is_dir():
        raise ValueError("Persistent Pages tree is unavailable")
    _assert_no_symlinks(pages)
    before = public_tree_bytes(pages)
    evicted = []
    if before > budget_bytes:
        pr_root = pages / "pr"
        candidates = []
        if pr_root.is_dir():
            for entry in pr_root.iterdir():
                if not PR_NUMBER_RE.fullmatch(entry.name) or entry.is_symlink() or not entry.is_dir():
                    continue
                pr_number = int(entry.name)
                if pr_number == current_pr:
                    continue
                candidate = _candidate(pages, pr_number)
                if candidate:
                    candidates.append(candidate)
        candidates.sort(key=lambda item: (item[0], item[1]))
        for _updated, pr_number, state, latest in candidates:
            _remove_tree(pages, pages / "pr" / str(pr_number))
            _mark_preview_evicted(pages, pr_number, state, latest)
            evicted.append(pr_number)
            if public_tree_bytes(pages) <= budget_bytes:
                break

    after = public_tree_bytes(pages)
    if after > budget_bytes:
        raise RuntimeError(
            f"Pages tree is {after} bytes after evicting {len(evicted)} old PR previews; "
            f"the current PR is protected and the {budget_bytes}-byte budget cannot be met"
        )
    return {"bytes_before": before, "bytes_after": after,
            "budget_bytes": budget_bytes, "evicted_pr_numbers": evicted}


def main() -> None:
    pages = Path(os.environ["PAGES_DIR"])
    current_pr = int(os.environ["PR_NUMBER"])
    result = prune(pages, current_pr)
    numbers = json.dumps(result["evicted_pr_numbers"], separators=(",", ":"))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"evicted_pr_numbers={numbers}\n")
            stream.write(f"bytes_before={result['bytes_before']}\n")
            stream.write(f"bytes_after={result['bytes_after']}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
