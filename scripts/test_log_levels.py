#!/usr/bin/env python3
"""Test script checking the effect of the logging settings.

This script proves that settings.log_level is currently IGNORED.
"""

import os
import sys
import logging

# Ajouter le backend au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from src.config import settings
from src.monitoring.logger import app_logger, frontend_logger


def test_current_implementation():
    """Test the current implementation - PROVES THE BUG"""
    print("=" * 80)
    print("TEST: Implémentation actuelle du système de logging")
    print("=" * 80)

    print("\n1. Configuration depuis .env:")
    print(f"   - LOG_LEVEL = {settings.log_level}")
    print(f"   - ENVIRONMENT = {settings.environment}")
    print(f"   - RAG_DEBUG_ENABLED = {settings.rag_debug_enabled}")

    print("\n2. Niveaux effectifs des loggers globaux:")
    print(f"   - app_logger (mimir): {logging.getLevelName(app_logger.level)}")
    print(f"   - frontend_logger: {logging.getLevelName(frontend_logger.level)}")

    print("\n3. Niveaux des handlers de app_logger:")
    for i, handler in enumerate(app_logger.handlers):
        handler_type = handler.__class__.__name__
        handler_level = logging.getLevelName(handler.level)
        print(f"   - Handler {i} ({handler_type}): {handler_level}")

    print("\n4. Test d'un logger enfant (comme dans les autres modules):")
    test_logger = logging.getLogger("src.api.endpoints.chat")
    print(f"   - Logger 'src.api.endpoints.chat': {logging.getLevelName(test_logger.level)}")
    print(f"   - Effective level: {logging.getLevelName(test_logger.getEffectiveLevel())}")

    print("\n5. Test de logging réel:")
    test_logger.debug("   [DEBUG] Ce message devrait être écrit si bug présent")
    test_logger.info("   [INFO] Ce message devrait toujours être écrit")
    test_logger.warning("   [WARNING] Ce message devrait toujours être écrit")

    print("\n" + "=" * 80)
    print("RÉSULTAT DU TEST:")
    print("=" * 80)

    if app_logger.level == logging.DEBUG:
        print("❌ BUG CONFIRMÉ: app_logger est en DEBUG alors que LOG_LEVEL=" + settings.log_level)
        print("   → Les logs DEBUG sont écrits dans debug.log même en production!")
        return False
    else:
        print("✅ OK: app_logger respecte LOG_LEVEL=" + settings.log_level)
        return True


def show_file_sizes():
    """Show the size of the log files"""
    print("\n" + "=" * 80)
    print("TAILLE DES FICHIERS DE LOGS ACTUELS:")
    print("=" * 80)

    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    if not os.path.exists(log_dir):
        print("Dossier logs/ n'existe pas encore")
        return

    for log_file in ["app.log", "error.log", "debug.log", "frontend.log", "rag_debug.log"]:
        log_path = os.path.join(log_dir, log_file)
        if os.path.exists(log_path):
            size_bytes = os.path.getsize(log_path)
            size_mb = size_bytes / (1024 * 1024)
            print(f"   - {log_file}: {size_mb:.2f} MB ({size_bytes:,} bytes)")
        else:
            print(f"   - {log_file}: n'existe pas")


if __name__ == "__main__":
    test_current_implementation()
    show_file_sizes()

    print("\n" + "=" * 80)
    print("RECOMMANDATIONS:")
    print("=" * 80)
    print("1. Modifier logger.py ligne 131 pour utiliser settings.log_level")
    print("2. Modifier logger.py ligne 177 pour utiliser settings.log_level")
    print("3. Modifier les handlers pour utiliser le niveau du logger parent")
    print("4. Désactiver RAG_DEBUG_ENABLED en production")
    print("5. Mettre LOG_LEVEL=WARNING en production")
    print("=" * 80)
