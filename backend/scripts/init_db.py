#!/usr/bin/env python3
"""
Script d'initialisation de la base de données
Crée les tables et peut insérer des données de test
"""

import contextlib
import sys
from pathlib import Path

# Ajouter le répertoire backend au PATH
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from src.database.connection import init_database, reset_database, db_manager
from src.database.repository import create_repositories


def main():
    """Point d'entrée principal"""
    import argparse

    parser = argparse.ArgumentParser(description="Initialize Mimir database")
    parser.add_argument(
        "--reset", action="store_true", help="Reset database (WARNING: deletes all data)"
    )
    parser.add_argument("--test-data", action="store_true", help="Insert test data")

    args = parser.parse_args()

    print("Mimir Database Initialization")
    print("=" * 40)

    try:
        if args.reset:
            print("⚠️  WARNING: Resetting database - all data will be lost!")
            confirm = input("Type 'yes' to confirm: ")
            if confirm.lower() != "yes":
                print("Cancelled.")
                return

            reset_database()
            print("✅ Database reset completed")
        else:
            init_database()
            print("✅ Database initialized")

        if args.test_data:
            insert_test_data()
            print("✅ Test data inserted")

        # Vérification finale
        if db_manager.health_check():
            print("✅ Database health check passed")
        else:
            print("❌ Database health check failed")

    except Exception as e:  # noqa: BLE001
        print(f"❌ Error: {e}")
        sys.exit(1)


def insert_test_data():
    """Insère des données de test dans la base"""
    with db_manager.get_session_context() as session:
        repos = create_repositories(session)

        # Configuration de test
        configs = [
            ("app_name", "Mimir Test Instance"),
            ("max_file_size_mb", "100"),
            ("default_chunk_size", "1000"),
            ("enable_debug", "false"),
        ]

        for key, value in configs:
            repos["config"].set(key, value)

        print(f"   - Inserted {len(configs)} configuration entries")

        # Documents de test
        test_docs = [
            (
                "sample1.pdf",
                "a1b2c3d4e5f61234567890123456789012345678901234567890123456789012",
                "/sample/sample1.pdf",
                False,
            ),
            (
                "important.docx",
                "b2c3d4e5f6a12345678901234567890123456789012345678901234567890123",
                "/important/important.docx",
                True,
            ),
            (
                "guide.md",
                "c3d4e5f6a1b234567890123456789012345678901234567890123456789012",
                "/docs/guide.md",
                False,
            ),
        ]

        for filename, file_hash, path, preserve in test_docs:
            with contextlib.suppress(ValueError):  # document already exists
                repos["document"].create(filename, file_hash, path, preserve)

        print(f"   - Inserted {len(test_docs)} test documents")

        # Logs d'audit de test
        repos["audit"].create_log("system", "database_init", "Test data inserted")
        repos["audit"].create_log("admin", "system_config", "Initial configuration set")

        print("   - Inserted audit logs")


if __name__ == "__main__":
    main()
