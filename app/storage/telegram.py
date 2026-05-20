"""Send backup artefacts to a Telegram chat/topic via Bot API."""

from __future__ import annotations

from pathlib import Path

import httpx
import structlog

from ..config import TelegramConfig
from ..utils import human_size

log = structlog.get_logger(__name__)


# Telegram caps file size at 50 MB for sendDocument from bots.
# Larger backups need to be split or sent via alternative method.
TELEGRAM_MAX_BOT_FILE_BYTES = 50 * 1024 * 1024


class TelegramStorage:
    """Wrapper around Bot API sendDocument with topic support."""

    def __init__(self, cfg: TelegramConfig) -> None:
        self.cfg = cfg
        self._token = cfg.bot_token()
        self._base = f"https://api.telegram.org/bot{self._token}"

    def send_document(
        self,
        file_path: Path,
        caption: str | None = None,
    ) -> None:
        """Upload file to chat/topic. Raises on HTTP/Telegram error."""
        if not file_path.is_file():
            raise FileNotFoundError(f"Document not found: {file_path}")

        size = file_path.stat().st_size
        if size > TELEGRAM_MAX_BOT_FILE_BYTES:
            log.warning(
                "telegram_file_too_large",
                file=file_path.name,
                size=human_size(size),
                limit=human_size(TELEGRAM_MAX_BOT_FILE_BYTES),
            )
            raise RuntimeError(
                f"File {file_path.name} ({human_size(size)}) exceeds Telegram bot "
                f"upload limit ({human_size(TELEGRAM_MAX_BOT_FILE_BYTES)}). "
                "Consider splitting or alternative storage."
            )

        data: dict[str, str | int] = {"chat_id": str(self.cfg.chat_id)}
        if self.cfg.thread_id is not None:
            data["message_thread_id"] = self.cfg.thread_id
        if caption:
            data["caption"] = caption[:1024]
            data["parse_mode"] = "HTML"

        log.info(
            "telegram_send_start",
            file=file_path.name,
            size=human_size(size),
            chat_id=self.cfg.chat_id,
            thread_id=self.cfg.thread_id,
        )

        with file_path.open("rb") as fh, httpx.Client(timeout=120) as client:
            response = client.post(
                f"{self._base}/sendDocument",
                data=data,
                files={"document": (file_path.name, fh)},
            )

        if response.status_code != 200:
            log.error(
                "telegram_send_failed",
                file=file_path.name,
                status=response.status_code,
                body=response.text[:300],
            )
            raise RuntimeError(
                f"Telegram sendDocument failed [{response.status_code}]: "
                f"{response.text[:300]}"
            )

        payload = response.json()
        if not payload.get("ok"):
            log.error("telegram_api_not_ok", file=file_path.name, payload=payload)
            raise RuntimeError(f"Telegram API not ok: {payload}")

        log.info("telegram_send_done", file=file_path.name)

    def send_text(self, text: str) -> None:
        """Optional summary/alert message."""
        data: dict[str, str | int] = {
            "chat_id": str(self.cfg.chat_id),
            "text": text[:4096],
            "parse_mode": "HTML",
        }
        if self.cfg.thread_id is not None:
            data["message_thread_id"] = self.cfg.thread_id

        with httpx.Client(timeout=30) as client:
            response = client.post(f"{self._base}/sendMessage", data=data)
        if response.status_code != 200:
            log.error(
                "telegram_text_failed",
                status=response.status_code,
                body=response.text[:300],
            )
