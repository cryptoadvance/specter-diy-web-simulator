#!/usr/bin/env python3
"""Report a validated preview result on its Specter PR using an App token."""
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import os
import re
import sys

from publish_preview import _load_state, _validate_live_pr
from validate_preview_request import parse_time, canonical_time


MARKER = "<!-- specter-web-simulator-preview -->"
TARGET_REPOSITORY = "cryptoadvance/specter-diy"
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA_RE = re.compile(r"[a-f0-9]{40}\Z")


def api(method, path, token, data=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "specter-web-simulator-preview",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    raw = json.dumps(data).encode() if data is not None else None
    if raw is not None:
        headers["Content-Type"] = "application/json"
    with urlopen(Request("https://api.github.com" + path, data=raw,
                         headers=headers, method=method), timeout=30) as response:
        content = response.read()
        return json.loads(content) if content else None


def managed_comments(comments, expected_login):
    return [comment for comment in comments
            if isinstance(comment, dict)
            and (comment.get("user") or {}).get("login") == expected_login
            and isinstance(comment.get("body"), str)
            and MARKER in comment["body"]]


def list_comments(repository, number, token, request_fn=api):
    result = []
    page = 1
    while True:
        path = f"/repos/{repository}/issues/{number}/comments?" + urlencode(
            {"per_page": 100, "page": page})
        batch = request_fn("GET", path, token)
        if not isinstance(batch, list):
            raise ValueError("GitHub returned an invalid issue-comment page")
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1


def _valid_success(item, number, site_base, simulator_repository):
    sha = item.get("head_sha", "")
    preview = item.get("preview_url", "")
    expected_preview = site_base + f"pr/{number}/{sha}/"
    evicted = item.get("preview_evicted") is True
    if (not SHA_RE.fullmatch(sha) or
            (evicted and preview is not None) or
            (not evicted and preview != expected_preview)):
        raise ValueError("Trusted preview state contains an invalid preview URL")
    run_id = item.get("workflow_run_id")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("Trusted preview state contains an invalid run identity")
    run_url = f"https://github.com/{simulator_repository}/actions/runs/{run_id}"
    if item.get("run_url") != run_url:
        raise ValueError("Trusted preview state contains an invalid run URL")
    firmware_url = item.get("firmware_url", "")
    if firmware_url and not re.fullmatch(
            rf"https://github\.com/{re.escape(simulator_repository)}/actions/runs/{run_id}/artifacts/[1-9][0-9]*",
            firmware_url):
        raise ValueError("Trusted preview state contains an invalid firmware URL")
    return sha, preview, firmware_url, run_url


def comment_body(state, action, result, number, site_base, simulator_repository):
    if action == "delete":
        return None
    successful = state.get("successful_previews", [])
    if not isinstance(successful, list) or len(successful) > 1:
        raise ValueError("Trusted preview history is invalid")
    records = [_valid_success(item, number, site_base, simulator_repository)
               for item in successful]
    lines = ["## Specter Browser Preview", ""]
    if result in ("failure", "cancelled"):
        sha = state.get("latest_source_sha", "")
        if not SHA_RE.fullmatch(sha):
            raise ValueError("Trusted preview state contains an invalid failed SHA")
        outcome = "failed" if result == "failure" else "was cancelled"
        lines.extend([f"Latest build `{sha[:7]}` {outcome}.", ""])
    if records:
        lines.extend(["### Latest", ""])
        if records[0][1]:
            lines.append(f"`{records[0][0][:7]}` → [Open browser simulator]({records[0][1]})")
        else:
            lines.append(
                f"`{records[0][0][:7]}` browser preview removed to stay within GitHub Pages storage limits. "
                "Push a new commit to publish a fresh preview."
            )
        if records[0][2]:
            lines.append(f"[Firmware artifact]({records[0][2]})")
        lines.append(f"[Build logs]({records[0][3]})")
    else:
        lines.extend(["No successful browser preview is available yet."])
    if result in ("failure", "cancelled"):
        failed_run = state.get("latest_run_url")
        if isinstance(failed_run, str) and re.fullmatch(
                rf"https://github\.com/{re.escape(simulator_repository)}/actions/runs/[1-9][0-9]*",
                failed_run):
            lines.extend(["", f"[Failed build logs]({failed_run})"])
    lines.extend(["", "⚠️ Experimental development build. Never enter a real seed phrase or use real funds.", "", MARKER])
    return "\n".join(lines)



def replace_managed_comment(repository, number, comments, expected_login, token,
                            body, request_fn=api):
    """Post a replacement before removing any old App-owned preview comments.

    A failed POST leaves the last useful preview comment untouched. If cleanup
    fails after the POST, a later successful report removes the duplicates.
    A closed PR passes body=None and only removes its existing marked comments.
    """
    marked = managed_comments(comments, expected_login)
    old_ids = []
    for previous in marked:
        comment_id = previous.get("id")
        if type(comment_id) is not int or comment_id <= 0:
            raise ValueError("GitHub returned an invalid comment ID")
        old_ids.append(comment_id)

    if body is not None:
        created = request_fn(
            "POST", f"/repos/{repository}/issues/{number}/comments",
            token, {"body": body},
        )
        if (not isinstance(created, dict) or
                type(created.get("id")) is not int or created["id"] <= 0):
            raise ValueError("GitHub returned an invalid created comment ID")

    for comment_id in old_ids:
        request_fn("DELETE", f"/repos/{repository}/issues/comments/{comment_id}", token)
    return len(old_ids)


def report(request, pages, simulator_repository, simulator_sha, run_id, run_attempt,
           result, token, app_slug, request_fn=api, pull_fetcher=None):
    if request["base_repository"].lower() != TARGET_REPOSITORY:
        raise ValueError("The preview reporter only writes to cryptoadvance/specter-diy")
    if not REPOSITORY_RE.fullmatch(simulator_repository) or not SHA_RE.fullmatch(simulator_sha):
        raise ValueError("Invalid Web Simulator run identity")
    if result not in ("success", "failure", "cancelled", "deleted"):
        raise ValueError("Invalid final build result")
    if not re.fullmatch(r"[a-z0-9-]{1,39}", app_slug):
        raise ValueError("Invalid GitHub App slug")
    expected_login = app_slug + "[bot]"
    state_path = pages / ".preview-state" / "pr" / f"{request['pr_number']}.json"
    state = _load_state(state_path)
    if not state:
        return {"applied": False, "status": "missing-state"}

    exact = {
        "latest_request_id": request["request_id"],
        "latest_action": request["action"],
        "latest_source_sha": request["head_sha"],
        "latest_source_updated_at": canonical_time(parse_time(request["source_updated_at"])),
        "workflow_run_id": run_id,
        "run_attempt": run_attempt,
        "status": result,
        "base_repository": request["base_repository"],
        "base_sha": request["base_sha"],
        "base_ref": request["base_ref"],
        "head_repository": request["head_repository"],
        "head_ref": request["head_ref"],
        "simulator_repository": simulator_repository,
        "simulator_sha": simulator_sha,
    }
    if any(state.get(key) != value for key, value in exact.items()):
        return {"applied": False, "status": "stale-state"}
    fetch = pull_fetcher or (lambda repository, number, auth: request_fn(
        "GET", f"/repos/{repository}/pulls/{number}", auth))
    if not _validate_live_pr(request, token, fetch):
        return {"applied": False, "status": "stale-pr"}

    comments = list_comments(request["base_repository"], request["pr_number"], token, request_fn)
    if request["action"] == "delete":
        removed = replace_managed_comment(
            request["base_repository"], request["pr_number"], comments,
            expected_login, token, None, request_fn,
        )
        return {"applied": True, "status": "deleted", "removed_comments": removed}

    owner, repository_name = simulator_repository.split("/", 1)
    site_base = f"https://{owner.lower()}.github.io/{repository_name}/"
    body = comment_body(state, request["action"], result, request["pr_number"],
                        site_base, simulator_repository)
    removed = replace_managed_comment(
        request["base_repository"], request["pr_number"], comments,
        expected_login, token, body, request_fn,
    )
    return {"applied": True, "status": result, "removed_comments": removed}


def report_capacity_evictions(pr_numbers, pages, simulator_repository, simulator_sha,
                              token, app_slug, request_fn=api, pull_fetcher=None):
    """Replace stale PR comments after their previews were evicted for capacity."""
    if not REPOSITORY_RE.fullmatch(simulator_repository) or not SHA_RE.fullmatch(simulator_sha):
        raise ValueError("Invalid Web Simulator run identity")
    if not re.fullmatch(r"[a-z0-9-]{1,39}", app_slug):
        raise ValueError("Invalid GitHub App slug")
    expected_login = app_slug + "[bot]"
    fetch = pull_fetcher or (lambda repository, number, auth: request_fn(
        "GET", f"/repos/{repository}/pulls/{number}", auth))
    owner, repository_name = simulator_repository.split("/", 1)
    site_base = f"https://{owner.lower()}.github.io/{repository_name}/"
    results = []

    for number in sorted(set(pr_numbers)):
        if type(number) is not int or number <= 0:
            raise ValueError("Invalid capacity-evicted PR number")
        state = _load_state(pages / ".preview-state" / "pr" / f"{number}.json")
        if (not state or state.get("status") != "capacity-evicted" or
                state.get("simulator_repository", "").lower() != simulator_repository.lower()):
            results.append({"pr_number": number, "status": "stale-state"})
            continue
        request = {
            "request_id": state.get("latest_request_id", ""),
            "action": "build",
            "base_repository": state.get("base_repository", ""),
            "base_sha": state.get("base_sha", ""),
            "base_ref": state.get("base_ref", ""),
            "pr_number": number,
            "head_repository": state.get("head_repository", ""),
            "head_sha": state.get("latest_source_sha", ""),
            "head_ref": state.get("head_ref", ""),
            "source_updated_at": state.get("latest_source_updated_at", ""),
        }
        if request["base_repository"].lower() != TARGET_REPOSITORY:
            results.append({"pr_number": number, "status": "unsupported-base"})
            continue
        if not _validate_live_pr(request, token, fetch):
            results.append({"pr_number": number, "status": "stale-pr"})
            continue

        comments = list_comments(request["base_repository"], number, token, request_fn)
        body = comment_body(state, "build", "success", number, site_base, simulator_repository)
        removed = replace_managed_comment(
            request["base_repository"], number, comments,
            expected_login, token, body, request_fn,
        )
        results.append({"pr_number": number, "status": "reported",
                        "removed_comments": removed})
    return results


def main():
    capacity_evictions = os.environ.get("CAPACITY_EVICTED_PR_NUMBERS")
    if capacity_evictions is not None:
        result = report_capacity_evictions(
            pr_numbers=json.loads(capacity_evictions),
            pages=Path(os.environ["PAGES_DIR"]),
            simulator_repository=os.environ["SIMULATOR_REPOSITORY"],
            simulator_sha=os.environ["SIMULATOR_SHA"],
            token=os.environ["SPECTER_PREVIEW_APP_TOKEN"],
            app_slug=os.environ["SPECTER_PREVIEW_APP_SLUG"],
        )
        print(json.dumps(result, sort_keys=True))
        return
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
    result = report(
        request=request,
        pages=Path(os.environ["PAGES_DIR"]),
        simulator_repository=os.environ["SIMULATOR_REPOSITORY"],
        simulator_sha=os.environ["SIMULATOR_SHA"],
        run_id=int(os.environ["GITHUB_RUN_ID"]),
        run_attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),
        result=os.environ["BUILD_RESULT"],
        token=os.environ["SPECTER_PREVIEW_APP_TOKEN"],
        app_slug=os.environ["SPECTER_PREVIEW_APP_SLUG"],
    )
    print(json.dumps(result, sort_keys=True))
    if not result["applied"]:
        raise SystemExit("Preview report was skipped because the request is stale")


if __name__ == "__main__":
    main()
