"""Integration tests for the SQLite backup/restore proof.

These tests exercise scripts/backup_sqlite.py and scripts/restore_sqlite.py
end-to-end against a throwaway WAL-mode SQLite database under tmp_path. They
prove:

1. A clean backup then restore yields integrity_check == "ok" AND matching
   per-table row counts (restore_and_verify returns True).
2. A row inserted into the source AFTER the backup is detected as a row-count
   mismatch (restore_and_verify returns False) -- the check is real, not a
   rubber stamp.
3. Rotation keeps exactly sqlite_backup_max_count backups; older ones removed.

The real production database (backend/data/sqlite/mimir.db) is never touched:
everything lives under a data/ subtree of tmp_path.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script(name):
    """Import a scripts/*.py module by file path (they are not a package)."""
    path = _PROJECT_ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup_mod = _load_script("backup_sqlite.py")
restore_mod = _load_script("restore_sqlite.py")


def _make_source_db(db_path: Path, docs_rows: int, users_rows: int) -> None:
    """Create a WAL-mode SQLite DB with two seeded tables."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        conn.executemany(
            "INSERT INTO documents (name) VALUES (?)",
            [(f"doc-{i}",) for i in range(docs_rows)],
        )
        conn.executemany(
            "INSERT INTO users (email) VALUES (?)",
            [(f"user-{i}@example.com",) for i in range(users_rows)],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_clean_backup_restore_verifies_true(tmp_path):
    """A clean backup/restore round-trip: integrity ok + matching row counts."""
    data_dir = tmp_path / "data"
    sqlite_dir = data_dir / "sqlite"
    sqlite_dir.mkdir(parents=True)
    source = sqlite_dir / "mimir.db"
    _make_source_db(source, docs_rows=7, users_rows=3)

    backup_path = backup_mod.backup(
        source_path=source,
        backup_dir=data_dir / "backups",
        max_count=3,
    )
    assert backup_path.exists()
    # Backup files must be 0600 (plaintext copy of user data).
    assert (backup_path.stat().st_mode & 0o777) == 0o600

    restored = data_dir / "restored.db"
    ok = restore_mod.restore_and_verify(backup_path, source, restored)
    assert ok is True


@pytest.mark.integration
def test_row_count_mismatch_detected_returns_false(tmp_path):
    """Inserting into source AFTER backup must be flagged as a mismatch."""
    data_dir = tmp_path / "data"
    sqlite_dir = data_dir / "sqlite"
    sqlite_dir.mkdir(parents=True)
    source = sqlite_dir / "mimir.db"
    _make_source_db(source, docs_rows=5, users_rows=2)

    backup_path = backup_mod.backup(
        source_path=source,
        backup_dir=data_dir / "backups",
        max_count=3,
    )

    # Mutate the source AFTER the backup was taken: the backup no longer
    # matches the source, so verification must fail.
    conn = sqlite3.connect(str(source))
    try:
        conn.execute("INSERT INTO documents (name) VALUES ('post-backup')")
        conn.commit()
    finally:
        conn.close()

    restored = data_dir / "restored.db"
    ok = restore_mod.restore_and_verify(backup_path, source, restored)
    assert ok is False


@pytest.mark.integration
def test_rotation_keeps_only_max_count(tmp_path):
    """Creating more than max_count backups leaves exactly max_count files."""
    data_dir = tmp_path / "data"
    sqlite_dir = data_dir / "sqlite"
    sqlite_dir.mkdir(parents=True)
    source = sqlite_dir / "mimir.db"
    _make_source_db(source, docs_rows=1, users_rows=1)

    backup_dir = data_dir / "backups"
    max_count = 3
    # backup() embeds a second-precision UTC timestamp in the filename, so a
    # tight loop can collide on the same name. After each real backup() call
    # (which exercises the script's own rotation), rename the produced file to
    # a unique, monotonically increasing timestamp so every iteration leaves a
    # distinct file for rotation to prune.
    for i in range(max_count + 2):
        backup_mod.backup(source_path=source, backup_dir=backup_dir, max_count=max_count)
        newest = max(backup_dir.glob("mimir-*.db"), key=lambda p: p.stat().st_mtime)
        unique = backup_dir / f"mimir-2020010{i}T000000Z.db"
        if newest.name != unique.name:
            newest.rename(unique)

    # After more than max_count backups, rotation must leave exactly max_count.
    remaining = sorted(backup_dir.glob("mimir-*.db"))
    assert len(remaining) == max_count
