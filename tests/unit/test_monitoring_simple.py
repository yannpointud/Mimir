"""
Tests unitaires simplifiés pour le système de logging
Focus sur la couverture de code pour atteindre 80%
"""

import pytest
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from src.monitoring.logger import (
    JSONFormatter, ConsoleFormatter, setup_logger
)


class TestJSONFormatterSimple:
    """Tests simplifiés pour JSONFormatter"""

    def test_json_formatter_basic_format(self):
        """Test de base du formatage JSON"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=10,
            msg="Test message", args=(), exc_info=None
        )
        # Ajouter les attributs requis
        record.module = "test_module"
        record.funcName = "test_function"
        record.process = 1234
        record.thread = 5678
        record.threadName = "MainThread"

        result = formatter.format(record)

        assert isinstance(result, str)
        # Vérifier que c'est du JSON valide
        data = json.loads(result)
        assert data['level'] == 'INFO'
        assert data['message'] == 'Test message'

    def test_json_formatter_with_extra(self):
        """Test avec champs extra"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="test.py", lineno=10,
            msg="Error", args=(), exc_info=None
        )
        record.module = "test"
        record.funcName = "test"
        record.process = 1234
        record.thread = 5678
        record.threadName = "MainThread"
        record.extra_fields = {'key': 'value'}

        result = formatter.format(record)
        data = json.loads(result)

        assert data['key'] == 'value'
        assert data['level'] == 'ERROR'


class TestConsoleFormatterSimple:
    """Tests simplifiés pour ConsoleFormatter"""

    def test_console_formatter_creates(self):
        """Test de création du formateur console"""
        formatter = ConsoleFormatter()
        assert formatter is not None

    def test_console_formatter_formats(self):
        """Test de formatage console"""
        formatter = ConsoleFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=10,
            msg="Test", args=(), exc_info=None
        )

        result = formatter.format(record)
        assert isinstance(result, str)
        assert len(result) > 0


class TestSetupLoggerSimple:
    """Tests simplifiés pour setup_logger"""

    def test_setup_logger_creates_logger(self):
        """Test de création de logger"""
        logger = setup_logger("test_simple")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_simple"

    def test_setup_logger_default_level(self):
        """Test du niveau par défaut"""
        logger = setup_logger("test_level")

        # Le niveau par défaut devrait être INFO
        assert logger.level <= logging.INFO

    def test_setup_logger_has_handlers(self):
        """Test que le logger a des handlers"""
        logger = setup_logger("test_handlers")

        assert len(logger.handlers) > 0

    def test_setup_logger_string_level(self):
        """Test avec niveau string"""
        logger = setup_logger("test_str", level="DEBUG")

        assert logger.level == logging.DEBUG

    def test_setup_logger_int_level(self):
        """Test avec niveau int en string"""
        logger = setup_logger("test_int", level="WARNING")

        assert logger.level == logging.WARNING


class TestLoggerIntegrationSimple:
    """Tests d'intégration simplifiés"""

    def test_logger_can_log_all_levels(self):
        """Test que le logger peut logger tous les niveaux"""
        logger = setup_logger("test_all_levels", level="DEBUG")

        # Ces appels ne doivent pas lever d'exception
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")

        assert True  # Si on arrive ici, pas d'exception

    def test_multiple_logger_creation(self):
        """Test de création de plusieurs loggers"""
        logger1 = setup_logger("multi1")
        logger2 = setup_logger("multi2")
        logger3 = setup_logger("multi1")  # Même nom que le premier

        assert logger1.name == "multi1"
        assert logger2.name == "multi2"
        assert logger1 is logger3  # Doit être le même instance

    def test_logger_with_file_creation(self):
        """Test de création de logger avec fichier temporaire"""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            logger = setup_logger("file_test")

            # Tester que le logger fonctionne
            logger.info("Test file logging")

            assert isinstance(logger, logging.Logger)
        finally:
            # Nettoyer le fichier temporaire
            Path(tmp_path).unlink(missing_ok=True)


class TestLoggerFunctionalitySimple:
    """Tests de fonctionnalité simple"""

    def test_json_formatter_no_exception_info(self):
        """Test du formateur sans info d'exception"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=1,
            msg="No exception", args=(), exc_info=None
        )
        record.module = "test"
        record.funcName = "test"
        record.process = 1
        record.thread = 1
        record.threadName = "Main"

        result = formatter.format(record)
        data = json.loads(result)

        assert 'exception' not in data
        assert data['message'] == 'No exception'

    def test_json_formatter_ensure_ascii_false(self):
        """Test que ensure_ascii=False fonctionne"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=1,
            msg="Message avec accents: café", args=(), exc_info=None
        )
        record.module = "test"
        record.funcName = "test"
        record.process = 1
        record.thread = 1
        record.threadName = "Main"

        result = formatter.format(record)

        # Doit contenir les caractères unicode directement
        assert "café" in result
        # Et être du JSON valide
        data = json.loads(result)
        assert data['message'] == "Message avec accents: café"