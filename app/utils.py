"""Shared helpers — logging setup, timestamps, archive operations."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog


def setup_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging in JSON-line mode."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def timestamp_for_filename(tz_name: str = "UTC") -> str:
    """ISO-like timestamp safe for filenames: 20260520-091523."""
    tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    return datetime.now(tz).strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def make_tarball(source_dir: Path, dest: Path) -> Path:
    """Pack the entire source_dir into dest as tar.gz.

    Inside the archive, contents are stored under the basename of source_dir.
    """
    ensure_dir(dest.parent)
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(source_dir, arcname=source_dir.name)
    return dest


def run_subprocess(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 600,
    capture: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Wrap subprocess.run with sane defaults."""
    full_env: dict[str, str] | None = None
    if env is not None:
        full_env = {**os.environ, **env}
    try:
        return subprocess.run(
            cmd,
            check=False,
            env=full_env,
            timeout=timeout,
            text=True,
            capture_output=capture,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"Subprocess timeout after {timeout}s: {' '.join(cmd[:3])}..."
        ) from e


def human_size(n: int | float) -> str:
    """1234567 → '1.2 MB'."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} PB"
