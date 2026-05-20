"""Collect files/folders into a staging directory."""

from __future__ import annotations

import shutil
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


def backup_paths(paths: list[Path], staging_dir: Path) -> list[Path]:
    """Copy each path into staging_dir/files/<path.name>.

    Returns the list of paths actually copied (skips non-existing entries).
    """
    files_dir = staging_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for src in paths:
        src = Path(src)
        if not src.exists():
            log.warning("path_missing_skipped", path=str(src))
            continue

        dest = files_dir / src.name
        try:
            if src.is_dir():
                shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest, follow_symlinks=False)
            copied.append(dest)
            log.debug("path_copied", source=str(src), dest=str(dest))
        except Exception as e:
            log.error("path_copy_failed", path=str(src), error=str(e))
            raise

    return copied
