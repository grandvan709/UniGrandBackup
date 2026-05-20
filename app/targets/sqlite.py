"""SQLite database backup via sqlite3 .dump."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path
from typing import TypedDict

import structlog

from ..config import SQLiteDB
from ..utils import run_subprocess

log = structlog.get_logger(__name__)


class SqliteDumpEntry(TypedDict):
    kind: str           # "sqlite"
    source_path: str    # original DB path on host
    archive_path: str   # path inside archive (e.g. "databases/app.sql.gz")


def dump_sqlite(db: SQLiteDB, staging_dir: Path) -> SqliteDumpEntry:
    """Run `sqlite3 <path> .dump` and gzip the output.

    Result: staging_dir/databases/<db-basename>.sql.gz
    """
    if not db.path.exists():
        raise FileNotFoundError(f"SQLite file not found: {db.path}")

    db_dir = staging_dir / "databases"
    db_dir.mkdir(parents=True, exist_ok=True)

    base = db.path.stem  # bot.db → "bot"
    sql_path = db_dir / f"{base}.sql"
    gz_path = db_dir / f"{base}.sql.gz"

    log.info("sqlite_dump_start", path=str(db.path), dest=str(gz_path))

    result = run_subprocess(
        ["sqlite3", str(db.path), ".dump"],
        timeout=1800,
    )

    if result.returncode != 0:
        log.error(
            "sqlite_dump_failed",
            path=str(db.path),
            stderr=(result.stderr or "")[:500],
        )
        raise RuntimeError(
            f"sqlite3 .dump failed for {db.path}: "
            f"{(result.stderr or '').strip()[:300]}"
        )

    sql_path.write_text(result.stdout, encoding="utf-8")
    with sql_path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    sql_path.unlink()

    size = gz_path.stat().st_size
    log.info("sqlite_dump_done", path=str(db.path), size_bytes=size, dest=str(gz_path))
    return {
        "kind": "sqlite",
        "source_path": str(db.path),
        "archive_path": f"databases/{gz_path.name}",
    }
