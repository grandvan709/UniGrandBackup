"""Config loader and validation (config.yaml → Pydantic models)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class GlobalConfig(BaseModel):
    local_storage_path: Path = Path("/var/backups")
    local_retention: int = Field(default=7, ge=1)
    timezone: str = "UTC"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    language: Literal["ru", "en"] = "ru"


class PostgresDB(BaseModel):
    kind: Literal["postgres"] = "postgres"
    host: str
    port: int = 5432
    user: str
    password_env: str
    database: str
    format: Literal["custom", "plain"] = "custom"

    def password(self) -> str:
        value = os.environ.get(self.password_env)
        if not value:
            raise RuntimeError(
                f"Postgres password env '{self.password_env}' is empty or unset"
            )
        return value


class SQLiteDB(BaseModel):
    kind: Literal["sqlite"] = "sqlite"
    path: Path


Database = PostgresDB | SQLiteDB


class TelegramConfig(BaseModel):
    bot_token_env: str
    chat_id: int | str
    thread_id: int | None = None
    send_last_only: bool = True
    send_summary: bool = True  # текстовое summary-сообщение с описанием

    def bot_token(self) -> str:
        value = os.environ.get(self.bot_token_env)
        if not value:
            raise RuntimeError(
                f"Telegram bot token env '{self.bot_token_env}' is empty or unset"
            )
        return value


class ServiceConfig(BaseModel):
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    enabled: bool = True
    schedule: str  # cron expression — APScheduler CronTrigger.from_crontab
    paths: list[Path] = Field(default_factory=list)
    databases: list[Database] = Field(default_factory=list)
    local_retention: int | None = None  # переопределяет global, если задано
    telegram: TelegramConfig | None = None

    @field_validator("paths", mode="before")
    @classmethod
    def _coerce_paths(cls, v):
        # YAML может отдать строки — превратим в Path
        if isinstance(v, list):
            return [Path(item) if not isinstance(item, Path) else item for item in v]
        return v


class Config(BaseModel):
    global_: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    services: list[ServiceConfig] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    def effective_retention(self, service: ServiceConfig) -> int:
        return service.local_retention or self.global_.local_retention


def load_config(path: Path | str) -> Config:
    """Read YAML file and return validated Config."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config.model_validate(raw)
