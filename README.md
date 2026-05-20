<h1 align=center><code>UniGrandBackup</code></h1>

> Универсальный Docker-контейнер для регулярного бэкапа любого количества сервисов на одном Linux-сервере. Файлы + базы данных → локальная ротация N последних копий + автоматическая отправка свежей копии в Telegram-топик.

<p align=center>
Создан как замена встроенным «однострочным» бэкапам отдельных сервисов (Bedolaga, n8n и т. п.):
вместо <b>N разных механизмов</b> с разной судьбой и форматами — <b>один контейнер</b>, описывающий все сервисы в одном <code>config.yaml</code>,
с предсказуемым форматом архива, прозрачной ротацией и доставкой в Telegram.
</p>

---

## 🚀 Возможности

- ✅ **Одновременно несколько сервисов** в одном контейнере (каждый со своим расписанием cron-формата)
- ✅ **Файлы и папки** → tar.gz внутри единого артефакта
- ✅ **PostgreSQL** через `pg_dump -Fc` (custom format, готов к `pg_restore -j`)
- ✅ **SQLite** через `sqlite3 .dump` (gzip-compressed)
- ✅ **Локальная ротация** N последних архивов на сервис (старые удаляются автоматически)
- ✅ **Telegram** — последний созданный бэкап отправляется в указанный chat/топик (`message_thread_id` поддерживается)
- ✅ **Per-service настройки** Telegram-бота: разные сервисы могут писать в разные топики и даже использовать разных ботов
- ✅ **Cron-формат** расписаний через APScheduler
- ✅ **Структурированные JSON-логи** через structlog
- ✅ **Запуск разовый или daemon** — можно поднять как фоновый сервис или вызывать руками через `run <service>`

---

## 📋 Требования

- Linux сервер с Docker + docker compose v2
- Доступ к docker-сетям бэкапаемых сервисов (для подключения к их Postgres-контейнерам)
- Telegram-бот с доступом к админ-чату / топику (для отправки артефактов)

---

## 🔧 Установка

### 1. Установить Docker (если ещё нет)

```bash
sudo curl -fsSL https://get.docker.com | sudo sh
```

### 2. Создать рабочую директорию

```bash
sudo mkdir -p /opt/unigrandbackup
cd /opt/unigrandbackup
```

### 3. Скачать `docker-compose.yml` и шаблоны конфига

```bash
sudo wget -O docker-compose.yml https://raw.githubusercontent.com/grandvan709/UniGrandBackup/master/docker-compose.yml
sudo wget -O config.yaml https://raw.githubusercontent.com/grandvan709/UniGrandBackup/master/examples/config.example.yaml
sudo wget -O .env https://raw.githubusercontent.com/grandvan709/UniGrandBackup/master/.env.example
```

### 4. Заполнить `config.yaml` и `.env`

```bash
sudo nano config.yaml   # секции services: под свои сервисы (см. ниже)
sudo nano .env          # реальные значения секретов (имена из *_env)
sudo chmod 600 .env
```

### 5. Создать локальную папку под архивы

```bash
sudo mkdir -p /var/backups/unigrandbackup
```

### 6. Поднять

```bash
sudo docker compose up -d
sudo docker compose logs -ft
```

При первом старте контейнер прочитает `config.yaml`, выведет резюме сервисов и встанет на расписание.

---

## ⚙️ Конфигурация

### Минимальный пример `config.yaml`

```yaml
global:
  local_storage_path: /var/backups
  local_retention: 7
  timezone: Europe/Moscow
  log_level: INFO

services:
  - name: bedolaga
    enabled: true
    schedule: "0 3 * * *"
    paths:
      - /opt/remnawave-bedolaga-telegram-bot/data
    databases:
      - kind: postgres
        host: remnawave_bot_db
        port: 5432
        user: remnawave_user
        password_env: BEDOLAGA_DB_PASSWORD
        database: remnawave_bot
        format: custom
    telegram:
      bot_token_env: BACKUP_BOT_TOKEN
      chat_id: -1003859501094
      thread_id: 42
```

### Глобальные настройки (`global:`)

| Поле | Тип | Default | Описание |
|:----:|:----:|:----:|:---|
| `local_storage_path` | path | `/var/backups` | Базовая директория для локальных архивов |
| `local_retention` | int | `7` | Сколько последних архивов хранить на сервис (можно переопределить) |
| `timezone` | str | `UTC` | IANA-таймзона для cron-расписаний и timestamp-ов в именах файлов |
| `log_level` | str | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### Сервис (`services:` — массив, по элементу на сервис)

| Поле | Тип | Обязательно | Описание |
|:----:|:----:|:----:|:---|
| `name` | str | да | Уникальное имя (a-z, 0-9, `_`, `-`). Используется как имя поддиректории и префикс архива |
| `enabled` | bool | нет | `true` по умолчанию. `false` = пропустить при загрузке расписания |
| `schedule` | cron | да | Cron-выражение в формате APScheduler (`min hour day month dow`) |
| `paths` | list of paths | нет | Файлы/папки для бэкапа (упакуются tar внутрь одного архива) |
| `databases` | list | нет | Базы данных (см. ниже) |
| `local_retention` | int | нет | Переопределяет `global.local_retention` |
| `telegram` | object | нет | Отправка в Telegram (см. ниже) |

### Базы данных

**PostgreSQL:**

```yaml
- kind: postgres
  host: remnawave_bot_db    # имя docker-контейнера или хост
  port: 5432
  user: remnawave_user
  password_env: BEDOLAGA_DB_PASSWORD   # имя env-переменной из .env
  database: remnawave_bot
  format: custom            # 'custom' (рек.) или 'plain'
```

**SQLite:**

```yaml
- kind: sqlite
  path: /opt/myapp/data/app.db    # путь должен быть доступен внутри контейнера
```

### Telegram

```yaml
telegram:
  bot_token_env: BACKUP_BOT_TOKEN   # имя env-переменной с токеном @BotFather
  chat_id: -1003859501094           # ID чата/группы (для топика — ID супергруппы)
  thread_id: 42                     # ID топика (опционально, для форумов)
  send_last_only: true              # отправлять только самый свежий архив (а не все)
  send_summary: true                # при ошибке отправки документа — слать текстовый алерт
```

### Переменные окружения (`.env`)

```ini
BACKUP_BOT_TOKEN=123456789:AAH...    # токен Telegram-бота от @BotFather
BEDOLAGA_DB_PASSWORD=...             # пароль Postgres для Bedolaga
N8N_DB_PASSWORD=...                  # пароль Postgres для n8n
```

⚠️ `.env` ОБЯЗАТЕЛЬНО в `.gitignore` и `chmod 600`. Имена переменных в `config.yaml` указываются как `*_env: NAME`, а сами значения — только в `.env`.

---

## 🐳 Docker сети

Чтобы UniGrandBackup мог достучаться до Postgres-контейнеров других сервисов, его контейнер должен быть подключён в те же docker-сети. В `docker-compose.yml` укажи через `external: true` все нужные сети:

```yaml
networks:
  bot_network:
    external: true
  automations:
    external: true
```

Их имена должны точно соответствовать тем что показывает `docker network ls`.

---

## 🚀 Запуск

```bash
# Поднять (daemon-режим, по расписанию)
sudo docker compose up -d

# Смотреть логи
sudo docker compose logs -ft

# Остановить
sudo docker compose down

# Перезагрузить с новой версией образа
sudo docker compose pull && sudo docker compose up -d && sudo docker compose logs -f -t

# Разовый бэкап одного сервиса (вне расписания, для проверки)
sudo docker compose exec unigrandbackup python -m app.main run bedolaga

# Показать список загруженных сервисов
sudo docker compose exec unigrandbackup python -m app.main list
```

---

## 📁 Структура артефактов

После каждого запуска один сервис создаёт **один** архив:

```
/var/backups/unigrandbackup/
├── bedolaga/
│   ├── bedolaga-20260520-030000.tar.gz   # сегодня
│   ├── bedolaga-20260519-030000.tar.gz
│   └── ...                                # хранится N=local_retention копий
├── n8n/
│   ├── n8n-20260520-033000.tar.gz
│   └── ...
└── claude-bridge/
    └── ...
```

Внутри одного `<service>-<YYYYMMDD-HHMMSS>.tar.gz`:

```
bedolaga-20260520-030000/
├── files/
│   ├── .env
│   └── data/...
└── databases/
    └── remnawave_bot.dump
```

`databases/*.dump` — это `pg_dump -Fc` (восстановить через `pg_restore`).
`databases/*.sql.gz` — это gzipped `sqlite3 .dump` (восстановить через `gunzip | sqlite3 newdb.sqlite`).

---

## 💬 Пример Telegram-сообщения

```
UniGrandBackup
Сервис: bedolaga
Статус: ✅ OK
Время: 2026-05-20 03:00:01 MSK
Размер: 12.4 MB
```

Сам файл `bedolaga-20260520-030000.tar.gz` приходит как `document` в тот же топик.

---

## 💡 Обновление

```bash
cd /opt/unigrandbackup
sudo docker compose down
sudo docker compose pull
sudo docker compose up -d && sudo docker compose logs -f -t
```

> Перед обновлением полезно сверить актуальность `config.yaml` с примером из репо (`examples/config.example.yaml`) — там бывают новые поля.

---

## 🔄 Восстановление

**Postgres custom-format:**
```bash
pg_restore -h <host> -U <user> -d <newdb> --clean --if-exists -j 4 < bedolaga-..../databases/<db>.dump
```

**SQLite:**
```bash
gunzip -c bedolaga-..../databases/<db>.sql.gz | sqlite3 new-database.sqlite
```

**Файлы:**
```bash
tar -xzf bedolaga-20260520-030000.tar.gz   # распакует в bedolaga-20260520-030000/files/
```

---

## 🛠 Разработка

```bash
git clone -b develop https://github.com/grandvan709/UniGrandBackup
cd UniGrandBackup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && cp examples/config.example.yaml config.yaml
python -m app.main list
python -m app.main run <service>
```

Релизы — git-теги `X.Y.Z`. GitHub Actions автоматически собирает Docker-образ и пушит в `grandvan/unigrandbackup:X.Y.Z` + `:latest`.

---

<p align=center>
    Если проект тебе полезен — поставь ⭐!<br>
    <br>
    USDT TRC20: <code>TL6gHETnKqNWV4D6GjiKKahkBsAwcyWfo8</code>
</p>

<p align=center>
    <a href="https://t.me/grand_van" target="_blank" rel="noopener noreferrer">
        <img src="https://img.shields.io/badge/Telegram-GrandVan-purple?logo=telegram&logoColor=white&labelColor=blue" alt="Chat me on Telegram">
    </a>
</p>
