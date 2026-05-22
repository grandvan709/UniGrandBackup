"""UniGrandBackup entrypoint.

Modes:
  daemon  (default): start APScheduler, run cron-based jobs forever
  run     <service>: run one service immediately and exit
  list:              print loaded services and exit
  restore <archive>: restore a backup archive (files + DB)
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from . import __version__
from .config import Config, ServiceConfig, load_config
from .i18n import t_count, t_ui
from .runner import BackupRunner
from .utils import setup_logging

log = structlog.get_logger(__name__)


# ─── pretty banner (printed before structlog logs start) ──────────────────────
_ANSI_RESET = "\033[0m"
_ANSI_BOLD = "\033[1m"
_ANSI_CYAN = "\033[36m"
_ANSI_GRAY = "\033[90m"
_ANSI_GREEN = "\033[32m"
_ANSI_DIM = "\033[2m"
_BANNER_WIDTH = 64


def _use_color() -> bool:
    return os.environ.get("NO_COLOR") not in ("1", "true", "yes")


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_ANSI_RESET}" if _use_color() else text


def _print_banner(config: Config) -> None:
    lang = config.global_.language
    enabled = [s for s in config.services if s.enabled]
    bar = "━" * _BANNER_WIDTH

    title = t_ui(lang, "banner_title", version=__version__)
    print(_c(bar, _ANSI_CYAN))
    print(_c(f"  🗄  {title}", _ANSI_BOLD + _ANSI_CYAN))
    print(_c(bar, _ANSI_CYAN))
    print(
        f"  {t_ui(lang, 'banner_tz'):<10} "
        f"{_c(config.global_.timezone, _ANSI_GREEN)}"
    )
    print(
        f"  {t_ui(lang, 'banner_storage'):<10} "
        f"{_c(str(config.global_.local_storage_path), _ANSI_GREEN)} "
        f"{_c('(' + t_ui(lang, 'banner_retention') + '=' + str(config.global_.local_retention) + ')', _ANSI_DIM)}"
    )
    print(
        f"  {t_ui(lang, 'banner_lang'):<10} "
        f"{_c(lang.upper(), _ANSI_GREEN)}"
    )
    print(
        f"  {_c(t_ui(lang, 'banner_services_total', total=len(config.services), enabled=len(enabled)), _ANSI_BOLD)}"
    )
    for s in config.services:
        marker = _c("✓", _ANSI_GREEN) if s.enabled else _c("·", _ANSI_GRAY)
        state = t_ui(lang, "banner_service_enabled") if s.enabled else t_ui(lang, "banner_service_disabled")
        retention = s.local_retention or config.global_.local_retention
        line = (
            f"    {marker} "
            f"{s.name:<22} "
            f"{_c('schedule', _ANSI_DIM)}={_c(repr(s.schedule), _ANSI_GREEN)} "
            f"{_c('retention', _ANSI_DIM)}={retention} "
            f"{_c('(' + state + ')', _ANSI_DIM)}"
        )
        print(line)
    print(_c(bar, _ANSI_CYAN))


def _run_one(config: Config, name: str) -> int:
    service = next((s for s in config.services if s.name == name), None)
    if service is None:
        print(
            t_ui(
                config.global_.language,
                "cli_service_not_found",
                name=name,
                available=", ".join(s.name for s in config.services),
            ),
            file=sys.stderr,
        )
        return 2
    if not service.enabled:
        log.warning("service_disabled", name=name)
    try:
        BackupRunner(config, service).run()
        return 0
    except Exception as e:
        log.error("backup_failed", service=name, error=str(e), exc_info=True)
        return 1


def _make_job(config: Config, service: ServiceConfig):
    def job() -> None:
        try:
            BackupRunner(config, service).run()
        except Exception as e:
            log.error("scheduled_job_failed", service=service.name, error=str(e), exc_info=True)
    return job


def _run_daemon(config: Config) -> int:
    try:
        tz = ZoneInfo(config.global_.timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    scheduler = BlockingScheduler(timezone=tz)

    for service in config.services:
        if not service.enabled:
            log.info("service_skipped_disabled", name=service.name)
            continue
        try:
            trigger = CronTrigger.from_crontab(service.schedule, timezone=tz)
        except Exception as e:
            log.error(
                "invalid_cron_schedule",
                service=service.name,
                schedule=service.schedule,
                error=str(e),
            )
            return 3
        scheduler.add_job(
            _make_job(config, service),
            trigger=trigger,
            id=f"backup-{service.name}",
            name=f"backup {service.name}",
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )
        log.info(
            "service_scheduled",
            name=service.name,
            schedule=service.schedule,
        )

    def _on_stop(signum, frame):
        log.info("shutdown_requested", signal=signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)

    log.info(
        "scheduler_starting",
        tasks_str=t_count(config.global_.language, "tasks", len(scheduler.get_jobs())),
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


def _parse_remap_owner(value: str | None) -> tuple[int, int] | None:
    """Parse '--remap-owner UID:GID' value. Raises ValueError on bad input."""
    if not value:
        return None
    try:
        uid_str, gid_str = value.split(":", 1)
        return (int(uid_str), int(gid_str))
    except (ValueError, AttributeError) as e:
        raise ValueError(
            f"--remap-owner must be UID:GID with integer values (e.g. 1000:1000), got {value!r}"
        ) from e


def _run_restore(
    config: Config,
    archive: Path,
    force: bool,
    no_compose: bool,
    skip_db: bool,
    db_only: bool,
    remap_owner: str | None,
) -> int:
    """Delegated to restore.py so that the import is lazy."""
    from .restore import restore_archive

    if not archive.is_file():
        print(
            t_ui(config.global_.language, "cli_archive_not_found", path=str(archive)),
            file=sys.stderr,
        )
        return 2
    try:
        remap = _parse_remap_owner(remap_owner)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    try:
        restore_archive(
            config,
            archive,
            force=force,
            run_compose=not no_compose,
            skip_db=skip_db,
            db_only=db_only,
            remap_owner=remap,
        )
        return 0
    except Exception as e:
        log.error("restore_failed", archive=str(archive), error=str(e), exc_info=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="unigrandbackup")
    parser.add_argument(
        "--config",
        default=os.environ.get("UGB_CONFIG", "/app/config.yaml"),
        help="path to config.yaml (default: /app/config.yaml or $UGB_CONFIG)",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("daemon", help="run scheduler (default)")
    p_run = sub.add_parser("run", help="run one service immediately and exit")
    p_run.add_argument("name", help="service name from config.yaml")
    sub.add_parser("list", help="print loaded services and exit")

    p_restore = sub.add_parser("restore", help="restore a backup archive")
    p_restore.add_argument("archive", type=Path, help="path to .tar.gz archive")
    p_restore.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing files/database without confirmation",
    )
    p_restore.add_argument(
        "--no-compose",
        action="store_true",
        help="don't auto-run 'docker compose up' even if compose file is in archive",
    )
    p_restore.add_argument(
        "--skip-db",
        action="store_true",
        help="restore files + compose only; skip database dump replay",
    )
    p_restore.add_argument(
        "--db-only",
        action="store_true",
        help="restore database dumps only; skip files and compose-up",
    )
    p_restore.add_argument(
        "--remap-owner",
        metavar="UID:GID",
        help="override file ownership during restore (e.g. --remap-owner 1000:1000); "
             "default: preserve uid/gid recorded in manifest",
    )

    args = parser.parse_args(argv)
    cmd = args.cmd or "daemon"

    load_dotenv(dotenv_path=Path("/app/.env"), override=False)

    try:
        config = load_config(args.config)
    except Exception as e:
        # Logging not yet configured — print plain to stderr.
        print(f"FATAL: failed to load config {args.config}: {e}", file=sys.stderr)
        return 4

    setup_logging(
        level=config.global_.log_level,
        tz_name=config.global_.timezone,
        lang=config.global_.language,
    )

    if cmd == "list":
        _print_banner(config)
        return 0
    if cmd == "run":
        _print_banner(config)
        return _run_one(config, args.name)
    if cmd == "restore":
        _print_banner(config)
        return _run_restore(
            config,
            args.archive,
            force=args.force,
            no_compose=args.no_compose,
            skip_db=args.skip_db,
            db_only=args.db_only,
            remap_owner=args.remap_owner,
        )
    _print_banner(config)
    return _run_daemon(config)


if __name__ == "__main__":
    sys.exit(main())
