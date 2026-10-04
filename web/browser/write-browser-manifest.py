#!/usr/bin/env python3
"""Write the trusted frozen-module manifest into a Specter source checkout."""
from pathlib import Path
import sys


MANIFEST = '''import os
freeze('f469-disco/usermods/udisplay_f469/display_unixport')
# Newer boards curate embit's src/ layout and omit CPython-only examples/tests.
# Older board revisions had flat common libraries and no curated manifest.
if os.path.isfile('f469-disco/manifests/common.py'):
    include('f469-disco/manifests/common.py')
else:
    freeze('f469-disco/libs/common')
freeze('src')
'''


def write_manifest(source: Path) -> Path:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError("Specter source directory does not exist")
    manifest = source / "browser.manifest.py"
    if manifest.is_symlink():
        raise ValueError("Browser manifest path must not be a symlink")
    manifest.write_text(MANIFEST, encoding="utf-8")
    return manifest


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: write-browser-manifest.py SPECTER_SOURCE_DIR")
    write_manifest(Path(sys.argv[1]))
