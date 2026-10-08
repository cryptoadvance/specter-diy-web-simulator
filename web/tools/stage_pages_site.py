#!/usr/bin/env python3
"""Copy the public Pages directories while keeping trusted state private."""
from pathlib import Path
import os
import shutil
import sys


def stage(persistent: Path, output: Path) -> None:
    if persistent.is_symlink():
        raise ValueError("Persistent Pages tree must not be a symlink")
    persistent = persistent.resolve()
    if not persistent.is_dir():
        raise ValueError("Persistent Pages tree is unavailable")
    for name in ("pr", "status"):
        source = persistent / name
        if source.is_symlink():
            raise ValueError("Symlink in public Pages tree")
        if source.exists() and not source.is_dir():
            raise ValueError("Invalid public Pages path")
        if source.exists():
            for current, directories, files in os.walk(source, followlinks=False):
                current_path = Path(current)
                for child in directories + files:
                    path = current_path / child
                    if path.is_symlink():
                        raise ValueError("Symlink in public Pages tree")
                    if child in directories and not path.is_dir():
                        raise ValueError("Invalid directory in public Pages tree")
                    if child in files and not path.is_file():
                        raise ValueError("Invalid file in public Pages tree")

    if output.exists():
        if output.is_symlink() or output.resolve() == persistent:
            raise ValueError("Unsafe Pages staging destination")
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for name in ("pr", "status"):
        source = persistent / name
        if source.exists():
            shutil.copytree(source, output / name)
    (output / ".nojekyll").write_text("", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: stage_pages_site.py PERSISTENT_TREE OUTPUT_DIR")
    stage(Path(sys.argv[1]), Path(sys.argv[2]))
