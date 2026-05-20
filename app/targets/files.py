"""Collect files/folders into a staging directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TypedDict

import structlog

log = structlog.get_logger(__name__)


class FileEntry(TypedDict):
    source: str         # original absolute path on host
    archive_path: str   # path inside archive (relative)
    kind: str           # "file" | "dir"


def backup_paths(paths: list[Path], staging_dir: Path) -> list[FileEntry]:
    """Copy each path into staging_dir/files/<path.name>.

    Returns a list of FileEntry dicts describing what was actually copied
    (skips non-existing entries). The entries are used to build the manifest.
    """
    files_dir = staging_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    copied: list[FileEntry] = []
    for src in paths:
        src = Path(src)
        if not src.exists():
            log.warning("path_missing_skipped", path=str(src))
            continue

        dest = files_dir / src.name
        try:
            if src.is_dir():
                shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
                kind = "dir"
            else:
                shutil.copy2(src, dest, follow_symlinks=False)
                kind = "file"
            copied.append({
                "source": str(src),
                "archive_path": f"files/{src.name}",
                "kind": kind,
            })
            log.debug("path_copied", source=str(src), dest=str(dest))
        except Exception as e:
            log.error("path_copy_failed", path=str(src), error=str(e))
            raise

    return copied
