"""Restore a backup archive — files + databases.

Flow:
  1. Extract <archive>.tar.gz into a temp directory.
  2. Read manifest.json (format unigrandbackup-1).
  3. Restore each `files/*` entry back to its original absolute path on host.
     If the destination exists, refuse unless --force was passed.
  4. If the archive contains docker-compose.yml (somewhere under restored
     paths) and --no-compose was NOT passed, run `docker compose up -d`
     in that directory. Requires docker CLI + /var/run/docker.sock mount.
  5. For each database in manifest:
       - postgres: pg_isready wait → pg_restore (custom) or psql (plain)
       - sqlite:   move existing file aside → gunzip | sqlite3 newdb
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

import structlog

from .config import Config
from .utils import run_subprocess

log = structlog.get_logger(__name__)


COMPOSE_FILENAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def restore_archive(
    config: Config,
    archive: Path,
    *,
    force: bool = False,
    run_compose: bool = True,
) -> None:
    """Restore a UniGrandBackup archive. See module docstring."""
    log.info("restore_start", archive=str(archive))

    extract_root = Path(tempfile.mkdtemp(prefix="ugb-restore-"))
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(extract_root, filter="data")

        # Archive has a single top-level dir: <service>-<stamp>/
        children = [p for p in extract_root.iterdir() if p.is_dir()]
        if len(children) != 1:
            raise RuntimeError(
                f"Unexpected archive layout — expected 1 top-level dir, got {len(children)}"
            )
        archive_root = children[0]

        manifest_path = archive_root / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(
                f"manifest.json not found in archive — is this an UniGrandBackup archive?"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        service = manifest.get("service", "?")
        log.info(
            "restore_manifest_loaded",
            service=service,
            created_at=manifest.get("created_at", "?"),
        )

        # --- 1. Files ---
        restored_sources: list[Path] = []
        files_entries: list[dict] = manifest.get("contents", {}).get("files", []) or []
        if files_entries:
            log.info("restore_files_start")
            for entry in files_entries:
                src = archive_root / entry["archive_path"]
                dest = Path(entry["source"])
                if not src.exists():
                    log.warning("restore_entry_missing", archive_path=entry["archive_path"])
                    continue
                _restore_one_path(src, dest, force=force)
                restored_sources.append(dest)

        # --- 2. docker compose up (if compose file restored) ---
        compose_dir: Path | None = None
        if run_compose:
            compose_dir = _find_compose_dir(restored_sources)
            if compose_dir is None:
                log.info("restore_compose_skipped")
            else:
                log.info("restore_compose_up", dir=str(compose_dir))
                _docker_compose_up(compose_dir)
                log.info("restore_compose_done")

        # --- 3. Databases ---
        db_entries: list[dict] = manifest.get("contents", {}).get("databases", []) or []
        for db in db_entries:
            kind = db.get("kind")
            try:
                if kind == "postgres":
                    _restore_postgres(db, archive_root, force=force)
                elif kind == "sqlite":
                    _restore_sqlite(db, archive_root, force=force)
                else:
                    log.warning("restore_db_unknown_kind", kind=kind)
            except Exception as e:
                name = db.get("database") or db.get("source_path") or "?"
                log.error("restore_db_failed", database=name, error=str(e))
                raise

        log.info("restore_done", service=service)

    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


# ─── Files ────────────────────────────────────────────────────────────────────

def _restore_one_path(src: Path, dest: Path, *, force: bool) -> None:
    """Copy src (file or directory from extracted archive) onto dest (host)."""
    if dest.exists():
        if not force:
            log.warning("restore_file_skipped", dest=str(dest))
            raise RuntimeError(
                f"Destination already exists: {dest}. "
                "Use --force to overwrite, or remove it manually first."
            )
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()

    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, symlinks=True)
    else:
        shutil.copy2(src, dest, follow_symlinks=False)
    log.info("restore_file_done", dest=str(dest))


# ─── docker compose ───────────────────────────────────────────────────────────

def _find_compose_dir(restored_sources: list[Path]) -> Path | None:
    """Return the deepest dir among restored sources that contains a compose file."""
    candidates: set[Path] = set()
    for src in restored_sources:
        if src.is_dir():
            candidates.add(src)
        candidates.add(src.parent)
        # also include grandparent — backups sometimes restore just .env into /opt/app/
        candidates.add(src.parent.parent)

    found: list[Path] = []
    for d in candidates:
        if not d.is_dir():
            continue
        for fname in COMPOSE_FILENAMES:
            if (d / fname).is_file():
                found.append(d)
                break

    if not found:
        return None
    # deepest match wins (most specific)
    return max(found, key=lambda p: len(p.parts))


def _docker_compose_up(compose_dir: Path) -> None:
    """Run `docker compose up -d` inside compose_dir. Requires docker.sock + docker CLI."""
    result = run_subprocess(
        ["docker", "compose", "up", "-d"],
        cwd=compose_dir,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker compose up failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()[:500]}"
        )


# ─── Postgres restore ─────────────────────────────────────────────────────────

def _pg_isready(host: str, port: int, user: str, database: str, timeout: int = 120) -> None:
    """Block until pg_isready succeeds. Raises after timeout."""
    log.info("restore_db_wait", host=host, port=port, database=database)
    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        result = run_subprocess(
            ["pg_isready", "-h", host, "-p", str(port), "-U", user, "-d", database],
            timeout=10,
        )
        if result.returncode == 0:
            log.info("restore_db_ready", database=database)
            return
        last_err = (result.stderr or result.stdout or "").strip()
        time.sleep(2)
    raise RuntimeError(
        f"Timed out waiting for postgres {host}:{port}/{database} ({timeout}s). "
        f"Last error: {last_err}"
    )


def _restore_postgres(db: dict, archive_root: Path, *, force: bool) -> None:
    """pg_restore the dump back into the database described in the manifest."""
    host = db["host"]
    port = int(db.get("port", 5432))
    user = db["user"]
    database = db["database"]
    fmt = db.get("format", "custom")
    password_env = db.get("password_env", "")
    dump_path = archive_root / db["archive_path"]
    if not dump_path.is_file():
        raise RuntimeError(f"DB dump not found in archive: {db['archive_path']}")

    password = os.environ.get(password_env, "") if password_env else ""
    if not password:
        raise RuntimeError(
            f"Postgres password env '{password_env}' is empty or unset. "
            "Set it in .env so restore can authenticate."
        )

    _pg_isready(host, port, user, database, timeout=180)

    sub_env = {"PGPASSWORD": password}

    if fmt == "custom":
        # pg_restore --clean --if-exists works even if the DB already has data.
        # Without --force we still require it for safety.
        if not force:
            raise RuntimeError(
                f"Restore will overwrite contents of database '{database}'. "
                "Pass --force to proceed."
            )
        cmd = [
            "pg_restore",
            "-h", host,
            "-p", str(port),
            "-U", user,
            "-d", database,
            "--clean", "--if-exists",
            "--no-owner", "--no-acl",
            str(dump_path),
        ]
    else:  # plain SQL
        if not force:
            raise RuntimeError(
                f"Restore will run plain-SQL dump against '{database}'. "
                "Pass --force to proceed."
            )
        cmd = [
            "psql",
            "-h", host,
            "-p", str(port),
            "-U", user,
            "-d", database,
            "-v", "ON_ERROR_STOP=1",
            "-f", str(dump_path),
        ]

    result = run_subprocess(cmd, env=sub_env, timeout=3600)
    if result.returncode != 0:
        # pg_restore prints lots of harmless "errors ignored on restore" — log
        # the full body so the user can decide if it actually failed.
        raise RuntimeError(
            f"pg_restore/psql failed (rc={result.returncode}) for {database}: "
            f"{(result.stderr or '').strip()[:1000]}"
        )
    log.info("restore_db_done", database=database)


# ─── SQLite restore ───────────────────────────────────────────────────────────

def _restore_sqlite(db: dict, archive_root: Path, *, force: bool) -> None:
    """Restore SQLite by running gunzip | sqlite3 onto the original path."""
    source_path = Path(db["source_path"])
    archive_dump = archive_root / db["archive_path"]
    if not archive_dump.is_file():
        raise RuntimeError(f"SQLite dump not found in archive: {db['archive_path']}")

    if source_path.exists():
        if not force:
            raise RuntimeError(
                f"SQLite file already exists at {source_path}. Pass --force to overwrite."
            )
        # Move aside as .bak.<timestamp> just in case.
        backup = source_path.with_suffix(source_path.suffix + f".bak.{int(time.time())}")
        source_path.rename(backup)
        log.info("restore_sqlite_existing_moved", original=str(source_path), backup=str(backup))

    source_path.parent.mkdir(parents=True, exist_ok=True)
    # Pipe: `gunzip -c <archive_dump> | sqlite3 <source_path>`
    sqlite_proc = subprocess.Popen(
        ["sqlite3", str(source_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    with gzip.open(archive_dump, "rt", encoding="utf-8") as fh:
        stdout, stderr = sqlite_proc.communicate(input=fh.read(), timeout=1800)
    if sqlite_proc.returncode != 0:
        raise RuntimeError(
            f"sqlite3 restore failed (rc={sqlite_proc.returncode}): "
            f"{(stderr or stdout or '').strip()[:500]}"
        )
    log.info("restore_db_done", database=str(source_path))
