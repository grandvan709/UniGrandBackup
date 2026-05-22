"""MySQL / MariaDB backup via mysqldump → gzip.

A single client (`mariadb-client` package) covers both MySQL 5.7+/8.x/9.x
and MariaDB 10.x/11.x — the wire protocol is compatible. We stream
mysqldump's stdout straight into gzip to keep memory low for large
schemas.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict

import structlog

from ..config import MySQLDB

log = structlog.get_logger(__name__)


class MySQLDumpEntry(TypedDict):
    kind: str           # "mysql" | "mariadb"
    host: str
    port: int
    user: str
    database: str
    password_env: str
    archive_path: str   # "databases/<db>.sql.gz"


def dump_mysql(db: MySQLDB, staging_dir: Path) -> MySQLDumpEntry:
    """mysqldump → staging_dir/databases/<db>.sql.gz (compressed inline)."""
    db_dir = staging_dir / "databases"
    db_dir.mkdir(parents=True, exist_ok=True)

    gz_path = db_dir / f"{db.database}.sql.gz"

    cmd = [
        "mysqldump",
        f"--host={db.host}",
        f"--port={db.port}",
        f"--user={db.user}",
        # Consistency without table-level locks (InnoDB friendly):
        "--single-transaction",
        # Include stored routines, triggers, scheduled events:
        "--routines",
        "--triggers",
        "--events",
        # Skip database-creation statement; restore targets an existing DB:
        "--no-create-db",
        db.database,
    ]

    # MYSQL_PWD avoids leaking password on command line (visible in ps).
    sub_env = {**os.environ, "MYSQL_PWD": db.password()}

    log.info(
        "mysql_dump_start",
        host=db.host, port=db.port, database=db.database, kind=db.kind,
    )

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=sub_env,
    )

    try:
        assert proc.stdout is not None
        with gzip.open(gz_path, "wb", compresslevel=6) as fh:
            shutil.copyfileobj(proc.stdout, fh)
        proc.wait(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        gz_path.unlink(missing_ok=True)
        raise RuntimeError(f"mysqldump timed out for {db.database}") from None

    stderr_bytes = proc.stderr.read() if proc.stderr else b""
    stderr_text = stderr_bytes.decode("utf-8", "replace")

    if proc.returncode != 0:
        gz_path.unlink(missing_ok=True)
        log.error(
            "mysql_dump_failed",
            host=db.host, database=db.database,
            stderr=stderr_text[:500],
        )
        raise RuntimeError(
            f"mysqldump failed for {db.database}@{db.host}: "
            f"{stderr_text.strip()[:300]}"
        )

    size = gz_path.stat().st_size
    log.info(
        "mysql_dump_done",
        host=db.host, database=db.database, size_bytes=size,
    )
    return {
        "kind": db.kind,
        "host": db.host,
        "port": db.port,
        "user": db.user,
        "database": db.database,
        "password_env": db.password_env,
        "archive_path": f"databases/{gz_path.name}",
    }
