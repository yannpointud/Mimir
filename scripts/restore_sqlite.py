#!/usr/bin/env python
"""Restore a SQLite backup and PROVE it is usable (OPS-03 done criterion).

A backup that has never been restored and verified is not proven to work. This
script restores a backup file via the Online Backup API and asserts two things:

1. ``PRAGMA integrity_check`` returns ``"ok"`` on the restored database.
2. Per-table row counts on the restored database match the source database.

It exits ``0`` only when both hold, ``1`` otherwise, so it can gate a scheduled
backup run or a disaster-recovery drill.
"""
import sqlite3
import sys
from pathlib import Path


def _assert_within_data_tree(path: Path) -> None:
    """Defense-in-depth path-traversal guard for an operator-invoked script.

    Each supplied path must resolve inside a ``data`` directory. This refuses
    obviously out-of-tree arguments; it does not replace filesystem perms.
    """
    if "data" not in path.parts:
        raise ValueError(
            f"Refusing to operate on path outside a data/ tree: {path}"
        )


def restore_and_verify(backup_path, source_path, restore_target) -> bool:
    """Restore ``backup_path`` and prove it against ``source_path``.

    Args:
        backup_path: Backup file produced by backup_sqlite.py.
        source_path: The live/source DB to compare row counts against.
        restore_target: Where the backup is materialized (fresh file).

    Returns:
        True if integrity_check is "ok" and every user table's row count
        matches the source; False otherwise (with a FAIL line printed).
    """
    backup_path = Path(backup_path).resolve()
    source_path = Path(source_path).resolve()
    restore_target = Path(restore_target).resolve()

    _assert_within_data_tree(backup_path)
    _assert_within_data_tree(source_path)
    _assert_within_data_tree(restore_target)

    # Refuse to materialize the restore over the live/source DB or over the
    # backup itself. Without this guard a DR-drill typo (restore_target ==
    # source_path) would clobber the live database with a possibly-older backup
    # AND make the row-count check compare the source against itself, so it
    # would always "pass" -- silent data loss plus a lie. The restore must land
    # in a FRESH, distinct file.
    if restore_target == source_path:
        raise ValueError(
            f"Refusing to restore onto the source database: {restore_target}. "
            "Choose a fresh, distinct restore target."
        )
    if restore_target == backup_path:
        raise ValueError(
            f"Refusing to restore onto the backup file itself: {restore_target}. "
            "Choose a fresh, distinct restore target."
        )

    # Restore: open the backup read-only and copy it into a fresh target via
    # the Online Backup API (mirrors backup_sqlite.py connection conventions).
    backup_conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    restore_conn = sqlite3.connect(str(restore_target))
    try:
        backup_conn.backup(restore_conn)
    finally:
        backup_conn.close()

    integrity = restore_conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        print(f"FAIL: integrity_check returned '{integrity}'")
        restore_conn.close()
        return False

    # Enumerate user tables only (exclude SQLite internal sqlite_% tables).
    tables = [r[0] for r in restore_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]

    source_conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    mismatches = []
    try:
        for table in tables:
            restored_count = restore_conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            source_count = source_conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            if restored_count != source_count:
                mismatches.append((table, source_count, restored_count))
    finally:
        source_conn.close()
        restore_conn.close()

    if mismatches:
        print(f"FAIL: row count mismatches (table, source, restored): {mismatches}")
        return False

    print(f"OK: integrity_check=ok, {len(tables)} tables match row counts")
    return True


if __name__ == "__main__":
    backup_arg, source_arg, target_arg = sys.argv[1], sys.argv[2], sys.argv[3]
    ok = restore_and_verify(backup_arg, source_arg, target_arg)
    sys.exit(0 if ok else 1)
