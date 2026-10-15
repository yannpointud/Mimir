#!/usr/bin/env python
"""Scheduled SQLite backup via the Online Backup API.

Intended to be invoked by host cron; safe to run while the app is live
(WAL-mode database, concurrent readers/writers). This script uses
``sqlite3.Connection.backup()`` (the SQLite Online Backup API), which is the
ONLY WAL-safe way to copy a live database: a raw filesystem copy of a WAL
database mid-write would miss uncheckpointed pages and produce an inconsistent
file. Never replace ``.backup()`` with ``shutil.copyfile()`` here.

Backup files are plaintext copies of ALL user data (chat history, document
text). They are written with restrictive ``0o600`` permissions and rotated so
only the newest ``settings.sqlite_backup_max_count`` files are kept.
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Make the backend package importable so we can read operator-configurable
# settings instead of hardcoding paths/rotation depth as script constants.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _PROJECT_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src.config import settings  # noqa: E402


def _resolve_source_path(source_path=None) -> Path:
    """Resolve the source database path from an override or settings."""
    if source_path is not None:
        return Path(source_path).resolve()
    # settings.database_url is a SQLAlchemy URL: sqlite:///./data/sqlite/mimir.db
    db_file = settings.database_url.replace("sqlite:///", "")
    return Path(db_file).resolve()


def _assert_within_data_tree(path: Path) -> None:
    """Defense-in-depth path-traversal guard for an operator-invoked script.

    The resolved path must live inside a ``data`` directory (the project's
    ``data/`` tree or ``backend/data/``). This does not replace filesystem
    permissions; it simply refuses obviously out-of-tree targets supplied by a
    misconfigured cron entry or a crafted argument.
    """
    parts = path.parts
    if "data" not in parts:
        raise ValueError(f"Refusing to operate on path outside a data/ tree: {path}")


def backup(source_path=None, backup_dir=None, max_count=None) -> Path:
    """Create a WAL-safe SQLite backup and rotate old backups.

    Args:
        source_path: Source SQLite DB file. Defaults to the DB derived from
            ``settings.database_url``.
        backup_dir: Destination directory. Defaults to
            ``settings.sqlite_backup_dir``.
        max_count: Number of backups to keep. Defaults to
            ``settings.sqlite_backup_max_count``.

    Returns:
        Path to the newly written backup file.
    """
    source = _resolve_source_path(source_path)
    dest_dir = (
        Path(backup_dir).resolve()
        if backup_dir is not None
        else Path(settings.sqlite_backup_dir).resolve()
    )
    keep = int(max_count) if max_count is not None else int(settings.sqlite_backup_max_count)

    _assert_within_data_tree(source)
    _assert_within_data_tree(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"mimir-{timestamp}.db"

    # Open the source read-only (uri mode=ro) so a concurrent writer is never
    # blocked, and open a fresh destination connection for the backup target.
    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(str(dest))
    try:
        # Online Backup API: single-step full copy (pages=-1 default). WAL-safe.
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    # Restrictive perms: the backup is a plaintext copy of all user data.
    os.chmod(dest, 0o600)

    _rotate(dest_dir, keep)
    return dest


def _rotate(backup_dir: Path, max_count: int) -> None:
    """Keep only the newest ``max_count`` backups; unlink older ones.

    Filenames embed a UTC timestamp (``mimir-<ts>.db``), so lexical sort is
    chronological and the oldest files sort first.
    """
    backups = sorted(backup_dir.glob("mimir-*.db"))
    excess = len(backups) - max_count
    for old in backups[: max(excess, 0)]:
        old.unlink()


if __name__ == "__main__":
    path = backup()
    print(f"Backup written: {path}")
    sys.exit(0)
