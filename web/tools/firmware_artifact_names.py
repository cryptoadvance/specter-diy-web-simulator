"""Trusted, predictable names for a commit-specific PR firmware download."""
import re


def firmware_base_name(pr_number: int, head_sha: str) -> str:
    if type(pr_number) is not int or not 1 <= pr_number <= 9_999_999:
        raise ValueError("Invalid firmware PR number")
    if not isinstance(head_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", head_sha):
        raise ValueError("Invalid firmware source SHA")
    return f"specter-firmware_PR-{pr_number}_{head_sha[:12]}"


def firmware_filenames(pr_number: int, head_sha: str) -> tuple[str, str]:
    base = firmware_base_name(pr_number, head_sha)
    return base + ".bin", base + ".hex"


def firmware_artifact_name(pr_number: int, head_sha: str, attempt: int = 1) -> str:
    """Standard download has the exact requested name; reruns need unique names."""
    if type(attempt) is not int or attempt < 1:
        raise ValueError("Invalid workflow attempt number")
    base = firmware_base_name(pr_number, head_sha)
    return base if attempt == 1 else f"{base}_attempt-{attempt}"
