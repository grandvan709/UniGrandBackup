"""Backup targets — collect data from various sources into a staging dir."""

from .files import backup_paths
from .postgres import dump_postgres
from .sqlite import dump_sqlite

__all__ = ["backup_paths", "dump_postgres", "dump_sqlite"]
