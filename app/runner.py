"""Backup orchestration for a single service."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from .config import Config, PostgresDB, ServiceConfig, SQLiteDB
from .storage import LocalStorage, TelegramStorage
from .targets import backup_paths, dump_postgres, dump_sqlite
from .utils import ensure_dir, human_size, make_tarball, timestamp_for_filename

log = structlog.get_logger(__name__)


class BackupRunner:
    """Runs one full backup cycle for one service."""

    def __init__(self, config: Config, service: ServiceConfig) -> None:
        self.config = config
        self.service = service
        self.tz = config.global_.timezone
        self.retention = config.effective_retention(service)
        self.local = LocalStorage(
            root=config.global_.local_storage_path,
            service_name=service.name,
            retention=self.retention,
        )

    def run(self) -> Path:
        """Execute backup cycle. Returns the local archive path."""
        bound = structlog.contextvars.bound_contextvars(service=self.service.name)
        with bound:
            log.info("backup_start", service=self.service.name)
            started_at = datetime.now(ZoneInfo(self.tz))

            staging_root = Path(
                tempfile.mkdtemp(prefix=f"ugb-{self.service.name}-")
            )
            stamp = timestamp_for_filename(self.tz)
            staging_name = f"{self.service.name}-{stamp}"
            staging_dir = staging_root / staging_name
            ensure_dir(staging_dir)

            paths_collected: list[Path] = []
            dumps: list[Path] = []
            errors: list[str] = []

            try:
                # 1. Paths (files / folders)
                if self.service.paths:
                    try:
                        paths_collected = backup_paths(self.service.paths, staging_dir)
                    except Exception as e:
                        errors.append(f"files: {e}")
                        log.error("files_step_failed", error=str(e))

                # 2. Databases
                for db in self.service.databases:
                    try:
                        if isinstance(db, PostgresDB):
                            dumps.append(dump_postgres(db, staging_dir))
                        elif isinstance(db, SQLiteDB):
                            dumps.append(dump_sqlite(db, staging_dir))
                    except Exception as e:
                        errors.append(f"db {getattr(db, 'database', getattr(db, 'path', '?'))}: {e}")
                        log.error("db_step_failed", error=str(e))

                if not paths_collected and not dumps:
                    raise RuntimeError(
                        f"Service {self.service.name}: nothing to back up "
                        "(all paths missing and/or all dumps failed)"
                    )

                # 3. Pack into one tar.gz
                archive_path = staging_root / f"{staging_name}.tar.gz"
                make_tarball(staging_dir, archive_path)
                size = archive_path.stat().st_size
                log.info(
                    "archive_built",
                    archive=archive_path.name,
                    size=human_size(size),
                )

                # 4. Move into local storage + rotate
                saved = self.local.save(archive_path)
                self.local.rotate()

                # 5. Telegram (last only)
                self._send_to_telegram(saved, started_at, errors)

                duration = (datetime.now(ZoneInfo(self.tz)) - started_at).total_seconds()
                log.info(
                    "backup_done",
                    service=self.service.name,
                    archive=saved.name,
                    duration_s=round(duration, 2),
                    errors=len(errors),
                )
                return saved

            finally:
                shutil.rmtree(staging_root, ignore_errors=True)

    def _send_to_telegram(
        self,
        archive: Path,
        started_at: datetime,
        errors: list[str],
    ) -> None:
        if not self.service.telegram:
            return

        try:
            tg = TelegramStorage(self.service.telegram)
        except Exception as e:
            log.error("telegram_init_failed", error=str(e))
            return

        try:
            caption = self._build_caption(archive, started_at, errors)
            tg.send_document(archive, caption=caption)
        except Exception as e:
            log.error("telegram_send_pipeline_failed", error=str(e))
            # Try to send a text alert instead so admin is at least notified
            if self.service.telegram.send_summary:
                try:
                    tg.send_text(
                        f"⚠️ <b>UniGrandBackup [{self.service.name}]</b>\n"
                        f"Backup archive built locally but Telegram upload failed:\n"
                        f"<code>{str(e)[:300]}</code>"
                    )
                except Exception:
                    pass

    def _build_caption(
        self,
        archive: Path,
        started_at: datetime,
        errors: list[str],
    ) -> str:
        size = human_size(archive.stat().st_size)
        status = "✅ OK" if not errors else f"⚠️ {len(errors)} ошибок"
        when = started_at.strftime("%Y-%m-%d %H:%M:%S %Z")
        lines = [
            f"<b>UniGrandBackup</b>",
            f"Сервис: <code>{self.service.name}</code>",
            f"Статус: {status}",
            f"Время: {when}",
            f"Размер: {size}",
        ]
        if errors:
            err_text = "\n".join(f"• {e[:120]}" for e in errors[:5])
            lines.append(f"<i>Ошибки:</i>\n{err_text}")
        return "\n".join(lines)
