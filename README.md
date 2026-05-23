<h1 align=center><code>UniGrandBackup</code></h1>

<p align="center">
  <img src="https://flagcdn.com/24x18/gb.png" height="14" alt="EN">&nbsp;<b>English</b>
  &nbsp;·&nbsp;
  <a href="./README_RU.md"><img src="https://flagcdn.com/24x18/ru.png" height="14" alt="RU">&nbsp;Русский</a>
</p>

> Universal Docker container for scheduled backups of any number of services on a single Linux host. Files + databases → local rotation of the last N copies + automatic delivery of the freshest archive to a Telegram topic.

<p align=center>
Built as a replacement for the ad-hoc one-liner backups each service ships:
instead of <b>N different mechanisms</b> with different fates and formats — <b>one container</b>
describing all services in one <code>config.yaml</code>, with a predictable archive format,
transparent rotation, and Telegram delivery.
</p>

---

## 🚀 Features

- ✅ **Multiple services in one container**, each with its own cron schedule
- ✅ **Files and directories** → tar.gz inside a single artifact, preserving uid/gid/mode
- ✅ **PostgreSQL 15–18** via `pg_dump -Fc` with server-version auto-detect + multi-version clients in the image
- ✅ **MySQL 5.7+ / 8.x** and **MariaDB 10.x / 11.x** via `mysqldump --single-transaction` (streaming → gzip)
- ✅ **SQLite** via `sqlite3 .dump` (gzip-compressed)
- ✅ **Local rotation** of the N most recent archives per service (older ones auto-deleted)
- ✅ **Telegram** — the latest archive is sent to the configured chat/topic (`message_thread_id` supported)
- ✅ **Per-service Telegram settings** — different services can post to different topics and even use different bots
- ✅ **Cron-style schedules** via APScheduler
- ✅ **`paths_exclude`** — glob patterns (with `**` support) to skip junk: `**/.git`, `**/node_modules`, `**/__pycache__`, `**/backups`
- ✅ **One-command restore** — `restore <archive>` unpacks files, brings up docker compose, and loads the DB dump. The archive is self-describing (`manifest.json` carries all metadata)
- ✅ **RU / EN localization** of logs and Telegram messages (`global.language`)
- ✅ **Readable color logs** in `docker logs` (plus an optional JSON mode via `LOG_FORMAT=json`)
- ✅ **One-shot or daemon** — run as a background service or invoke `run <service>` manually

---

## 📋 Requirements

- Linux server with Docker + docker compose v2 (only to run **UniGrandBackup itself**)
- A Telegram bot with access to the admin chat / topic (for delivering archives)
- The UniGrandBackup container must be able to reach whatever it's backing up:
  - **Files** — bind-mount the relevant directories into the container (e.g. `/opt:/opt:ro`)
  - **Postgres** — network reachability to `host:port` (same docker network as the DB container / `host.docker.internal` / a direct IP/DNS)
  - **SQLite** — path to the `.db` file accessible inside the container via a volume

> 💡 **The services you back up don't have to be in Docker.** You can back up a bare-metal Postgres (via host IP), SQLite files of any application, systemd services, and so on. The Docker-specific part lives only in the `restore` command — for a non-Dockerized service use the `--no-compose` flag and the rest still works.

---

## 🔧 Installation

### 1. Install Docker (if you don't have it)

```bash
sudo curl -fsSL https://get.docker.com | sudo sh
```

### 2. Create the working directory

```bash
sudo mkdir -p /opt/unigrandbackup
cd /opt/unigrandbackup
```

### 3. Download `docker-compose.yml` and the config templates

```bash
sudo wget -O docker-compose.yml https://raw.githubusercontent.com/grandvan709/UniGrandBackup/master/docker-compose.yml
sudo wget -O config.yaml https://raw.githubusercontent.com/grandvan709/UniGrandBackup/master/examples/config.example.yaml
sudo wget -O .env https://raw.githubusercontent.com/grandvan709/UniGrandBackup/master/.env.example
```

### 4. Fill in `config.yaml` and `.env`

```bash
sudo nano config.yaml   # describe your services under services: (see below)
sudo nano .env          # actual secret values (names come from *_env)
sudo chmod 600 .env
```

### 5. Create the local archive directory

```bash
sudo mkdir -p /var/backups/unigrandbackup
```

### 6. Start it

```bash
sudo docker compose up -d
sudo docker compose logs -ft
```

On first start the container reads `config.yaml`, prints a summary of services, and starts the scheduler.

---

## ⚙️ Configuration

### Minimal `config.yaml`

```yaml
global:
  local_storage_path: /var/backups
  local_retention: 7
  timezone: Europe/Moscow
  log_level: INFO
  language: en                 # ru | en — language for logs and Telegram messages

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

### Global settings (`global:`)

| Field | Type | Default | Description |
|:----:|:----:|:----:|:---|
| `local_storage_path` | path | `/var/backups` | Base directory for local archives |
| `local_retention` | int | `7` | How many recent archives to keep per service (can be overridden) |
| `timezone` | str | `UTC` | IANA timezone for cron schedules and timestamps in file names and logs |
| `log_level` | str | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `language` | str | `ru` | Language for logs and Telegram messages (`ru` / `en`) |

### Service (`services:` — array, one element per service)

| Field | Type | Required | Description |
|:----:|:----:|:----:|:---|
| `name` | str | yes | Unique name (a-z, 0-9, `_`, `-`). Used as the subdirectory name and archive prefix |
| `enabled` | bool | no | `true` by default. `false` = skip when loading the schedule |
| `schedule` | cron | yes | Cron expression in APScheduler format (`min hour day month dow`) |
| `paths` | list of paths | no | Files/directories to back up (packed into a single tar inside the archive) |
| `paths_exclude` | list of glob | no | Glob patterns (with `**` support) to exclude from `paths`. Patterns are matched **relative** to each root in `paths`. Examples: `**/.git`, `**/node_modules`, `**/__pycache__`, `**/backups`, `**/*.log` |
| `databases` | list | no | Databases (see below) |
| `local_retention` | int | no | Overrides `global.local_retention` |
| `telegram` | object | no | Telegram delivery (see below) |

### Databases

UniGrandBackup supports **PostgreSQL**, **MySQL/MariaDB**, and **SQLite**. Versions and tooling matrix:

| Engine | Supported versions | Backup tool | Restore tool | Archive format |
|:--|:--|:--|:--|:--|
| **PostgreSQL** | 15, 16, 17, 18 (any, with auto-detect) | `pg_dump -Fc` (custom) | `pg_restore --clean --if-exists --no-owner --no-acl` | `.dump` (binary) |
| **PostgreSQL plain** | 15, 16, 17, 18 | `pg_dump -Fp` | `psql -v ON_ERROR_STOP=1 -f` | `.sql` (plain SQL) |
| **MySQL** | 5.7, 8.0, 8.4 | `mysqldump --single-transaction --routines --triggers --events` | `mysql < gunzip` | `.sql.gz` |
| **MariaDB** | 10.5+, 10.6, 10.11, 11.x | `mysqldump --single-transaction ...` (via mariadb-client) | `mysql < gunzip` | `.sql.gz` |
| **SQLite** | 3.x | `sqlite3 .dump` | `sqlite3 < gunzip` | `.sql.gz` |

**PostgreSQL:**

```yaml
- kind: postgres
  host: myapp-db            # docker container name or host
  port: 5432
  user: myapp_user
  password_env: MYAPP_DB_PASSWORD     # env-var name from .env
  database: myapp
  format: custom            # 'custom' (recommended) or 'plain'
  client_version: auto      # auto (default) | 15 | 16 | 17 | 18
                            # auto: detects server version via SHOW server_version_num
                            #       and invokes the matching pg_dump from the image
```

All four pg-client versions (15/16/17/18) are installed in the image via apt.postgresql.org. The version actually used is recorded in `manifest.json` (`client_version_used`) so restore can pick a compatible `pg_restore`.

**MySQL / MariaDB:**

```yaml
- kind: mysql               # 'mysql' or 'mariadb' — one client (mariadb-client)
  host: webapp-db
  port: 3306
  user: webapp
  password_env: WEBAPP_DB_PASSWORD
  database: webapp
```

Uses `mariadb-client`, which is wire-protocol-compatible with MySQL 5.7+, 8.x, 9.x and MariaDB 10.x/11.x. Dump runs with `--single-transaction --routines --triggers --events`, and `mysqldump`'s stdout is piped straight into gzip (no in-memory buffering).

**SQLite:**

```yaml
- kind: sqlite
  path: /opt/myapp/data/app.db    # path must be accessible inside the container
```

### Telegram

```yaml
telegram:
  bot_token_env: BACKUP_BOT_TOKEN   # env-var name carrying the @BotFather token
  chat_id: -1001234567890           # chat/group ID (for a topic — the supergroup ID)
  thread_id: 42                     # topic ID (optional, for forum chats)
  send_last_only: true              # send only the freshest archive (not all)
  send_summary: true                # if document upload fails — send a text alert instead
```

### Environment variables (`.env`)

```ini
BACKUP_BOT_TOKEN=123456789:AAH...    # Telegram bot token from @BotFather
MYAPP_DB_PASSWORD=...                # Postgres password for myapp
```

⚠️ `.env` **must** be in `.gitignore` with `chmod 600`. Variable **names** go into `config.yaml` as `*_env: NAME`; their **values** live only in `.env`.

---

## 🐳 Docker networks

For UniGrandBackup to reach the Postgres containers of other services, its container must be attached to the same docker networks. In `docker-compose.yml` reference each required network as `external: true`:

```yaml
networks:
  myapp_network:
    external: true
```

The names must match exactly what `docker network ls` shows.

---

## 🚀 Usage

```bash
# Start (daemon mode, on schedule)
sudo docker compose up -d

# Tail logs
sudo docker compose logs -ft

# Stop
sudo docker compose down

# Pull a new image version and restart
sudo docker compose pull && sudo docker compose up -d && sudo docker compose logs -f -t

# One-off backup of a single service (off-schedule, for verification)
sudo docker compose exec unigrandbackup python -m app.main run myapp

# Print the list of loaded services
sudo docker compose exec unigrandbackup python -m app.main list
```

---

## 📁 Artifact layout

Each scheduled run produces **one** archive per service:

```
/var/backups/unigrandbackup/
├── myapp/
│   ├── myapp-20260520-030000.tar.gz       # today
│   ├── myapp-20260519-030000.tar.gz
│   └── ...                                # N=local_retention copies kept
└── filestore/
    ├── filestore-20260520-033000.tar.gz
    └── ...
```

Inside a `<service>-<YYYYMMDD-HHMMSS>.tar.gz`:

```
myapp-20260520-030000/
├── manifest.json              # backup metadata (format, service, contents)
├── files/
│   ├── .env
│   └── data/...
└── databases/
    └── myapp.dump
```

`manifest.json` — describes contents, required by `app.main restore`.
`databases/*.dump` — `pg_dump -Fc` (restore via `pg_restore`).
`databases/*.sql.gz` — gzipped `sqlite3 .dump` or `mysqldump` (restore via `gunzip | sqlite3 newdb.sqlite` or `mysql`).

---

## 💬 Sample Telegram message

```
🗄 UniGrandBackup
━━━━━━━━━━━━━━━━━━━━
📦 Service: myapp
✅ Status:  OK
🕐 Time:    2026-05-20 03:00:01 UTC
⏱ Took:    12.4 s
📊 Size:    12.4 MB

📥 Contents:
   • 📁 Files: 2 paths
   • 🐘 PostgreSQL: myapp
```

The `myapp-20260520-030000.tar.gz` file itself arrives as a `document` in the same topic.

---

## 💡 Updating

```bash
cd /opt/unigrandbackup
sudo docker compose down
sudo docker compose pull
sudo docker compose up -d && sudo docker compose logs -f -t
```

> Before updating it's a good idea to diff your `config.yaml` against the repo's example (`examples/config.example.yaml`) — new fields get added there.

---

## 🔄 Restore

UniGrandBackup can **restore an archive on its own**: it unpacks files, optionally brings up docker compose, and loads the DB dump. A dedicated compose profile `restore` mounts `/opt` as RW and exposes `docker.sock`, leaving the daemon (which runs with `/opt:ro`) untouched.

### Automatic restore

```bash
cd /opt/unigrandbackup

# 1. Put the archive into the local backup directory (or pass a custom path)
sudo cp /path/to/myapp-20260520-030000.tar.gz \
        /var/backups/unigrandbackup/myapp/

# 2. Run restore (one-shot container with RW /opt + docker.sock)
sudo docker compose --profile restore run --rm unigrandbackup-restore \
        /var/backups/unigrandbackup/myapp/myapp-20260520-030000.tar.gz \
        --force
```

`restore` flags:

| Flag | Description |
|:---:|:---|
| `--force` | Overwrite existing files and DB contents without confirmation. **Required** if anything already exists at the destination paths. |
| `--no-compose` | Don't run `docker compose up -d` even if the archive contains a `docker-compose.yml`. Handy when the containers are already running. |
| `--skip-db` | Restore files + compose only; **skip** the DB dump replay. Useful when you want to deal with the app first and the DB separately. |
| `--db-only` | Restore **only** the DB dumps; skip files and compose-up. Useful when files are already on the host and you only need to refresh the DB. |
| `--remap-owner UID:GID` | Override file ownership during restore (default: preserve uid/gid recorded in the manifest). Example: `--remap-owner 1000:1000`. |
| `--dry-run` | Print the restore plan (which files, which DBs, where to compose) — **without applying anything**. Handy before running against prod. |

Workflow:

1. Extract the archive into a temp directory.
2. Read `manifest.json` — contains schema `unigrandbackup-1`, service name, timestamp, contents description, **uid/gid/mode** for every path.
3. Restore files to their **original absolute paths** on the host, preserving `uid`/`gid`/`mode` from the manifest (when running as root, which is the default inside a docker container).
4. Find `docker-compose.yml` among the restored files and run `docker compose up -d` (disable via `--no-compose`). docker compose output is streamed into our logs (build/pull progress visible in real time).
5. **Auto-attach to the DB container's docker network** — restore connects itself to the freshly-created DB networks so `pg_isready -h <container_name>` can resolve.
6. Wait for the DB via `pg_isready` (Postgres) or `mysqladmin ping` (MySQL/MariaDB).
7. Load the dump:
   - **Postgres custom-format** → `pg_restore --clean --if-exists --no-owner --no-acl`
   - **Postgres plain** → `psql -v ON_ERROR_STOP=1 -f`
   - **MySQL / MariaDB** → `mysql < gunzip(dump.sql.gz)`
   - **SQLite** → the existing file is renamed to `*.bak.<timestamp>`, the dump is replayed via `sqlite3`

> 💡 For automatic compose-up to work, add the `docker-compose.yml` (or the whole service root) to the service's `paths`.

### 🛠 Troubleshooting

**1. `permission denied` / `EACCES` when the app starts after restore**

A rare-but-real case: a bind-mounted directory (e.g. `./data` or `./logs`) was created by docker as `root:root`, but the app inside the container runs as uid 1000 (`app`, `node`). We do record and restore uid/gid in the manifest, but if the mapping differs on the new host — use `--remap-owner`:

```bash
sudo docker compose --profile restore run --rm unigrandbackup-restore \
        /var/backups/myapp/myapp-20260520-030000.tar.gz \
        --force --remap-owner 1000:1000
```

Or after restore, by hand: `sudo chown -R 1000:1000 /opt/myapp/data /opt/myapp/logs`.

**2. `pg_restore: error: unsupported version (1.16) in file header`**

This means the dump was produced by a newer pg_dump than the pg_restore you're trying to load it with. UniGrandBackup ships pg-clients 15/16/17/18 and uses the one matching your server version. If you're invoking `pg_restore` **outside** our container on a system with an older client — it'll fail.

Options:
- Use our restore (`docker compose --profile restore run ...`) — it picks the right client based on `client_version_used` in the manifest.
- Or manually: `docker run --rm --network <db_net> -e PGPASSWORD=... -v /dump:/dump:ro postgres:17-alpine pg_restore ...` (postgres:17 reads format 1.16).

**3. `pg_isready` times out (`no response`)**

If restore reaches compose-up on a fresh host but then hangs on `pg_isready` for 180 seconds and dies — the `restore_network_attached` log line should be there showing we joined the DB network. If it isn't, check:
- Is `docker.sock` mounted into the restore container (see `docker-compose.yml`)?
- Does docker CLI work inside the container: `docker ps` from the restore container should return a list.

**4. Backup too big for Telegram (>50 MB)**

Telegram bots refuse files >50 MB. Options:
- Tighten `paths_exclude` (especially `**/.git`, `**/node_modules`, `**/pgdata` for postgres bind-mounts).
- The local copy in `/var/backups/<service>/` is kept regardless — Telegram delivery is optional.

### Manual restore (pulling individual pieces)

**Unpack the archive:**
```bash
tar -xzf myapp-20260520-030000.tar.gz      # extracts to myapp-20260520-030000/
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

## 🛠 Development

```bash
git clone -b develop https://github.com/grandvan709/UniGrandBackup
cd UniGrandBackup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && cp examples/config.example.yaml config.yaml
python -m app.main list
python -m app.main run <service>
```

Releases — git tags `X.Y.Z`. GitHub Actions automatically builds the Docker image and pushes `grandvan/unigrandbackup:X.Y.Z` + `:latest`.

---

<p align=center>
    If the project is useful to you — leave a ⭐!<br>
    <br>
    USDT TRC20: <code>TL6gHETnKqNWV4D6GjiKKahkBsAwcyWfo8</code>
</p>

<p align=center>
    <a href="https://t.me/grand_van" target="_blank" rel="noopener noreferrer">
        <img src="https://img.shields.io/badge/Telegram-GrandVan-purple?logo=telegram&logoColor=white&labelColor=blue" alt="Chat me on Telegram">
    </a>
</p>
