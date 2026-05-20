"""Postgres database backup via pg_dump."""

from __future__ import annotations

from pathlib import Path

import structlog

from ..config import PostgresDB
from ..utils import run_subprocess

log = structlog.get_logger(__name__)


def dump_postgres(db: PostgresDB, staging_dir: Path) -> Path:
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
    return dest
