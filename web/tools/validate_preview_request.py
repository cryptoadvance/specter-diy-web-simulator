#!/usr/bin/env python3
"""Validate a Specter dispatch against the live pull request before building."""
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import json
import os
import re


OWNER_RE = re.compile(r"^[A-Za-z0-9-]{1,39}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
REQUEST_RE = re.compile(
    r"^specter-pr-(?P<number>[1-9][0-9]{0,6})-"
    r"(?P<sha>[a-f0-9]{40})-(?P<run>[1-9][0-9]*)-(?P<attempt>[1-9][0-9]*)$"
)


def parse_time(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("source_updated_at must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("source_updated_at must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("source_updated_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_time(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def fetch_pull(repository: str, number: int, token: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "specter-web-simulator-preview",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"https://api.github.com/repos/{repository}/pulls/{number}",
        headers=headers,
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def _valid_ref(value: str) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 255:
        return False
    if value.startswith(("/", ".")) or value.endswith(("/", ".", ".lock")):
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    if any(token in value for token in ("..", "//", "@{", "\\", " ", "~", "^", ":", "?", "*", "[")):
        return False
    return all(part and not part.startswith(".") and not part.endswith(".lock")
               for part in value.split("/"))


def parse_request(inputs: dict, service_repository: str) -> dict:
    if not REPOSITORY_RE.fullmatch(service_repository):
        raise ValueError("Invalid Web Simulator repository")
    owner, name = service_repository.split("/", 1)
    if not OWNER_RE.fullmatch(owner):
        raise ValueError("Invalid Web Simulator owner")

    action = inputs.get("action", "")
    if action not in ("build", "delete"):
        raise ValueError("action must be build or delete")
    base_repository = inputs.get("base_repository", "")
    expected_base = f"{owner}/specter-diy"
    if base_repository.lower() != expected_base.lower():
        raise ValueError(f"base_repository must be {expected_base}")
    if not REPOSITORY_RE.fullmatch(base_repository):
        raise ValueError("Invalid base_repository")

    number_text = str(inputs.get("pr_number", ""))
    if not re.fullmatch(r"[1-9][0-9]{0,6}", number_text):
        raise ValueError("Invalid PR number")
    number = int(number_text)

    head_sha = inputs.get("head_sha", "")
    if not SHA_RE.fullmatch(head_sha):
        raise ValueError("head_sha must be a full 40-character commit SHA")
    request_id = inputs.get("request_id", "")
    match = REQUEST_RE.fullmatch(request_id)
    if not match:
        raise ValueError("request_id has an invalid format")
    if int(match.group("number")) != number or match.group("sha") != head_sha:
        raise ValueError("request_id does not match the PR number and source SHA")

    head_repository = inputs.get("head_repository", "")
    head_ref = inputs.get("head_ref", "")
    base_sha = inputs.get("base_sha", "")
    base_ref = inputs.get("base_ref", "")
    if bool(base_sha) != bool(base_ref):
        raise ValueError("base_sha and base_ref must be supplied together")
    if base_sha and not SHA_RE.fullmatch(base_sha):
        raise ValueError("base_sha must be a full 40-character commit SHA")
    if base_ref and not _valid_ref(base_ref):
        raise ValueError("base_ref must be a valid branch name")
    if action == "build":
        if not REPOSITORY_RE.fullmatch(head_repository):
            raise ValueError("Build requests require a valid head_repository")
        if not _valid_ref(head_ref):
            raise ValueError("Build requests require a valid head_ref")
    elif head_repository:
        if not REPOSITORY_RE.fullmatch(head_repository):
            raise ValueError("Invalid head_repository")

    updated = parse_time(inputs.get("source_updated_at", ""))
    return {
        "request_id": request_id,
        "action": action,
        "base_repository": expected_base,
        "base_sha": base_sha,
        "base_ref": base_ref,
        "pr_number": number,
        "head_repository": head_repository,
        "head_sha": head_sha,
        "head_ref": head_ref,
        "source_updated_at": canonical_time(updated),
        "request_run_id": int(match.group("run")),
        "request_run_attempt": int(match.group("attempt")),
    }


def validate_request(inputs: dict, service_repository: str, token: str,
                     pull_fetcher=fetch_pull) -> dict:
    request = parse_request(inputs, service_repository)
    pr = pull_fetcher(request["base_repository"], request["pr_number"], token)
    if int(pr.get("number", -1)) != request["pr_number"]:
        raise ValueError("GitHub returned a different PR number")
    base = pr.get("base") or {}
    base_repo = (base.get("repo") or {}).get("full_name", "")
    if base_repo.lower() != request["base_repository"].lower():
        raise ValueError("PR belongs to another base repository")
    live_base_sha = base.get("sha", "")
    live_base_ref = base.get("ref", "")
    if not SHA_RE.fullmatch(live_base_sha):
        raise ValueError("PR base does not have a valid commit SHA")
    if not _valid_ref(live_base_ref):
        raise ValueError("PR base does not have a valid branch name")
    if request["action"] == "build" and request["base_sha"] and request["base_sha"] != live_base_sha:
        raise ValueError("PR base SHA no longer matches the validated base")
    if request["action"] == "build" and request["base_ref"] and request["base_ref"] != live_base_ref:
        raise ValueError("PR base ref no longer matches the validated base")

    head = pr.get("head") or {}
    live_sha = head.get("sha", "")
    if live_sha != request["head_sha"]:
        raise ValueError("PR head SHA no longer matches the dispatched SHA")

    if request["action"] == "build":
        if pr.get("state") != "open":
            raise ValueError("Build requests require an open PR")
        live_repo = (head.get("repo") or {}).get("full_name", "")
        if live_repo.lower() != request["head_repository"].lower():
            raise ValueError("PR head repository no longer matches the request")
        if head.get("ref") != request["head_ref"]:
            raise ValueError("PR head ref no longer matches the request")
    else:
        if pr.get("state") != "closed":
            raise ValueError("Delete requests require a closed PR")
        live_repo = (head.get("repo") or {}).get("full_name", "")
        if live_repo and request["head_repository"] and live_repo.lower() != request["head_repository"].lower():
            raise ValueError("Closed PR head repository does not match the request")

    live_updated = parse_time(pr.get("updated_at", ""))
    if live_updated < parse_time(request["source_updated_at"]):
        raise ValueError("source_updated_at is ahead of current PR metadata")
    request["head_repository"] = request["head_repository"] or ""
    request["base_sha"] = live_base_sha
    request["base_ref"] = live_base_ref
    return request


def main() -> None:
    inputs = json.loads(os.environ["PREVIEW_INPUTS_JSON"])
    expected_ref = f"refs/heads/{os.environ['DEFAULT_BRANCH']}"
    if os.environ.get("GITHUB_REF") != expected_ref:
        raise ValueError("Preview requests must run from the Web Simulator default branch")
    result = validate_request(inputs, os.environ["GITHUB_REPOSITORY"],
                              os.environ.get("GH_TOKEN", ""))
    output = os.environ["GITHUB_OUTPUT"]
    with open(output, "a", encoding="utf-8") as stream:
        for key in ("request_id", "action", "base_repository", "pr_number",
                    "base_sha", "base_ref",
                    "head_repository", "head_sha", "head_ref", "source_updated_at",
                    "request_run_id", "request_run_attempt"):
            stream.write(f"{key}={result[key]}\n")
    with open("validated-request.json", "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
