"""Backup orchestration for a single service."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from . import __version__
from .config import Config, PostgresDB, ServiceConfig, SQLiteDB
from .i18n import t_count, t_tg
from .storage import LocalStorage, TelegramStorage
from .targets import backup_paths, dump_postgres, dump_sqlite
from .utils import ensure_dir, human_size, make_tarball, timestamp_for_filename

log = structlog.get_logger(__name__)


# Manifest format version. Bump when manifest schema changes incompatibly.
MANIFEST_FORMAT = "unigrandbackup-1"


class BackupRunner:
    """Runs one full backup cycle for one service."""

    def __init__(self, config: Config, service: ServiceConfig) -> None:
        self.config = config
        self.service = service
        self.tz = config.global_.timezone
        self.lang = config.global_.language
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

            files_meta: list[dict] = []
            db_meta: list[dict] = []
            errors: list[str] = []

            try:
                # 1. Paths (files / folders)
                if self.service.paths:
                    try:
                        files_meta = list(backup_paths(self.service.paths, staging_dir))
                    except Exception as e:
                        errors.append(f"files: {e}")
                        log.error("files_step_failed", error=str(e))

                # 2. Databases
                for db in self.service.databases:
                    try:
                        if isinstance(db, PostgresDB):
                            db_meta.append(dict(dump_postgres(db, staging_dir)))
                        elif isinstance(db, SQLiteDB):
                            db_meta.append(dict(dump_sqlite(db, staging_dir)))
                    except Exception as e:
                        errors.append(f"db {getattr(db, 'database', getattr(db, 'path', '?'))}: {e}")
                        log.error("db_step_failed", error=str(e))

                if not files_meta and not db_meta:
                    raise RuntimeError(
                        f"Service {self.service.name}: nothing to back up "
                        "(all paths missing and/or all dumps failed)"
                    )

                # 3. Write manifest.json into the staging dir (top level inside archive)
                self._write_manifest(
                    staging_dir,
                    started_at=started_at,
                    files_meta=files_meta,
                    db_meta=db_meta,
                )

                # 4. Pack into one tar.gz
                archive_path = staging_root / f"{staging_name}.tar.gz"
                make_tarball(staging_dir, archive_path)
                size = archive_path.stat().st_size
                log.info(
                    "archive_built",
                    archive=archive_path.name,
                    size=human_size(size),
                )

                # 5. Move into local storage + rotate
                saved = self.local.save(archive_path)
                self.local.rotate()

                # 6. Telegram (last only)
                duration_s = (datetime.now(ZoneInfo(self.tz)) - started_at).total_seconds()
                self._send_to_telegram(
                    saved,
                    started_at=started_at,
                    duration_s=duration_s,
                    files_meta=files_meta,
                    db_meta=db_meta,
                    errors=errors,
                )

                log.info(
                    "backup_done",
                    service=self.service.name,
                    archive=saved.name,
                    duration_s=round(duration_s, 2),
                    errors_str=t_count(self.lang, "errors", len(errors)),
                )
                return saved

            finally:
                shutil.rmtree(staging_root, ignore_errors=True)

    def _write_manifest(
        self,
        staging_dir: Path,
        *,
        started_at: datetime,
        files_meta: list[dict],
        db_meta: list[dict],
    ) -> None:
        """Embed manifest.json into the archive root.

        Restore uses this file to know what's inside and how to put it back.
        """
        # Snapshot only this service's config (without secrets — env var
        # NAMES are kept, values are not).
        try:
            service_dump = self.service.model_dump(mode="json", exclude_none=True)
        except Exception:
            service_dump = None

        manifest = {
            "format_version": MANIFEST_FORMAT,
            "app_version": __version__,
            "service": self.service.name,
            "created_at": started_at.isoformat(),
            "timezone": self.tz,
            "contents": {
                "files": files_meta,
                "databases": db_meta,
            },
            "service_config": service_dump,
        }
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _send_to_telegram(
        self,
        archive: Path,
        *,
        started_at: datetime,
        duration_s: float,
        files_meta: list[dict],
        db_meta: list[dict],
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
            caption = self._build_caption(
                archive,
                started_at=started_at,
                duration_s=duration_s,
                files_meta=files_meta,
                db_meta=db_meta,
                errors=errors,
            )
            tg.send_document(archive, caption=caption)
        except Exception as e:
            log.error("telegram_send_pipeline_failed", error=str(e))
            # Try to send a text alert instead so admin is at least notified
            if self.service.telegram.send_summary:
                try:
                    tg.send_text(
                        t_tg(self.lang, "alert_pipeline_failed",
                             service=self.service.name, error=str(e)[:300])
                    )
                except Exception:
                    pass

    def _build_caption(
        self,
        archive: Path,
        *,
        started_at: datetime,
        duration_s: float,
        files_meta: list[dict],
        db_meta: list[dict],
        errors: list[str],
    ) -> str:
        size = human_size(archive.stat().st_size)
        when = started_at.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
        duration = f"{duration_s:.1f} с" if self.lang == "ru" else f"{duration_s:.1f} s"

        if errors:
            status_icon = "⚠️"
            status_text = t_count(self.lang, "errors", len(errors))
        else:
            status_icon = "✅"
            status_text = t_tg(self.lang, "status_ok")

        lines = [
            f"🗄 <b>{t_tg(self.lang, 'title')}</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📦 <b>{t_tg(self.lang, 'service')}:</b> <code>{self.service.name}</code>",
            f"{status_icon} <b>{t_tg(self.lang, 'status')}:</b> {status_text}",
            f"🕐 <b>{t_tg(self.lang, 'time')}:</b> {when}",
            f"⏱ <b>{t_tg(self.lang, 'duration')}:</b> {duration}",
            f"📊 <b>{t_tg(self.lang, 'size')}:</b> {size}",
        ]

        contents_lines: list[str] = []
        if files_meta:
            contents_lines.append(
                f"   • 📁 <b>{t_tg(self.lang, 'files')}:</b> "
                f"{t_count(self.lang, 'paths', len(files_meta))}"
            )
        for db in db_meta:
            if db.get("kind") == "postgres":
                name = db.get("database", "?")
                contents_lines.append(
                    f"   • 🐘 <b>{t_tg(self.lang, 'postgres')}:</b> <code>{name}</code>"
                )
            elif db.get("kind") == "sqlite":
                name = Path(db.get("source_path", "?")).name
                contents_lines.append(
                    f"   • 🪶 <b>{t_tg(self.lang, 'sqlite')}:</b> <code>{name}</code>"
                )

        if contents_lines:
            lines.append("")
            lines.append(f"📥 <b>{t_tg(self.lang, 'contents')}:</b>")
            lines.extend(contents_lines)

        if errors:
            err_text = "\n".join(f"• {e[:120]}" for e in errors[:5])
            lines.append("")
            lines.append(f"⚠️ <b>{t_tg(self.lang, 'errors_label')}:</b>")
            lines.append(f"<i>{err_text}</i>")

        return "\n".join(lines)
