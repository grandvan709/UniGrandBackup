"""Collect files/folders into a staging directory."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import TypedDict

import structlog

log = structlog.get_logger(__name__)


class OwnerInfo(TypedDict, total=False):
    uid: int
    gid: int
    user: str | None
    group: str | None


class FileEntry(TypedDict):
    source: str         # original absolute path on host
    archive_path: str   # path inside archive (relative)
    kind: str           # "file" | "dir"
    owner: OwnerInfo    # uid/gid + symbolic names if resolvable
    mode: str           # octal string like "0755"


def _read_owner(path: Path) -> OwnerInfo:
    """Read uid/gid + try to resolve symbolic user/group names. Best-effort."""
    st = path.lstat()
    info: OwnerInfo = {"uid": st.st_uid, "gid": st.st_gid, "user": None, "group": None}
    try:
        import pwd
        info["user"] = pwd.getpwuid(st.st_uid).pw_name
    except (KeyError, ImportError, OSError):
        pass
    try:
        import grp
        info["group"] = grp.getgrgid(st.st_gid).gr_name
    except (KeyError, ImportError, OSError):
        pass
    return info


def _read_mode(path: Path) -> str:
    """Permission bits as a 4-digit octal string (e.g. '0755')."""
    return format(path.lstat().st_mode & 0o7777, "04o")


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
    (skips non-existing entries). Each entry records the source owner (uid/gid)
    and mode bits so `restore` can put them back exactly as they were on the
    original host.

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
                "owner": _read_owner(src),
                "mode": _read_mode(src),
            })
            log.debug("path_copied", source=str(src), dest=str(dest))
        except Exception as e:
            log.error("path_copy_failed", path=str(src), error=str(e))
            raise

    return copied
