#!/usr/bin/env python3
"""Delete only firmware artifacts referenced by trusted preview state."""
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import os
import re


REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def api(method, path, token):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "specter-web-simulator-firmware-cleanup",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with urlopen(Request("https://api.github.com" + path,
                         headers=headers, method=method), timeout=30) as response:
        content = response.read()
        return json.loads(content) if content else None


def _candidate_list(value):
    candidates = json.loads(value)
    if not isinstance(candidates, list) or len(candidates) > 4:
        raise ValueError("Invalid firmware artifact cleanup list")
    result = []
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Invalid firmware artifact reference")
        artifact_id = candidate.get("artifact_id")
        run_id = candidate.get("workflow_run_id")
        if type(artifact_id) is not int or artifact_id <= 0:
            raise ValueError("Invalid firmware artifact ID")
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("Invalid firmware workflow run ID")
        if artifact_id not in seen:
            result.append({"artifact_id": artifact_id, "workflow_run_id": run_id})
            seen.add(artifact_id)
    return result


def _get_artifact(repository, artifact_id, token, request_fn):
    path = f"/repos/{repository}/actions/artifacts/{artifact_id}"
    try:
        return request_fn("GET", path, token)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def prune(repository, pr_number, candidates, token, request_fn=api):
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("Invalid simulator repository")
    if type(pr_number) is not int or not 1 <= pr_number <= 9_999_999:
        raise ValueError("Invalid PR number")
    if not isinstance(candidates, list) or len(candidates) > 4:
        raise ValueError("Invalid firmware artifact cleanup list")

    legacy_names = {"specter-firmware", f"specter-firmware-pr-{pr_number}"}
    deleted = []
    skipped = []
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("Invalid firmware artifact reference")
        artifact_id = candidate.get("artifact_id")
        run_id = candidate.get("workflow_run_id")
        if type(artifact_id) is not int or artifact_id <= 0:
            raise ValueError("Invalid firmware artifact ID")
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("Invalid firmware workflow run ID")
        if artifact_id in seen:
            continue
        seen.add(artifact_id)

        artifact = _get_artifact(repository, artifact_id, token, request_fn)
        if artifact is None:
            skipped.append({"artifact_id": artifact_id, "reason": "missing"})
            continue
        workflow_run = artifact.get("workflow_run") or {}
        artifact_name = artifact.get("name")
        legacy_run_name = re.fullmatch(
            rf"specter-firmware-pr-{pr_number}-run-{run_id}-attempt-[1-9][0-9]*",
            artifact_name or "",
        )
        commit_named = re.fullmatch(
            rf"specter-firmware_PR-{pr_number}_[a-f0-9]{{12}}(?:_attempt-(?:[2-9]|[1-9][0-9]+))?",
            artifact_name or "",
        )
        if ((artifact_name not in legacy_names and not legacy_run_name and not commit_named) or
                workflow_run.get("id") != run_id):
            skipped.append({"artifact_id": artifact_id, "reason": "identity-mismatch"})
            continue
        if artifact.get("expired") is True:
            skipped.append({"artifact_id": artifact_id, "reason": "already-expired"})
            continue

        request_fn("DELETE", f"/repos/{repository}/actions/artifacts/{artifact_id}", token)
        deleted.append(artifact_id)
    return {"deleted": deleted, "skipped": skipped}


def main():
    result = prune(
        repository=os.environ["GITHUB_REPOSITORY"],
        pr_number=int(os.environ["PR_NUMBER"]),
        candidates=_candidate_list(os.environ.get("FIRMWARE_ARTIFACTS_TO_PRUNE", "[]")),
        token=os.environ["GITHUB_TOKEN"],
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
