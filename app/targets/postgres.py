"""PostgreSQL backup via pg_dump (multi-version aware).

Picks pg_dump version matching the server (auto-detection via
`SHOW server_version_num`) unless `client_version` is pinned in config.
Records the version used in the manifest so restore can use a compatible
pg_restore later.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import structlog

from ..config import PG_CLIENT_VERSIONS, PostgresDB
from ..utils import run_subprocess

log = structlog.get_logger(__name__)


# Known major versions that ship in this image, in preference order
# (newest first). Used as fallbacks when auto-detection picks a major
# we don't have installed.
KNOWN_PG_MAJORS: tuple[str, ...] = tuple(v for v in PG_CLIENT_VERSIONS if v != "auto")


class PostgresDumpEntry(TypedDict, total=False):
    kind: str
    host: str
    port: int
    user: str
    database: str
    format: str
    password_env: str
    archive_path: str
    server_version_major: str   # what the server reports — for documentation
    client_version_used: str    # the pg_dump major actually invoked


def _pg_binary(name: str, major: str | None) -> str:
    """Path to pg utility (pg_dump/pg_restore/psql/pg_isready) for a major.

    `None` → use whatever's on PATH (typically the newest installed via
    pg_wrapper). A specific major → use the explicit path bypassing
    pg_wrapper so we always invoke the version we mean.
    """
    if not major:
        return name
    return f"/usr/lib/postgresql/{major}/bin/{name}"


def _pg_version_installed(major: str) -> bool:
    """Whether postgresql-client-<major> is installed in this image."""
    return Path(f"/usr/lib/postgresql/{major}/bin/pg_dump").is_file()


def _newest_installed_major() -> str | None:
    """Largest installed PG major version we have a client for, or None."""
    for major in KNOWN_PG_MAJORS:  # already in newest-first order
        if _pg_version_installed(major):
            return major
    return None


def _detect_server_major(db: PostgresDB) -> str | None:
    """Query `SHOW server_version_num;`, return major as str. None on failure."""
    result = run_subprocess(
        [_pg_binary("psql", None), "-h", db.host, "-p", str(db.port),
         "-U", db.user, "-d", db.database,
         "-tAc", "SHOW server_version_num;"],
        env={"PGPASSWORD": db.password()},
        timeout=15,
    )
    if result.returncode != 0:
        log.warning(
            "postgres_server_version_query_failed",
            host=db.host, database=db.database,
            error=(result.stderr or "").strip()[:200],
        )
        return None
    try:
        server_version_num = int((result.stdout or "").strip())
    except ValueError:
        log.warning("postgres_server_version_parse_failed", raw=result.stdout[:100])
        return None
    return str(server_version_num // 10000)


def _resolve_client_major(db: PostgresDB) -> tuple[str | None, str | None]:
    """Decide which pg-client major version to use.

    Returns (client_major, server_major). Either may be None:
      - client_major None → fall back to PATH default
      - server_major None → couldn't query the server
    """
    server_major = _detect_server_major(db)

    if db.client_version != "auto":
        # User pinned it. Verify we have it installed; otherwise warn + default.
        if _pg_version_installed(db.client_version):
            return db.client_version, server_major
        log.warning(
            "postgres_client_version_not_installed",
            wanted=db.client_version,
            available=", ".join(m for m in KNOWN_PG_MAJORS if _pg_version_installed(m)),
        )
        return None, server_major

    # Auto: prefer exact server match, otherwise newest installed.
    if server_major and _pg_version_installed(server_major):
        return server_major, server_major

    newest = _newest_installed_major()
    if server_major and newest and newest != server_major:
        log.info(
            "postgres_client_version_fallback",
            server=server_major, using=newest,
        )
    return newest, server_major


def dump_postgres(db: PostgresDB, staging_dir: Path) -> PostgresDumpEntry:
    """Run pg_dump and write the dump into staging_dir/databases/<db>.dump.

    Picks the right pg_dump version (auto or pinned via config) so the dump
    format is consistent with the server. The version actually used is
    recorded in the manifest so restore can pick a compatible pg_restore.
    """
    db_dir = staging_dir / "databases"
    db_dir.mkdir(parents=True, exist_ok=True)

    suffix = "dump" if db.format == "custom" else "sql"
    dest = db_dir / f"{db.database}.{suffix}"

    client_major, server_major = _resolve_client_major(db)
    pg_dump = _pg_binary("pg_dump", client_major)

    fmt_flag = "-Fc" if db.format == "custom" else "-Fp"
    cmd = [
        pg_dump,
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
        client_version=client_major or "default",
        server_version=server_major or "?",
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
    )
    entry: PostgresDumpEntry = {
        "kind": "postgres",
        "host": db.host,
        "port": db.port,
        "user": db.user,
        "database": db.database,
        "format": db.format,
        "password_env": db.password_env,
        "archive_path": f"databases/{dest.name}",
    }
    if client_major:
        entry["client_version_used"] = client_major
    if server_major:
        entry["server_version_major"] = server_major
    return entry
