"""Collect files/folders into a staging directory."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import TypedDict

import structlog

log = structlog.get_logger(__name__)


class FileEntry(TypedDict):
    source: str         # original absolute path on host
    archive_path: str   # path inside archive (relative)
    kind: str           # "file" | "dir"


def _make_exclude_matcher(src_root: Path, patterns: list[str]):
    """Return an `ignore` callable for shutil.copytree.

    Patterns are glob-style with `**` (recursive). They match paths
    relative to src_root, so '**/.git' excludes any '.git' directory at
    any depth, '**/backups' excludes a 'backups' directory anywhere, etc.
    """
    if not patterns:
        return None

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped: set[str] = set()
        dir_path = Path(directory)
        for name in names:
            try:
                rel = (dir_path / name).relative_to(src_root)
            except ValueError:
                continue
            rel_posix = PurePosixPath(rel.as_posix())
            for pat in patterns:
                # full_match (Py3.13+) matches whole path with ** support.
                if rel_posix.full_match(pat):
                    skipped.add(name)
                    log.debug("path_excluded", path=str(dir_path / name), pattern=pat)
                    break
        return skipped

    return ignore


def backup_paths(
    paths: list[Path],
    staging_dir: Path,
    exclude_patterns: list[str] | None = None,
) -> list[FileEntry]:
    """Copy each path into staging_dir/files/<path.name>.

    Returns a list of FileEntry dicts describing what was actually copied
    (skips non-existing entries). The entries are used to build the manifest.

    `exclude_patterns` — glob-style patterns matched against paths RELATIVE
    to each source root. Use '**' for recursive wildcards (e.g. '**/.git',
    '**/node_modules', '**/__pycache__').
    """
    exclude_patterns = exclude_patterns or []
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
                ignore = _make_exclude_matcher(src, exclude_patterns)
                shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True, ignore=ignore)
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
