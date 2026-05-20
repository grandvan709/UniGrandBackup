"""Local-disk storage with N-most-recent retention."""

from __future__ import annotations

import shutil
from pathlib import Path

import structlog

from ..utils import ensure_dir

log = structlog.get_logger(__name__)


class LocalStorage:
    """Stores artefacts under <root>/<service>/ with file-count retention."""

    def __init__(self, root: Path, service_name: str, retention: int) -> None:
        if retention < 1:
            raise ValueError(f"retention must be >= 1, got {retention}")
        self.root = Path(root)
        self.service_name = service_name
        self.retention = retention
        self.dir = self.root / service_name

    def save(self, src: Path) -> Path:
        """Move src into the service directory.

        Uses shutil.move() instead of Path.replace() so that the move works
        across filesystem boundaries (e.g. /tmp tmpfs → /var/backups volume mount
        inside Docker — pure os.rename() fails with EXDEV / 'Invalid cross-device link').
        """
        ensure_dir(self.dir)
        dest = self.dir / src.name
        shutil.move(str(src), str(dest))
        log.info(
            "local_saved",
            service=self.service_name,
            file=dest.name,
            size_bytes=dest.stat().st_size,
        )
        return dest

    def rotate(self) -> list[Path]:
        """Delete old archives, keeping only `retention` most recent.

        Returns list of deleted paths.
        """
        if not self.dir.is_dir():
            return []
        archives = sorted(
            [p for p in self.dir.iterdir() if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        to_delete = archives[self.retention:]
        for old in to_delete:
            try:
                old.unlink()
                log.info(
                    "local_rotated_out",
                    service=self.service_name,
                    file=old.name,
                )
            except OSError as e:
                log.error(
                    "local_rotate_failed",
                    service=self.service_name,
                    file=old.name,
                    error=str(e),
                )
        return to_delete

    def latest(self) -> Path | None:
        """Return path to the newest archive (None if empty)."""
        if not self.dir.is_dir():
            return None
        archives = sorted(
            [p for p in self.dir.iterdir() if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return archives[0] if archives else None
