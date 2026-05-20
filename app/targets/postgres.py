"""Postgres database backup via pg_dump."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import structlog

from ..config import PostgresDB
from ..utils import run_subprocess

log = structlog.get_logger(__name__)


class PostgresDumpEntry(TypedDict):
    kind: str           # "postgres"
    host: str
    port: int
    user: str
    database: str
    format: str         # "custom" | "plain"
    password_env: str
    archive_path: str   # path inside archive (e.g. "databases/myapp.dump")


def dump_postgres(db: PostgresDB, staging_dir: Path) -> PostgresDumpEntry:
    """Run pg_dump and write the dump into staging_dir/databases/<db>.dump.

    For format=custom — produces compressed binary dump (-Fc), restore via pg_restore.
    For format=plain — produces plain SQL, restore via psql.
    """
    db_dir = staging_dir / "databases"
    db_dir.mkdir(parents=True, exist_ok=True)

    suffix = "dump" if db.format == "custom" else "sql"
    dest = db_dir / f"{db.database}.{suffix}"

    fmt_flag = "-Fc" if db.format == "custom" else "-Fp"
    cmd = [
        "pg_dump",
        "-h", db.host,
        "-p", str(db.port),
        "-U", db.user,
        "-d", db.database,
        fmt_flag,
        "--no-owner",
        "--no-acl",
        "-f", str(dest),
    ]

    log.info(
        "postgres_dump_start",
        host=db.host,
        database=db.database,
        format=db.format,
        dest=str(dest),
    )

    result = run_subprocess(
        cmd,
        env={"PGPASSWORD": db.password()},
        timeout=3600,
    )

    if result.returncode != 0:
        log.error(
            "postgres_dump_failed",
            host=db.host,
            database=db.database,
            stderr=(result.stderr or "")[:500],
        )
        raise RuntimeError(
            f"pg_dump failed for {db.database}@{db.host}: "
            f"{(result.stderr or '').strip()[:300]}"
        )

    size = dest.stat().st_size
    log.info(
        "postgres_dump_done",
        host=db.host,
        database=db.database,
        size_bytes=size,
        dest=str(dest),
    )
    return {
        "kind": "postgres",
        "host": db.host,
        "port": db.port,
        "user": db.user,
        "database": db.database,
        "format": db.format,
        "password_env": db.password_env,
        "archive_path": f"databases/{dest.name}",
    }
