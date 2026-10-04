"""Helpers for identifying firmware projects across repositories and forks."""


def is_specter_diy_repository(repository: str) -> bool:
    return repository.rsplit("/", 1)[-1].lower() == "specter-diy"
