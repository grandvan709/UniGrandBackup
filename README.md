<h1 align=center><code>UniGrandBackup</code></h1>

> Универсальный Docker-контейнер для регулярного бэкапа любого количества сервисов на одном Linux-сервере. Файлы + базы данных → локальная ротация N последних копий + автоматическая отправка свежей копии в Telegram-топик.

<p align=center>
Создан как замена встроенным «однострочным» бэкапам отдельных сервисов:
вместо <b>N разных механизмов</b> с разной судьбой и форматами — <b>один контейнер</b>, описывающий все сервисы в одном <code>config.yaml</code>,
с предсказуемым форматом архива, прозрачной ротацией и доставкой в Telegram.
</p>

---

## 🚀 Возможности

- ✅ **Одновременно несколько сервисов** в одном контейнере (каждый со своим расписанием cron-формата)
- ✅ **Файлы и папки** → tar.gz внутри единого артефакта, с сохранением uid/gid/mode
- ✅ **PostgreSQL 15-18** через `pg_dump -Fc` с auto-detect версии сервера + multi-version клиенты в образе
- ✅ **MySQL 5.7+ / 8.x** и **MariaDB 10.x / 11.x** через `mysqldump --single-transaction` (streaming → gzip)
- ✅ **SQLite** через `sqlite3 .dump` (gzip-compressed)
- ✅ **Локальная ротация** N последних архивов на сервис (старые удаляются автоматически)
- ✅ **Telegram** — последний созданный бэкап отправляется в указанный chat/топик (`message_thread_id` поддерживается)
- ✅ **Per-service настройки** Telegram-бота: разные сервисы могут писать в разные топики и даже использовать разных ботов
- ✅ **Cron-формат** расписаний через APScheduler
- ✅ **`paths_exclude`** — glob-паттерны (с поддержкой `**`) для исключения подпапок/файлов: `**/.git`, `**/node_modules`, `**/__pycache__`, `**/backups`
- ✅ **Восстановление одной командой** — `restore <archive>` распаковывает файлы, поднимает docker compose и заливает дамп БД. Формат архива самодостаточен (есть `manifest.json` со всей метой)
- ✅ **Локализация RU / EN** для логов и Telegram-сообщений (`global.language`)
- ✅ **Читаемые цветные логи** в `docker logs` (плюс опциональный JSON-режим через `LOG_FORMAT=json`)
- ✅ **Запуск разовый или daemon** — можно поднять как фоновый сервис или вызывать руками через `run <service>`

---

## 📋 Требования

- Linux-сервер с Docker + docker compose v2 (только для запуска **самого** UniGrandBackup)
- Telegram-бот с доступом к админ-чату / топику (для отправки артефактов)
- Доступ из контейнера UniGrandBackup до того, что бэкапится:
  - **Файлы** — bind-mount нужных директорий внутрь контейнера (например `/opt:/opt:ro`)
  - **Postgres** — сетевой доступ до `host:port` (docker-сеть с контейнером БД / `host.docker.internal` / прямой IP/DNS)
  - **SQLite** — путь к `.db`-файлу, доступный внутри контейнера через volume

> 💡 **Бэкапаемые сервисы НЕ обязаны быть в Docker.** Можно бэкапить bare-metal Postgres (через host-IP), SQLite-файлы любого приложения, systemd-сервисы и т. п. Docker-специфика только в команде `restore` — для не-докеризованного сервиса используется флаг `--no-compose`, дальше всё работает.

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
  language: ru                 # ru | en — язык логов и Telegram-сообщений

services:
  - name: myapp
    enabled: true
    schedule: "0 3 * * *"
    paths:
      - /opt/myapp/data
    databases:
      - kind: postgres
        host: myapp-db
        port: 5432
        user: myapp_user
        password_env: MYAPP_DB_PASSWORD
        database: myapp
        format: custom
    telegram:
      bot_token_env: BACKUP_BOT_TOKEN
      chat_id: -1001234567890
      thread_id: 42
```

### Глобальные настройки (`global:`)

| Поле | Тип | Default | Описание |
|:----:|:----:|:----:|:---|
| `local_storage_path` | path | `/var/backups` | Базовая директория для локальных архивов |
| `local_retention` | int | `7` | Сколько последних архивов хранить на сервис (можно переопределить) |
| `timezone` | str | `UTC` | IANA-таймзона для cron-расписаний и timestamp-ов в именах файлов и логов |
| `log_level` | str | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `language` | str | `ru` | Язык логов и Telegram-сообщений (`ru` / `en`) |

### Сервис (`services:` — массив, по элементу на сервис)

| Поле | Тип | Обязательно | Описание |
|:----:|:----:|:----:|:---|
| `name` | str | да | Уникальное имя (a-z, 0-9, `_`, `-`). Используется как имя поддиректории и префикс архива |
| `enabled` | bool | нет | `true` по умолчанию. `false` = пропустить при загрузке расписания |
| `schedule` | cron | да | Cron-выражение в формате APScheduler (`min hour day month dow`) |
| `paths` | list of paths | нет | Файлы/папки для бэкапа (упакуются tar внутрь одного архива) |
| `paths_exclude` | list of glob | нет | Glob-паттерны (с поддержкой `**`), исключаемые из `paths`. Пути сопоставляются **относительно** каждого корня в `paths`. Примеры: `**/.git`, `**/node_modules`, `**/__pycache__`, `**/backups`, `**/*.log` |
| `databases` | list | нет | Базы данных (см. ниже) |
| `local_retention` | int | нет | Переопределяет `global.local_retention` |
| `telegram` | object | нет | Отправка в Telegram (см. ниже) |

### Базы данных

UniGrandBackup поддерживает **PostgreSQL**, **MySQL/MariaDB** и **SQLite**. Матрица версий и тулзов:

| СУБД | Поддерживаемые версии | Backup tool | Restore tool | Формат архива |
|:--|:--|:--|:--|:--|
| **PostgreSQL** | 15, 16, 17, 18 (любая, с auto-detect) | `pg_dump -Fc` (custom) | `pg_restore --clean --if-exists --no-owner --no-acl` | `.dump` (binary) |
| **PostgreSQL plain** | 15, 16, 17, 18 | `pg_dump -Fp` | `psql -v ON_ERROR_STOP=1 -f` | `.sql` (plain SQL) |
| **MySQL** | 5.7, 8.0, 8.4 | `mysqldump --single-transaction --routines --triggers --events` | `mysql < gunzip` | `.sql.gz` |
| **MariaDB** | 10.5+, 10.6, 10.11, 11.x | `mysqldump --single-transaction ...` (через mariadb-client) | `mysql < gunzip` | `.sql.gz` |
| **SQLite** | 3.x | `sqlite3 .dump` | `sqlite3 < gunzip` | `.sql.gz` |

**PostgreSQL:**

```yaml
- kind: postgres
  host: myapp-db            # имя docker-контейнера или хост
  port: 5432
  user: myapp_user
  password_env: MYAPP_DB_PASSWORD     # имя env-переменной из .env
  database: myapp
  format: custom            # 'custom' (рек.) или 'plain'
  client_version: auto      # auto (default) | 15 | 16 | 17 | 18
                            # auto: детектит версию сервера через SHOW server_version_num
                            #       и подключает matching pg_dump из образа
```

Все 4 версии pg-клиентов (15/16/17/18) ставятся в образ через apt.postgresql.org. Используемая версия записывается в `manifest.json` (`client_version_used`), чтобы restore смог взять совместимый `pg_restore`.

**MySQL / MariaDB:**

```yaml
- kind: mysql               # 'mysql' или 'mariadb' — клиент один (mariadb-client)
  host: webapp-db
  port: 3306
  user: webapp
  password_env: WEBAPP_DB_PASSWORD
  database: webapp
```

Используется `mariadb-client` — он совместим с MySQL 5.7+, 8.x, 9.x и MariaDB 10.x/11.x на уровне протокола. Dump делается с `--single-transaction --routines --triggers --events`, поток сразу пайпится в gzip (без буфера в памяти).

**SQLite:**

```yaml
- kind: sqlite
  path: /opt/myapp/data/app.db    # путь должен быть доступен внутри контейнера
```

### Telegram

```yaml
telegram:
  bot_token_env: BACKUP_BOT_TOKEN   # имя env-переменной с токеном @BotFather
  chat_id: -1001234567890           # ID чата/группы (для топика — ID супергруппы)
  thread_id: 42                     # ID топика (опционально, для форумов)
  send_last_only: true              # отправлять только самый свежий архив (а не все)
  send_summary: true                # при ошибке отправки документа — слать текстовый алерт
```

### Переменные окружения (`.env`)

```ini
BACKUP_BOT_TOKEN=123456789:AAH...    # токен Telegram-бота от @BotFather
MYAPP_DB_PASSWORD=...                # пароль Postgres для myapp
```

⚠️ `.env` ОБЯЗАТЕЛЬНО в `.gitignore` и `chmod 600`. Имена переменных в `config.yaml` указываются как `*_env: NAME`, а сами значения — только в `.env`.

---

## 🐳 Docker сети

Чтобы UniGrandBackup мог достучаться до Postgres-контейнеров других сервисов, его контейнер должен быть подключён в те же docker-сети. В `docker-compose.yml` укажи через `external: true` все нужные сети:

```yaml
networks:
  myapp_network:
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
sudo docker compose exec unigrandbackup python -m app.main run myapp

# Показать список загруженных сервисов
sudo docker compose exec unigrandbackup python -m app.main list
```

---

## 📁 Структура артефактов

После каждого запуска один сервис создаёт **один** архив:

```
/var/backups/unigrandbackup/
├── myapp/
│   ├── myapp-20260520-030000.tar.gz       # сегодня
│   ├── myapp-20260519-030000.tar.gz
│   └── ...                                # хранится N=local_retention копий
└── filestore/
    ├── filestore-20260520-033000.tar.gz
    └── ...
```

Внутри одного `<service>-<YYYYMMDD-HHMMSS>.tar.gz`:

```
myapp-20260520-030000/
├── manifest.json              # метаданные бэкапа (формат, сервис, содержимое)
├── files/
│   ├── .env
│   └── data/...
└── databases/
    └── myapp.dump
```

`manifest.json` — описание содержимого, нужен для восстановления через `app.main restore`.
`databases/*.dump` — это `pg_dump -Fc` (восстановить через `pg_restore`).
`databases/*.sql.gz` — это gzipped `sqlite3 .dump` (восстановить через `gunzip | sqlite3 newdb.sqlite`).

---

## 💬 Пример Telegram-сообщения

```
🗄 UniGrandBackup
━━━━━━━━━━━━━━━━━━━━
📦 Сервис: myapp
✅ Статус: OK
🕐 Время:  2026-05-20 03:00:01 MSK
⏱ Длится:  12.4 с
📊 Размер: 12.4 MB

📥 Содержимое:
   • 📁 Файлы: 2 пути
   • 🐘 PostgreSQL: myapp
```

Сам файл `myapp-20260520-030000.tar.gz` приходит как `document` в тот же топик.

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

UniGrandBackup умеет **сам** восстанавливать архив: разворачивает файлы, опционально поднимает docker compose, заливает дамп БД. Используется отдельный compose-профиль `restore` — он монтирует `/opt` в режиме RW и пробрасывает `docker.sock`, поэтому daemon, который работает с RO-/opt, не трогается.

### Автоматическое восстановление

```bash
cd /opt/unigrandbackup

# 1. Положи архив в локальное хранилище бэкапов (или укажи свой путь)
sudo cp /path/to/myapp-20260520-030000.tar.gz \
        /var/backups/unigrandbackup/myapp/

# 2. Запусти restore (одноразовый контейнер с RW /opt + docker.sock)
sudo docker compose --profile restore run --rm unigrandbackup-restore \
        /var/backups/unigrandbackup/myapp/myapp-20260520-030000.tar.gz \
        --force
```

Флаги команды `restore`:

| Флаг | Описание |
|:---:|:---|
| `--force` | Перезаписать существующие файлы и контент БД без подтверждения. **Обязателен**, если что-то по целевым путям уже существует. |
| `--no-compose` | Не запускать `docker compose up -d`, даже если в архиве найден `docker-compose.yml`. Полезно, если контейнеры уже подняты. |
| `--skip-db` | Восстановить только файлы + compose, **не** трогать БД. Удобно когда хочешь сначала разобраться с приложением, а БД залить отдельно. |
| `--db-only` | Восстановить **только** БД-дампы; не трогать файлы и не запускать compose. Полезно если файлы уже на хосте, БД нужно подменить. |
| `--remap-owner UID:GID` | Переназначить владельца восстанавливаемых файлов (по умолчанию uid/gid берётся из манифеста). Пример: `--remap-owner 1000:1000`. |
| `--dry-run` | Распечатать план рестора (какие файлы, какие БД, куда compose) — **ничего не применяя**. Удобно перед запуском на проде. |

Логика работы:

1. Распаковка архива во временную директорию.
2. Чтение `manifest.json` — содержит схему `unigrandbackup-1`, имя сервиса, дату, описание содержимого, **uid/gid/mode** каждого пути.
3. Восстановление файлов в **исходные абсолютные пути** на хосте, с сохранением `uid`/`gid`/`mode` из манифеста (если запущены как root, что верно внутри docker-контейнера).
4. Поиск `docker-compose.yml` среди восстановленных файлов и `docker compose up -d` (можно отключить `--no-compose`). Вывод docker compose стримится в наши логи (видны прогресс билда / pull в real-time).
5. **Auto-attach к docker-сети БД-контейнера** — restore сам подключается к свежесозданным docker-сетям БД, чтобы `pg_isready -h <container_name>` мог резолвить имя.
6. Ожидание готовности БД через `pg_isready` (для Postgres).
7. Заливка дампа:
   - **Postgres custom-format** → `pg_restore --clean --if-exists --no-owner --no-acl`
   - **Postgres plain** → `psql -v ON_ERROR_STOP=1 -f`
   - **SQLite** → существующий файл переименовывается в `*.bak.<timestamp>`, дамп заливается заново через `sqlite3`

> 💡 Чтобы автоматический подъём compose сработал — добавь `docker-compose.yml` (или весь корень сервиса) в `services[].paths` сервиса.

### 🛠 Troubleshooting

**1. `permission denied` или `EACCES` при старте приложения после рестора**

Случай редкий, но встречается: bind-mount директория (например `./data` или `./logs`) была создана docker'ом как `root:root`, а приложение внутри контейнера работает под uid 1000 (`app`, `node`). В манифесте мы храним и восстанавливаем uid/gid, но если на новом хосте маппинг другой — поможет `--remap-owner`:

```bash
sudo docker compose --profile restore run --rm unigrandbackup-restore \
        /var/backups/myapp/myapp-20260520-030000.tar.gz \
        --force --remap-owner 1000:1000
```

Или после рестора руками: `sudo chown -R 1000:1000 /opt/myapp/data /opt/myapp/logs`.

**2. `pg_restore: error: unsupported version (1.16) in file header`**

Это значит дамп сделан клиентом более новой версии, чем тот pg_restore, которым ты пытаешься заливать. UniGrandBackup делает дамп через `pg_dump 17` из своего образа; если бэкапаемый сервер постарше (PG 15), а на новом хосте ты пытаешься залить через **локальный** pg_restore 15 — провалится.

Способы:
- Использовать наш restore (`docker compose --profile restore run ...`) — там pg_restore 17, читает все старые форматы.
- Или вручную: `docker run --rm --network <db_net> -e PGPASSWORD=... -v /dump:/dump:ro postgres:17-alpine pg_restore ...` (postgres:17 поймёт format 1.16).

**3. `pg_isready` падает таймаутом (`no response`)**

Если на свежем хосте restore проходит compose-up, но потом виснет на `pg_isready` 180 секунд и отваливается — `restore_network_attached` лог должен показывать что мы подключились к сети БД. Если его нет — проверь:
- `docker.sock` смонтирован в restore-контейнер (см. `docker-compose.yml`)?
- Docker CLI работает внутри: `docker ps` из restore-контейнера должен показывать список.

**4. Бэкап слишком большой для Telegram (>50 MB)**

Telegram bots не принимают файлы >50 MB. Способы:
- Подобрать `paths_exclude` агрессивнее (особенно `**/.git`, `**/node_modules`, `**/pgdata` для postgres bind-mounts).
- Локальная копия в `/var/backups/<service>/` всё равно сохранится — отправка в Telegram опциональна.

### Ручное восстановление (если нужно вытащить отдельные части)

**Распаковать архив:**
```bash
tar -xzf myapp-20260520-030000.tar.gz      # распакует в myapp-20260520-030000/
```

**Postgres custom-format:**
```bash
pg_restore -h <host> -U <user> -d <db> --clean --if-exists -j 4 \
    < myapp-20260520-030000/databases/<db>.dump
```

**SQLite:**
```bash
gunzip -c myapp-20260520-030000/databases/<db>.sql.gz | sqlite3 new-database.sqlite
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
