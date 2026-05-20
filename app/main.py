"""UniGrandBackup entrypoint.

Modes:
  daemon  (default): start APScheduler, run cron-based jobs forever
  run     <service>: run one service immediately and exit
  list:              print loaded services and exit
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from . import __version__
from .config import Config, ServiceConfig, load_config
from .runner import BackupRunner
from .utils import setup_logging

log = structlog.get_logger(__name__)


def _print_banner(config: Config) -> None:
    enabled = [s for s in config.services if s.enabled]
    print(f"UniGrandBackup v{__version__}")
    print(f"Timezone: {config.global_.timezone}")
    print(f"Storage:  {config.global_.local_storage_path} (retention: {config.global_.local_retention})")
    print(f"Services configured: {len(config.services)}, enabled: {len(enabled)}")
    for s in config.services:
        marker = "✓" if s.enabled else "·"
        print(f"  {marker} {s.name:24} schedule={s.schedule!r:24} retention={s.local_retention or config.global_.local_retention}")


def _run_one(config: Config, name: str) -> int:
    service = next((s for s in config.services if s.name == name), None)
    if service is None:
        log.error("service_not_found", name=name, available=[s.name for s in config.services])
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
    scheduler = BlockingScheduler(timezone=config.global_.timezone)

    for service in config.services:
        if not service.enabled:
            log.info("service_skipped_disabled", name=service.name)
            continue
        try:
            trigger = CronTrigger.from_crontab(service.schedule, timezone=config.global_.timezone)
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

    log.info("scheduler_starting", services=len(scheduler.get_jobs()))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


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

    args = parser.parse_args(argv)
    cmd = args.cmd or "daemon"

    load_dotenv(dotenv_path=Path("/app/.env"), override=False)

    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"FATAL: failed to load config {args.config}: {e}", file=sys.stderr)
        return 4

    setup_logging(config.global_.log_level)

    if cmd == "list":
        _print_banner(config)
        return 0
    if cmd == "run":
        return _run_one(config, args.name)
    _print_banner(config)
    return _run_daemon(config)


if __name__ == "__main__":
    sys.exit(main())
