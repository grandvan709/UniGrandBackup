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

from .i18n import DEFAULT_LANG, Lang, t_log


# ANSI codes — `docker logs` and most terminals render them; we strip if NO_COLOR=1.
_ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "gray": "\033[90m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "red_bold": "\033[1;31m",
    "blue": "\033[34m",
}

_LEVEL_COLOR = {
    "debug": _ANSI["gray"],
    "info": _ANSI["cyan"],
    "warning": _ANSI["yellow"],
    "error": _ANSI["red"],
    "critical": _ANSI["red_bold"],
}


def _make_tz_timestamper(tz: ZoneInfo):
    """Return a structlog processor that stamps events with tz-aware HH:MM:SS."""

    def stamp(_logger, _method, event_dict):
        event_dict["timestamp"] = datetime.now(tz).strftime("%H:%M:%S")
        return event_dict

    return stamp


def _make_translator(lang: Lang):
    """Return a processor that translates event_dict['event'] into `lang`."""

    def translate(_logger, _method, event_dict):
        event_key = event_dict.get("event")
        if not isinstance(event_key, str):
            return event_dict
        # Pull only kwargs that aren't structlog meta — they're the template vars
        meta_keys = {"event", "level", "timestamp", "logger", "exc_info", "stack_info"}
        kwargs = {k: v for k, v in event_dict.items() if k not in meta_keys}
        translated = t_log(lang, event_key, **kwargs)
        if translated is not None:
            event_dict["event"] = translated
            event_dict["_translated"] = True
        return event_dict

    return translate


def _make_pretty_renderer(use_color: bool):
    """Build a renderer that produces nice aligned output for docker logs."""

    def render(_logger, _method, event_dict) -> str:
        ts = event_dict.pop("timestamp", "")
        level = event_dict.pop("level", "info").lower()
        event = event_dict.pop("event", "")
        translated = event_dict.pop("_translated", False)

        # Drop noisy fields we don't want in output
        event_dict.pop("logger", None)
        exc_info = event_dict.pop("exc_info", None)
        stack_info = event_dict.pop("stack_info", None)

        level_label = level.upper()[:5].ljust(5)

        # When the event was translated, the kvs are already baked into the
        # message — don't repeat them at the end. Otherwise show as key=value.
        if translated:
            extra = ""
        else:
            kvs = " ".join(f"{k}={v}" for k, v in event_dict.items())
            extra = f"  {_ANSI['dim']}{kvs}{_ANSI['reset']}" if (kvs and use_color) else (f"  {kvs}" if kvs else "")

        if use_color:
            color = _LEVEL_COLOR.get(level, "")
            line = (
                f"{_ANSI['gray']}{ts}{_ANSI['reset']}  "
                f"{color}{level_label}{_ANSI['reset']}  "
                f"{event}{extra}"
            )
        else:
            line = f"{ts}  {level_label}  {event}{extra}"

        if exc_info:
            import traceback

            tb = "".join(traceback.format_exception(*exc_info)) if isinstance(exc_info, tuple) else str(exc_info)
            line += "\n" + tb.rstrip()
        if stack_info:
            line += "\n" + str(stack_info).rstrip()
        return line

    return render


def setup_logging(
    level: str = "INFO",
    tz_name: str = "UTC",
    lang: str = DEFAULT_LANG,
    log_format: str | None = None,
) -> None:
    """Configure structlog + stdlib logging.

    Args:
        level: DEBUG | INFO | WARNING | ERROR
        tz_name: IANA timezone name for log timestamps
        lang: 'ru' | 'en' — language for log messages
        log_format: 'pretty' | 'json' (default: env $LOG_FORMAT or 'pretty')
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
    # Tone down chatty 3rd-party loggers — httpx writes the full request URL
    # (which contains the Telegram bot token!). Bumping them to WARNING keeps
    # real errors visible but hides routine request-success noise.
    for noisy in ("httpx", "httpcore", "apscheduler", "apscheduler.scheduler", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    resolved_lang: Lang = "en" if lang == "en" else "ru"
    fmt = (log_format or os.environ.get("LOG_FORMAT") or "pretty").lower()
    use_color = os.environ.get("NO_COLOR") not in ("1", "true", "yes")

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _make_tz_timestamper(tz),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        _make_translator(resolved_lang),
    ]

    if fmt == "json":
        # When emitting JSON, use a full ISO timestamp instead of HH:MM:SS.
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors.append(_make_pretty_renderer(use_color))

    structlog.configure(
        processors=processors,
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
