"""Collect files/folders into a staging directory.

The copy preserves per-file uid/gid/mode on the staging side so the tar
archive built from staging carries the original owners (not root, even
though our daemon container itself runs as root).
"""

from __future__ import annotations

import os
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
    owner: OwnerInfo    # uid/gid + symbolic names of the root entry
    mode: str           # octal string like "0755" of the root entry


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
    return format(path.lstat().st_mode & 0o7777, "04o")


def _make_exclude_matcher(src_root: Path, patterns: list[str]):
    """Same logic as before — drop names whose relative path matches a pattern."""
    if not patterns:
        return lambda directory, names: set()

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
                if rel_posix.full_match(pat):
                    skipped.add(name)
                    log.debug("path_excluded", path=str(dir_path / name), pattern=pat)
                    break
        return skipped

    return ignore


def _stamp_meta(src: Path, dst: Path, *, can_chown: bool) -> None:
    """Mirror src.lstat() uid/gid/mode onto dst. Chown skipped if not root."""
    try:
        s = src.lstat()
    except OSError as e:
        log.warning("backup_stat_failed", path=str(src), error=str(e))
        return
    if can_chown:
        try:
            os.lchown(dst, s.st_uid, s.st_gid)
        except OSError as e:
            log.warning("backup_chown_failed", dest=str(dst), error=str(e))
    if not dst.is_symlink():
        try:
            os.chmod(dst, s.st_mode & 0o7777)
        except OSError as e:
            log.warning("backup_chmod_failed", dest=str(dst), error=str(e))


def _copy_tree_preserving_meta(
    src_root: Path,
    dst_root: Path,
    ignore,
    *,
    can_chown: bool,
) -> None:
    """Walk src_root → recreate at dst_root, copying uid/gid/mode of each entry.

    Replaces shutil.copytree because copytree creates directories with the
    process umask + current uid (root inside our container), losing the
    original ownership we want to ship in the tar.
    """
    dst_root.mkdir(parents=True, exist_ok=True)
    _stamp_meta(src_root, dst_root, can_chown=can_chown)

    # Walk src tree top-down so dirs exist before their children.
    for cur_dir, dirnames, filenames in os.walk(src_root, followlinks=False):
        cur_path = Path(cur_dir)
        # Apply ignore to skip excluded names BEFORE descending.
        skip = ignore(cur_dir, dirnames + filenames) if ignore else set()
        # Mutate dirnames in-place so os.walk doesn't descend into excluded dirs.
        dirnames[:] = [d for d in dirnames if d not in skip]

        rel = cur_path.relative_to(src_root)
        for dname in dirnames:
            src_d = cur_path / dname
            dst_d = dst_root / rel / dname
            if src_d.is_symlink():
                # treat as file-symlink below in filenames loop? os.walk
                # already split symlinks-to-dirs into dirnames when
                # followlinks=False ... actually no: with followlinks=False,
                # os.walk does NOT descend into symlinks but still lists them
                # in dirnames if they point to a dir. We must NOT recurse,
                # we just copy the symlink.
                _create_symlink(src_d, dst_d, can_chown=can_chown)
            else:
                dst_d.mkdir(exist_ok=True)
                _stamp_meta(src_d, dst_d, can_chown=can_chown)

        for fname in filenames:
            if fname in skip:
                continue
            src_f = cur_path / fname
            dst_f = dst_root / rel / fname
            if src_f.is_symlink():
                _create_symlink(src_f, dst_f, can_chown=can_chown)
            else:
                try:
                    shutil.copy2(src_f, dst_f, follow_symlinks=False)
                except OSError as e:
                    log.error("path_copy_failed", path=str(src_f), error=str(e))
                    raise
                _stamp_meta(src_f, dst_f, can_chown=can_chown)


def _create_symlink(src: Path, dst: Path, *, can_chown: bool) -> None:
    target = os.readlink(src)
    try:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(target, dst)
    except OSError as e:
        log.warning("backup_symlink_failed", dest=str(dst), error=str(e))
        return
    if can_chown:
        try:
            s = src.lstat()
            os.lchown(dst, s.st_uid, s.st_gid)
        except OSError as e:
            log.warning("backup_chown_failed", dest=str(dst), error=str(e))


def backup_paths(
    paths: list[Path],
    staging_dir: Path,
    exclude_patterns: list[str] | None = None,
) -> list[FileEntry]:
    """Copy each path into staging_dir/files/<path.name> preserving owners.

    `exclude_patterns` — glob patterns (with `**` support) matched RELATIVE
    to each source root in `paths`. Examples: `**/.git`, `**/node_modules`,
    `**/__pycache__`, `**/backups`, `**/*.log`.

    Per-file uid/gid/mode are preserved so the resulting tar archive carries
    the original ownership (uid 1000, etc.), not root from our daemon
    container's process uid. This is critical for restore: bind-mount targets
    like ./data must be owned by the application's uid for it to mkdir into
    them on startup.
    """
    exclude_patterns = exclude_patterns or []
    files_dir = staging_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    # geteuid is Linux-only; on Windows we skip chown entirely (irrelevant
    # there since the daemon container is always Linux).
    can_chown = hasattr(os, "geteuid") and os.geteuid() == 0
    if not can_chown:
        log.warning("backup_chown_unavailable_not_root",
                    note="archive owners will reflect current process uid")

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
                _copy_tree_preserving_meta(src, dest, ignore, can_chown=can_chown)
                kind = "dir"
            else:
                shutil.copy2(src, dest, follow_symlinks=False)
                _stamp_meta(src, dest, can_chown=can_chown)
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
