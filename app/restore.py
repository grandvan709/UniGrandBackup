"""Restore a backup archive — files + databases.

Flow:
  1. Extract <archive>.tar.gz into a temp directory.
  2. Read manifest.json (format unigrandbackup-1).
  3. Restore each `files/*` entry back to its original absolute path on host,
     preserving uid/gid/mode recorded in the manifest (when running as root).
  4. If the archive contains docker-compose.yml (somewhere under restored
     paths) and --no-compose was NOT passed, stream `docker compose up -d`
     output to our log. Requires docker CLI + /var/run/docker.sock mount.
  5. For each database in manifest:
       - Auto-attach our container to the DB container's docker networks so
         `pg_isready -h <container_name>` / mysqladmin ping resolves.
       - postgres: pg_isready wait → pg_restore (custom) or psql (plain)
       - mysql/mariadb: mysqladmin ping → mysql < gunzip(dump.sql.gz)
       - sqlite:   move existing file aside → gunzip | sqlite3 newdb

Flags:
  --force         : overwrite existing files/DB without confirmation
  --no-compose    : don't auto-run `docker compose up`
  --skip-db       : restore files + compose only, skip DB dumps
  --db-only       : restore DB dumps only, skip files and compose
  --remap-owner U:G : override ownership during file restore
  --dry-run       : print planned actions, don't apply
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import structlog

from .config import Config
from .targets.postgres import _pg_binary, _pg_version_installed, KNOWN_PG_MAJORS
from .utils import run_subprocess

log = structlog.get_logger(__name__)


COMPOSE_FILENAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def restore_archive(
    config: Config,
    archive: Path,
    *,
    force: bool = False,
    run_compose: bool = True,
    skip_db: bool = False,
    db_only: bool = False,
    remap_owner: tuple[int, int] | None = None,
    dry_run: bool = False,
) -> None:
    """Restore a UniGrandBackup archive. See module docstring."""
    if skip_db and db_only:
        raise RuntimeError("--skip-db and --db-only are mutually exclusive")

    log.info("restore_start", archive=str(archive), dry_run=dry_run)

    extract_root = Path(tempfile.mkdtemp(prefix="ugb-restore-"))
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(extract_root, filter="data")

        children = [p for p in extract_root.iterdir() if p.is_dir()]
        if len(children) != 1:
            raise RuntimeError(
                f"Unexpected archive layout — expected 1 top-level dir, got {len(children)}"
            )
        archive_root = children[0]

        manifest_path = archive_root / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(
                "manifest.json not found in archive — is this an UniGrandBackup archive?"
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
        if not db_only and files_entries:
            log.info("restore_files_start")
            for entry in files_entries:
                src = archive_root / entry["archive_path"]
                dest = Path(entry["source"])
                if not src.exists():
                    log.warning("restore_entry_missing", archive_path=entry["archive_path"])
                    continue
                if dry_run:
                    log.info(
                        "dry_run_would_restore_file",
                        dest=str(dest),
                        kind=entry.get("kind", "?"),
                        owner=entry.get("owner", {}),
                        mode=entry.get("mode", "?"),
                    )
                else:
                    _restore_one_path(src, dest, entry, force=force, remap_owner=remap_owner)
                restored_sources.append(dest)

        # --- 2. docker compose up (if compose file restored) ---
        if not db_only and run_compose:
            compose_dir = _find_compose_dir(restored_sources)
            if compose_dir is None:
                log.info("restore_compose_skipped")
            else:
                log.info("restore_compose_up", dir=str(compose_dir))
                if dry_run:
                    log.info("dry_run_would_compose_up", dir=str(compose_dir))
                else:
                    _docker_compose_up(compose_dir)
                    log.info("restore_compose_done")

        # --- 3. Databases ---
        if not skip_db:
            db_entries: list[dict] = manifest.get("contents", {}).get("databases", []) or []
            for db in db_entries:
                kind = db.get("kind")
                if dry_run:
                    log.info(
                        "dry_run_would_restore_db",
                        kind=kind,
                        database=db.get("database") or db.get("source_path"),
                        host=db.get("host"),
                    )
                    continue
                try:
                    if kind == "postgres":
                        _restore_postgres(db, archive_root, force=force)
                    elif kind in ("mysql", "mariadb"):
                        _restore_mysql(db, archive_root, force=force)
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

def _restore_one_path(
    src: Path,
    dest: Path,
    entry: dict,
    *,
    force: bool,
    remap_owner: tuple[int, int] | None,
) -> None:
    """Copy src → dest, then restore ownership + mode recorded in `entry`."""
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

    _apply_owner_and_mode(dest, entry, remap_owner=remap_owner)
    log.info("restore_file_done", dest=str(dest))


def _apply_owner_and_mode(
    dest: Path,
    entry: dict,
    *,
    remap_owner: tuple[int, int] | None,
) -> None:
    """Restore uid/gid + mode for dest tree, using manifest entry as source of truth."""
    owner = entry.get("owner") or {}
    mode_str = entry.get("mode")

    uid: int | None = None
    gid: int | None = None
    if remap_owner is not None:
        uid, gid = remap_owner
    else:
        uid = owner.get("uid") if isinstance(owner.get("uid"), int) else None
        gid = owner.get("gid") if isinstance(owner.get("gid"), int) else None

    can_chown = (uid is not None and gid is not None and os.geteuid() == 0)

    if can_chown:
        try:
            _chown_recursive(dest, uid, gid)
            log.debug("restore_owner_set", dest=str(dest), uid=uid, gid=gid)
        except OSError as e:
            log.warning("restore_chown_failed", dest=str(dest), error=str(e))
    elif uid is not None and os.geteuid() != 0:
        log.debug("restore_chown_skipped_not_root", dest=str(dest))

    if mode_str:
        try:
            os.chmod(dest, int(mode_str, 8))
        except (ValueError, OSError) as e:
            log.warning("restore_chmod_failed", dest=str(dest), error=str(e))


def _chown_recursive(path: Path, uid: int, gid: int) -> None:
    os.lchown(path, uid, gid)
    if path.is_dir() and not path.is_symlink():
        for child in path.rglob("*"):
            try:
                os.lchown(child, uid, gid)
            except OSError as e:
                log.warning("restore_chown_failed", path=str(child), error=str(e))


# ─── docker compose ───────────────────────────────────────────────────────────

def _find_compose_dir(restored_sources: list[Path]) -> Path | None:
    candidates: set[Path] = set()
    for src in restored_sources:
        if src.is_dir():
            candidates.add(src)
        candidates.add(src.parent)
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
    return max(found, key=lambda p: len(p.parts))


def _docker_compose_up(compose_dir: Path, timeout: int = 900) -> None:
    """Stream `docker compose up -d` output to our log."""
    # We intentionally don't pass `--progress plain`. That flag is top-level
    # (must come BEFORE `up`), and docker compose auto-selects plain output
    # anyway when stdout is a pipe (which it is — we capture via Popen).
    proc = subprocess.Popen(
        ["docker", "compose", "up", "-d"],
        cwd=str(compose_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_lines: list[str] = []

    def reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                output_lines.append(line)
                log.debug("compose_output", line=line)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"docker compose up timed out after {timeout}s")
    t.join(timeout=5)

    if proc.returncode != 0:
        tail = "\n".join(output_lines[-100:])
        raise RuntimeError(
            f"docker compose up failed (rc={proc.returncode}).\n"
            f"Last 100 lines of output:\n{tail}"
        )


# ─── Docker network discovery / auto-attach ──────────────────────────────────

def _self_container_id() -> str:
    try:
        with open("/etc/hostname") as f:
            return f.read().strip()
    except OSError as e:
        raise RuntimeError(f"Could not read /etc/hostname: {e}") from e


def _container_networks(name_or_id: str) -> list[str]:
    result = run_subprocess(
        ["docker", "inspect", name_or_id, "-f", "{{json .NetworkSettings.Networks}}"],
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker inspect {name_or_id} failed: {(result.stderr or '').strip()[:300]}"
        )
    try:
        networks_obj = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Bad JSON from docker inspect: {e}") from e
    return list(networks_obj.keys()) if isinstance(networks_obj, dict) else []


def _attach_self_to_container_networks(target_container: str) -> list[str]:
    """Attach our own container to all networks of target_container."""
    try:
        self_id = _self_container_id()
        target_nets = _container_networks(target_container)
        own_nets = set(_container_networks(self_id))
    except RuntimeError as e:
        log.warning("restore_network_inspect_failed", target=target_container, error=str(e))
        return []

    attached: list[str] = []
    for net in target_nets:
        if net in own_nets:
            continue
        result = run_subprocess(
            ["docker", "network", "connect", net, self_id],
            timeout=30,
        )
        if result.returncode == 0:
            attached.append(net)
            log.info("restore_network_attached", network=net, target=target_container)
        else:
            log.warning(
                "restore_network_attach_failed",
                network=net,
                error=(result.stderr or "").strip()[:300],
            )
    return attached


# ─── Postgres restore ─────────────────────────────────────────────────────────

def _resolve_pg_restore_major(manifest_db: dict) -> str | None:
    """Pick pg-client major for restore.

    Prefer the version recorded in the manifest (`client_version_used`).
    If not installed in this image (rare — image was downgraded), fall back
    to the closest >= version we have. As a last resort, default PATH.
    """
    pinned = manifest_db.get("client_version_used")
    if pinned and _pg_version_installed(pinned):
        return pinned
    if pinned:
        # Pick the smallest installed major >= pinned, else the newest.
        ge = sorted(
            (v for v in KNOWN_PG_MAJORS if _pg_version_installed(v) and int(v) >= int(pinned)),
            key=int,
        )
        if ge:
            log.info("restore_pg_client_fallback", wanted=pinned, using=ge[0])
            return ge[0]
        newest = max(
            (v for v in KNOWN_PG_MAJORS if _pg_version_installed(v)),
            key=int,
            default=None,
        )
        if newest:
            log.warning(
                "restore_pg_client_downgrade",
                wanted=pinned, using=newest,
                note="restore may fail if dump format is newer than client",
            )
            return newest
    return None  # PATH default (latest via pg_wrapper)


def _pg_isready(host: str, port: int, user: str, database: str, *, binary: str, timeout: int = 120) -> None:
    log.info("restore_db_wait", host=host, port=port, database=database)
    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        result = run_subprocess(
            [binary, "-h", host, "-p", str(port), "-U", user, "-d", database],
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

    # Bridge into the DB container's docker network so DNS resolution works.
    _attach_self_to_container_networks(host)

    client_major = _resolve_pg_restore_major(db)
    pg_isready_bin = _pg_binary("pg_isready", client_major)
    pg_restore_bin = _pg_binary("pg_restore", client_major)
    psql_bin = _pg_binary("psql", client_major)

    _pg_isready(host, port, user, database, binary=pg_isready_bin, timeout=180)

    sub_env = {"PGPASSWORD": password}

    if fmt == "custom":
        if not force:
            raise RuntimeError(
                f"Restore will overwrite contents of database '{database}'. "
                "Pass --force to proceed."
            )
        cmd = [
            pg_restore_bin,
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
            psql_bin,
            "-h", host,
            "-p", str(port),
            "-U", user,
            "-d", database,
            "-v", "ON_ERROR_STOP=1",
            "-f", str(dump_path),
        ]

    result = run_subprocess(cmd, env=sub_env, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(
            f"pg_restore/psql failed (rc={result.returncode}) for {database}: "
            f"{(result.stderr or '').strip()[:1000]}"
        )
    log.info("restore_db_done", database=database)


# ─── MySQL / MariaDB restore ─────────────────────────────────────────────────

def _mysql_isready(
    host: str, port: int, user: str, password: str, *, timeout: int = 180
) -> None:
    """Block until mysqladmin ping succeeds against host:port."""
    log.info("restore_db_wait", host=host, port=port, database="?")
    deadline = time.time() + timeout
    last_err = ""
    sub_env = {**os.environ, "MYSQL_PWD": password}
    while time.time() < deadline:
        result = run_subprocess(
            ["mysqladmin",
             f"--host={host}",
             f"--port={port}",
             f"--user={user}",
             "ping"],
            env={"MYSQL_PWD": password},
            timeout=10,
        )
        if result.returncode == 0:
            log.info("restore_db_ready", database="?")
            return
        last_err = (result.stderr or result.stdout or "").strip()
        time.sleep(2)
    raise RuntimeError(
        f"Timed out waiting for mysql {host}:{port} ({timeout}s). Last error: {last_err}"
    )


def _restore_mysql(db: dict, archive_root: Path, *, force: bool) -> None:
    """Pipe gunzip(dump.sql.gz) → mysql client to restore the database."""
    host = db["host"]
    port = int(db.get("port", 3306))
    user = db["user"]
    database = db["database"]
    password_env = db.get("password_env", "")

    dump_path = archive_root / db["archive_path"]
    if not dump_path.is_file():
        raise RuntimeError(f"MySQL/MariaDB dump not found: {db['archive_path']}")

    password = os.environ.get(password_env, "") if password_env else ""
    if not password:
        raise RuntimeError(
            f"MySQL/MariaDB password env '{password_env}' is empty or unset. "
            "Set it in .env so restore can authenticate."
        )

    if not force:
        raise RuntimeError(
            f"Restore will overwrite contents of database '{database}'. "
            "Pass --force to proceed."
        )

    _attach_self_to_container_networks(host)
    _mysql_isready(host, port, user, password, timeout=180)

    sub_env = {**os.environ, "MYSQL_PWD": password}

    proc = subprocess.Popen(
        ["mysql",
         f"--host={host}",
         f"--port={port}",
         f"--user={user}",
         database],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=sub_env,
    )

    try:
        assert proc.stdin is not None
        with gzip.open(dump_path, "rb") as fh:
            shutil.copyfileobj(fh, proc.stdin)
        proc.stdin.close()
        stdout, stderr = proc.communicate(timeout=3600)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"mysql restore timed out for {database}") from None

    if proc.returncode != 0:
        err = (stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr or "")
        raise RuntimeError(
            f"mysql restore failed (rc={proc.returncode}) for {database}: "
            f"{err.strip()[:500]}"
        )
    log.info("restore_db_done", database=database)


# ─── SQLite restore ───────────────────────────────────────────────────────────

def _restore_sqlite(db: dict, archive_root: Path, *, force: bool) -> None:
    source_path = Path(db["source_path"])
    archive_dump = archive_root / db["archive_path"]
    if not archive_dump.is_file():
        raise RuntimeError(f"SQLite dump not found in archive: {db['archive_path']}")

    if source_path.exists():
        if not force:
            raise RuntimeError(
                f"SQLite file already exists at {source_path}. Pass --force to overwrite."
            )
        backup = source_path.with_suffix(source_path.suffix + f".bak.{int(time.time())}")
        source_path.rename(backup)
        log.info("restore_sqlite_existing_moved", original=str(source_path), backup=str(backup))

    source_path.parent.mkdir(parents=True, exist_ok=True)
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
