#!/usr/bin/env python3
"""Report a validated preview result on its Specter PR using a non-collaborator machine-user PAT."""
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
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")


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


def verify_machine_user(token, expected_login, request_fn=api):
    if not token or not LOGIN_RE.fullmatch(expected_login):
        raise ValueError("Missing token or invalid expected bot login")
    user = request_fn("GET", "/user", token)
    if not isinstance(user, dict) or user.get("type") != "User" or (
        str(user.get("login", "")).lower() != expected_login.lower()
    ):
        raise ValueError("The token does not belong to the configured machine user")
    return user["login"]


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
    """Match the legacy compact Specter PR Build card, with provenance collapsed."""
    if action == "delete":
        return None
    if result not in ("success", "failure", "cancelled"):
        raise ValueError("Unexpected report result")
    if not REPOSITORY_RE.fullmatch(simulator_repository):
        raise ValueError("Invalid simulator repository")
    short = state.get("latest_source_sha", "")
    if not isinstance(short, str) or not SHA_RE.fullmatch(short):
        raise ValueError("Invalid latest source SHA")
    source = state.get("head_repository", "")
    base_repo = state.get("base_repository", "")
    base_sha = state.get("base_sha", "")
    sim_sha = state.get("simulator_sha", "")
    if not all(isinstance(r, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", r)
               for r in (source, base_repo)):
        raise ValueError("Invalid repository provenance")
    if not all(isinstance(h, str) and SHA_RE.fullmatch(h) for h in (base_sha, sim_sha)):
        raise ValueError("Invalid commit provenance")
    records = state.get("successful_previews", [])
    if not isinstance(records, list) or len(records) > 1:
        raise ValueError("Invalid successful preview state")
    site = site_base
    successful = [_valid_success(r, number, site, simulator_repository) for r in records]
    status_icon = {"success": "✅", "failure": "❌", "cancelled": "⏹️"}[result]
    lines = [f"🧪 **Specter PR Build** · `{short[:7]}` {status_icon}", "",
             "<details>", "<summary>Build provenance</summary>", "",
             f"- **Source commit:** [`{source}@{short[:7]}`](https://github.com/{source}/commit/{short})",
             f"- **PR base commit:** [`{base_repo}@{base_sha[:7]}`](https://github.com/{base_repo}/commit/{base_sha})",
             f"- **Simulator commit:** [`{simulator_repository}@{sim_sha[:7]}`](https://github.com/{simulator_repository}/commit/{sim_sha})"]
    latest_id = state.get("workflow_run_id")
    if type(latest_id) is not int or latest_id <= 0:
        raise ValueError("Invalid latest build run ID")
    latest_run = f"https://github.com/{simulator_repository}/actions/runs/{latest_id}"
    lines.append(f"- **Latest build:** [Build logs]({latest_run})")
    if successful:
        lines.append(f"- **Last successful build:** [Verified build logs]({successful[0][3]})")
    lines.extend(["", "</details>", ""])
    if result == "failure":
        lines.extend(["**Latest build failed.**", ""])
    elif result == "cancelled":
        lines.extend(["**Latest build was cancelled.**", ""])
    if successful:
        record_sha, preview, firmware, _ = successful[0]
        if record_sha != short:
            lines.extend([f"Last working preview is from an earlier commit `{record_sha[:7]}`.", ""])
        if preview:
            lines.extend([f"🖥️ [Open browser simulator]({preview})", ""])
        else:
            lines.extend(["Browser preview removed to stay within GitHub Pages limits. Push a new commit to generate a fresh preview.", ""])
        if firmware:
            lines.extend([f"⬇️ [Download firmware from the same commit]({firmware})", ""])
    else:
        lines.extend(["No successful browser preview is available yet.", ""])
    lines.extend([
        "⚠️ **Experimental development build. Never use real funds or enter a real seed phrase. Use dedicated test hardware for firmware builds.**",
        "", MARKER
    ])
    return "\n".join(lines)


def replace_managed_comment(repository, number, comments, expected_login, token, body, request_fn=api):
    """Keep the earliest owned preview comment; PATCH in place, never repost it.

    The stable comment ID avoids duplicate timeline entries and notifications.
    Delete only extra comments authored by this exact machine user and carrying
    our private preview marker. On edit failure do not delete anything.
    """
    owned = sorted(managed_comments(comments, expected_login), key=lambda c: c.get("id", -1))
    ids = [c.get("id") for c in owned]
    if any(type(cid) is not int or cid <= 0 for cid in ids):
        raise ValueError("Invalid owned comment ID")
    if body is None:
        for cid in ids:
            request_fn("DELETE", f"/repos/{repository}/issues/comments/{cid}", token)
        return len(ids)
    if owned:
        survivor = owned[0]
        if survivor["body"] != body:
            response = request_fn(
                "PATCH", f"/repos/{repository}/issues/comments/{survivor['id']}",
                token, {"body": body}
            )
            if (not isinstance(response, dict) or
                response.get("id") != survivor["id"] or
                (response.get("user") or {}).get("login") != expected_login):
                raise ValueError("Comment update was not confirmed for the expected bot")
        obsolete = ids[1:]
    else:
        response = request_fn(
            "POST", f"/repos/{repository}/issues/{number}/comments",
            token, {"body": body}
        )
        if (not isinstance(response, dict) or
            type(response.get("id")) is not int or response["id"] <= 0 or
            (response.get("user") or {}).get("login") != expected_login):
            raise ValueError("Comment creation was not confirmed for the expected bot")
        obsolete = []
    for cid in obsolete:
        request_fn("DELETE", f"/repos/{repository}/issues/comments/{cid}", token)
    return len(obsolete)

def report(request, pages, simulator_repository, simulator_sha, run_id, run_attempt,
           result, token, expected_login, request_fn=api, pull_fetcher=None):
    if request["base_repository"].lower() != TARGET_REPOSITORY:
        raise ValueError("The preview reporter only writes to cryptoadvance/specter-diy")
    if not REPOSITORY_RE.fullmatch(simulator_repository) or not SHA_RE.fullmatch(simulator_sha):
        raise ValueError("Invalid Web Simulator run identity")
    if result not in ("success", "failure", "cancelled", "deleted"):
        raise ValueError("Invalid final build result")
    if simulator_repository.lower() != 'cryptoadvance/specter-diy-web-simulator':
        raise ValueError('Only the paired production Web Simulator may report upstream')
    verify_machine_user(token, expected_login, request_fn)
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
                              token, expected_login, request_fn=api, pull_fetcher=None):
    """Replace stale PR comments after their previews were evicted for capacity."""
    if not REPOSITORY_RE.fullmatch(simulator_repository) or not SHA_RE.fullmatch(simulator_sha):
        raise ValueError("Invalid Web Simulator run identity")
    if simulator_repository.lower() != 'cryptoadvance/specter-diy-web-simulator':
        raise ValueError('Only the paired production Web Simulator may report upstream')
    verify_machine_user(token, expected_login, request_fn)
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
            token=os.environ["SPECTER_PREVIEW_BOT_TOKEN"],
            expected_login=os.environ["SPECTER_PREVIEW_BOT_LOGIN"],
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
        token=os.environ["SPECTER_PREVIEW_BOT_TOKEN"],
        expected_login=os.environ["SPECTER_PREVIEW_BOT_LOGIN"],
    )
    print(json.dumps(result, sort_keys=True))
    if not result["applied"]:
        raise SystemExit("Preview report was skipped because the request is stale")


if __name__ == "__main__":
    main()
