"""Storage backends — local disk + Telegram."""

from .local import LocalStorage
from .telegram import TelegramStorage

__all__ = ["LocalStorage", "TelegramStorage"]
