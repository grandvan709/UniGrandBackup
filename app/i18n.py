"""Localization — translation templates for logs and Telegram messages."""

from __future__ import annotations

from typing import Literal

Lang = Literal["ru", "en"]
DEFAULT_LANG: Lang = "ru"


# Log event templates. Keys match the `event` string passed to log.info(...).
# Variables in {braces} are pulled from kwargs (event_dict) at render time.
# Translations missing in one language fall back to the other.
LOG_MESSAGES: dict[str, dict[Lang, str]] = {
    # --- Startup ---
    "service_scheduled": {
        "ru": "Сервис '{name}' поставлен в расписание ({schedule})",
        "en": "Service '{name}' scheduled ({schedule})",
    },
    "service_skipped_disabled": {
        "ru": "Сервис '{name}' пропущен (disabled)",
        "en": "Service '{name}' skipped (disabled)",
    },
    "scheduler_starting": {
        "ru": "Планировщик запущен — {tasks_str} в очереди",
        "en": "Scheduler started — {tasks_str} queued",
    },
    "shutdown_requested": {
        "ru": "Получен сигнал остановки ({signal})",
        "en": "Shutdown signal received ({signal})",
    },
    "invalid_cron_schedule": {
        "ru": "Некорректное cron-расписание для '{service}': '{schedule}' — {error}",
        "en": "Invalid cron schedule for '{service}': '{schedule}' — {error}",
    },
    # --- Backup runner ---
    "backup_start": {
        "ru": "Запуск бэкапа: '{service}'",
        "en": "Starting backup: '{service}'",
    },
    "backup_done": {
        "ru": "Бэкап готов: '{service}' → {archive} (за {duration_s}с, {errors_str})",
        "en": "Backup done: '{service}' → {archive} (took {duration_s}s, {errors_str})",
    },
    "backup_failed": {
        "ru": "Бэкап провален: '{service}' — {error}",
        "en": "Backup failed: '{service}' — {error}",
    },
    "scheduled_job_failed": {
        "ru": "Запланированная задача провалена: '{service}' — {error}",
        "en": "Scheduled job failed: '{service}' — {error}",
    },
    "archive_built": {
        "ru": "Архив собран: {archive} ({size})",
        "en": "Archive built: {archive} ({size})",
    },
    # --- Files ---
    "path_missing_skipped": {
        "ru": "Путь не найден, пропускаем: {path}",
        "en": "Path missing, skipping: {path}",
    },
    "path_copied": {
        "ru": "Скопирован путь: {source} → {dest}",
        "en": "Path copied: {source} → {dest}",
    },
    "path_copy_failed": {
        "ru": "Не удалось скопировать {path}: {error}",
        "en": "Failed to copy {path}: {error}",
    },
    "files_step_failed": {
        "ru": "Сбор файлов провалился: {error}",
        "en": "Files step failed: {error}",
    },
    # --- Postgres ---
    "postgres_dump_start": {
        "ru": "pg_dump: '{database}' @ {host} (формат: {format})",
        "en": "pg_dump: '{database}' @ {host} (format: {format})",
    },
    "postgres_dump_done": {
        "ru": "pg_dump готов: '{database}' ({size_bytes} байт)",
        "en": "pg_dump done: '{database}' ({size_bytes} bytes)",
    },
    "postgres_dump_failed": {
        "ru": "pg_dump провалился для '{database}' @ {host}: {stderr}",
        "en": "pg_dump failed for '{database}' @ {host}: {stderr}",
    },
    # --- SQLite ---
    "sqlite_dump_start": {
        "ru": "sqlite3 .dump: {path}",
        "en": "sqlite3 .dump: {path}",
    },
    "sqlite_dump_done": {
        "ru": "sqlite .dump готов: {dest} ({size_bytes} байт)",
        "en": "sqlite .dump done: {dest} ({size_bytes} bytes)",
    },
    "sqlite_dump_failed": {
        "ru": "sqlite .dump провалился для {path}: {stderr}",
        "en": "sqlite .dump failed for {path}: {stderr}",
    },
    "db_step_failed": {
        "ru": "Сбор БД провалился: {error}",
        "en": "Database step failed: {error}",
    },
    # --- Local storage ---
    "local_saved": {
        "ru": "Архив сохранён локально: {file} ({size_bytes} байт)",
        "en": "Archive saved locally: {file} ({size_bytes} bytes)",
    },
    "local_rotated_out": {
        "ru": "Архив удалён по ротации: {file}",
        "en": "Archive rotated out: {file}",
    },
    "local_rotate_failed": {
        "ru": "Не удалось удалить старый архив {file}: {error}",
        "en": "Failed to delete old archive {file}: {error}",
    },
    # --- Telegram ---
    "telegram_send_start": {
        "ru": "Отправка в Telegram: {file} ({size}) → chat {chat_id} / topic {thread_id}",
        "en": "Sending to Telegram: {file} ({size}) → chat {chat_id} / topic {thread_id}",
    },
    "telegram_send_done": {
        "ru": "Отправлено в Telegram: {file}",
        "en": "Sent to Telegram: {file}",
    },
    "telegram_send_failed": {
        "ru": "Ошибка отправки в Telegram: {file} (status {status}) — {body}",
        "en": "Telegram send failed: {file} (status {status}) — {body}",
    },
    "telegram_init_failed": {
        "ru": "Ошибка инициализации Telegram-клиента: {error}",
        "en": "Telegram client init failed: {error}",
    },
    "telegram_send_pipeline_failed": {
        "ru": "Ошибка в пайплайне отправки Telegram: {error}",
        "en": "Telegram send pipeline failed: {error}",
    },
    "telegram_text_failed": {
        "ru": "Ошибка отправки текстового сообщения в Telegram (status {status})",
        "en": "Telegram text send failed (status {status})",
    },
    "telegram_api_not_ok": {
        "ru": "Telegram API ответил не ok для {file}",
        "en": "Telegram API not ok for {file}",
    },
    "telegram_file_too_large": {
        "ru": "Файл слишком большой для Telegram: {file} ({size}, лимит {limit})",
        "en": "File too large for Telegram: {file} ({size}, limit {limit})",
    },
    # --- Restore ---
    "restore_start": {
        "ru": "Запуск восстановления из архива: {archive}",
        "en": "Starting restore from archive: {archive}",
    },
    "restore_manifest_loaded": {
        "ru": "Манифест прочитан: сервис '{service}', создан {created_at}",
        "en": "Manifest loaded: service '{service}', created {created_at}",
    },
    "restore_files_start": {
        "ru": "Восстановление файлов в исходные пути",
        "en": "Restoring files to original paths",
    },
    "restore_file_done": {
        "ru": "Восстановлено: {dest}",
        "en": "Restored: {dest}",
    },
    "restore_file_skipped": {
        "ru": "Пропущен (требуется подтверждение --force): {dest}",
        "en": "Skipped (requires --force): {dest}",
    },
    "restore_compose_up": {
        "ru": "Поднимаю docker compose в {dir}",
        "en": "Starting docker compose in {dir}",
    },
    "restore_compose_done": {
        "ru": "docker compose поднят",
        "en": "docker compose started",
    },
    "restore_compose_skipped": {
        "ru": "docker-compose.yml не найден в восстановленных файлах — пропускаю",
        "en": "docker-compose.yml not found among restored files — skipping",
    },
    "restore_db_wait": {
        "ru": "Жду готовности БД {host}:{port}/{database}...",
        "en": "Waiting for database {host}:{port}/{database}...",
    },
    "restore_db_ready": {
        "ru": "БД готова, заливаю дамп",
        "en": "Database ready, loading dump",
    },
    "restore_db_done": {
        "ru": "Дамп БД '{database}' залит",
        "en": "Database dump for '{database}' loaded",
    },
    "restore_db_failed": {
        "ru": "Не удалось залить дамп БД '{database}': {error}",
        "en": "Failed to load database dump '{database}': {error}",
    },
    "restore_done": {
        "ru": "Восстановление завершено: '{service}'",
        "en": "Restore completed: '{service}'",
    },
    "restore_failed": {
        "ru": "Восстановление провалено: {archive} — {error}",
        "en": "Restore failed: {archive} — {error}",
    },
    "restore_entry_missing": {
        "ru": "Запись из манифеста не найдена в архиве: {archive_path}",
        "en": "Manifest entry not present in archive: {archive_path}",
    },
    "restore_network_attached": {
        "ru": "Подключился к docker-сети '{network}' (вместе с {target})",
        "en": "Attached to docker network '{network}' (alongside {target})",
    },
    "restore_network_attach_failed": {
        "ru": "Не удалось подключиться к сети '{network}': {error}",
        "en": "Failed to attach to network '{network}': {error}",
    },
    "restore_network_inspect_failed": {
        "ru": "Не удалось осмотреть контейнер '{target}': {error}",
        "en": "Failed to inspect container '{target}': {error}",
    },
    "restore_chown_failed": {
        "ru": "Не удалось сменить владельца: {dest} — {error}",
        "en": "chown failed: {dest} — {error}",
    },
    "restore_chmod_failed": {
        "ru": "Не удалось выставить mode: {dest} — {error}",
        "en": "chmod failed: {dest} — {error}",
    },
}


# Telegram caption strings (full, not log events).
TG_MESSAGES: dict[str, dict[Lang, str]] = {
    "title": {"ru": "UniGrandBackup", "en": "UniGrandBackup"},
    "service": {"ru": "Сервис", "en": "Service"},
    "status_ok": {"ru": "OK", "en": "OK"},
    "status": {"ru": "Статус", "en": "Status"},
    "time": {"ru": "Время", "en": "Time"},
    "duration": {"ru": "Длится", "en": "Duration"},
    "size": {"ru": "Размер", "en": "Size"},
    "contents": {"ru": "Содержимое", "en": "Contents"},
    "files": {"ru": "Файлы", "en": "Files"},
    "postgres": {"ru": "PostgreSQL", "en": "PostgreSQL"},
    "sqlite": {"ru": "SQLite", "en": "SQLite"},
    "errors_label": {"ru": "Ошибки", "en": "Errors"},
    "alert_pipeline_failed": {
        "ru": (
            "⚠️ <b>UniGrandBackup [{service}]</b>\n"
            "Архив бэкапа собран локально, но загрузка в Telegram сорвалась:\n"
            "<code>{error}</code>"
        ),
        "en": (
            "⚠️ <b>UniGrandBackup [{service}]</b>\n"
            "Backup archive built locally but Telegram upload failed:\n"
            "<code>{error}</code>"
        ),
    },
}


# Banner / CLI strings (printed via print(), not structlog).
UI_MESSAGES: dict[str, dict[Lang, str]] = {
    "banner_title": {
        "ru": "UniGrandBackup v{version}",
        "en": "UniGrandBackup v{version}",
    },
    "banner_tz": {"ru": "Таймзона", "en": "Timezone"},
    "banner_storage": {"ru": "Хранилище", "en": "Storage"},
    "banner_retention": {"ru": "retention", "en": "retention"},
    "banner_lang": {"ru": "Язык", "en": "Language"},
    "banner_services_total": {
        "ru": "Сервисы: всего {total}, активных {enabled}",
        "en": "Services: total {total}, enabled {enabled}",
    },
    "banner_service_enabled": {"ru": "включён", "en": "enabled"},
    "banner_service_disabled": {"ru": "выключен", "en": "disabled"},
    "cli_service_not_found": {
        "ru": "Сервис '{name}' не найден. Доступные: {available}",
        "en": "Service '{name}' not found. Available: {available}",
    },
    "cli_archive_not_found": {
        "ru": "Архив не найден: {path}",
        "en": "Archive not found: {path}",
    },
    "cli_config_load_failed": {
        "ru": "Не удалось загрузить конфиг {path}: {error}",
        "en": "Failed to load config {path}: {error}",
    },
}


def _lookup(table: dict[str, dict[Lang, str]], key: str, lang: Lang) -> str | None:
    entry = table.get(key)
    if not entry:
        return None
    return entry.get(lang) or entry.get("en") or entry.get("ru")


def t_log(lang: Lang, event_key: str, **kwargs) -> str | None:
    """Translate a structured log event. Returns None if no translation exists."""
    template = _lookup(LOG_MESSAGES, event_key, lang)
    if template is None:
        return None
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def t_tg(lang: Lang, key: str, **kwargs) -> str:
    """Translate a Telegram caption string. Falls back to the key itself."""
    template = _lookup(TG_MESSAGES, key, lang) or key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def t_ui(lang: Lang, key: str, **kwargs) -> str:
    """Translate a CLI/banner string. Falls back to the key itself."""
    template = _lookup(UI_MESSAGES, key, lang) or key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


# ─── Pluralization ────────────────────────────────────────────────────────────
#
# Russian has three plural forms (one / few / many) selected by mod-10/mod-100
# rules. English just has singular/plural.

# (singular, few, many) — for Russian
RU_PLURALS: dict[str, tuple[str, str, str]] = {
    "paths": ("путь", "пути", "путей"),
    "errors": ("ошибка", "ошибки", "ошибок"),
    "tasks": ("задача", "задачи", "задач"),
}

# (singular, plural) — for English
EN_PLURALS: dict[str, tuple[str, str]] = {
    "paths": ("path", "paths"),
    "errors": ("error", "errors"),
    "tasks": ("task", "tasks"),
}


def _ru_plural_form(n: int, forms: tuple[str, str, str]) -> str:
    """Pick the right Russian plural form for n (one / few / many)."""
    n = abs(int(n))
    mod100 = n % 100
    mod10 = n % 10
    if mod10 == 1 and mod100 != 11:
        return forms[0]
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return forms[1]
    return forms[2]


def t_count(lang: Lang, key: str, n: int) -> str:
    """Render '<n> <noun>' with proper plural form for the language.

    Examples:
        t_count('ru', 'paths',  1) → '1 путь'
        t_count('ru', 'paths',  2) → '2 пути'
        t_count('ru', 'paths',  5) → '5 путей'
        t_count('ru', 'errors', 0) → '0 ошибок'
        t_count('en', 'paths',  1) → '1 path'
        t_count('en', 'paths',  2) → '2 paths'

    If the key is unknown, returns just the number as a string.
    """
    if lang == "ru":
        forms_ru = RU_PLURALS.get(key)
        if forms_ru is not None:
            return f"{n} {_ru_plural_form(n, forms_ru)}"
    forms_en = EN_PLURALS.get(key)
    if forms_en is not None:
        return f"{n} {forms_en[0] if abs(int(n)) == 1 else forms_en[1]}"
    return str(n)
