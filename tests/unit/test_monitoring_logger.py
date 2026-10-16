"""
Tests unitaires pour le système de logging centralisé
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from mimir.monitoring.logger import (
    ConsoleFormatter,
    JSONFormatter,
    setup_logger,
)


class TestJSONFormatter:
    """Tests pour le formateur JSON"""

    def test_json_formatter_basic(self):
        """Test de formatage de base"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.module = "test_module"
        record.funcName = "test_function"
        record.process = 1234
        record.thread = 5678
        record.threadName = "MainThread"

        formatted = formatter.format(record)
        log_data = json.loads(formatted)

        assert log_data["level"] == "INFO"
        assert log_data["module"] == "test_module"
        assert log_data["function"] == "test_function"
        assert log_data["line"] == 10
        assert log_data["message"] == "Test message"
        assert log_data["process_id"] == 1234
        assert log_data["thread_id"] == 5678
        assert "timestamp" in log_data

    def test_json_formatter_with_extra_fields(self):
        """Test de formatage avec champs supplémentaires"""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.module = "test_module"
        record.funcName = "test_function"
        record.process = 1234
        record.thread = 5678
        record.threadName = "MainThread"
        record.extra_fields = {"user_id": "123", "action": "login"}

        formatted = formatter.format(record)
        log_data = json.loads(formatted)

        assert log_data["user_id"] == "123"
        assert log_data["action"] == "login"

    def test_json_formatter_with_exception(self):
        """Test de formatage avec exception"""
        formatter = JSONFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=10,
                msg="Error occurred",
                args=(),
                exc_info=sys.exc_info(),
            )
            record.module = "test_module"
            record.funcName = "test_function"
            record.process = 1234
            record.thread = 5678
            record.threadName = "MainThread"

            formatted = formatter.format(record)
            log_data = json.loads(formatted)

            assert log_data["level"] == "ERROR"
            assert "exception" in log_data
            assert "ValueError: Test error" in log_data["exception"]

    def test_json_formatter_no_exception_info(self):
        """Without exc_info, no exception key is emitted."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="No exception",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "test"
        record.process = 1
        record.thread = 1
        record.threadName = "Main"

        result = formatter.format(record)
        data = json.loads(result)

        assert "exception" not in data
        assert data["message"] == "No exception"

    def test_json_formatter_ensure_ascii_false(self):
        """Non-ASCII characters are written as is (ensure_ascii=False)."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Message avec accents: café",
            args=(),
            exc_info=None,
        )
        record.module = "test"
        record.funcName = "test"
        record.process = 1
        record.thread = 1
        record.threadName = "Main"

        result = formatter.format(record)

        # Must contain unicode characters directly
        assert "café" in result
        # And be valid JSON
        data = json.loads(result)
        assert data["message"] == "Message avec accents: café"


class TestConsoleFormatter:
    """Tests pour le formateur console"""

    def test_console_formatter_basic(self):
        """Test de formatage console de base"""
        formatter = ConsoleFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.created = datetime.now().timestamp()

        formatted = formatter.format(record)

        assert "test" in formatted
        assert "INFO" in formatted
        assert "Test message" in formatted


class TestSetupLogger:
    """Tests pour la configuration des loggers"""

    def test_setup_logger_basic(self):
        """Test de configuration de base"""
        logger = setup_logger("test_logger")

        assert logger.name == "test_logger"
        assert logger.level == logging.INFO
        assert len(logger.handlers) > 0

    def test_setup_logger_with_level(self):
        """Test de configuration avec niveau spécifique"""
        logger = setup_logger("test_logger", level="DEBUG")

        assert logger.level == logging.DEBUG

    def test_setup_logger_singleton(self):
        """Test que setup_logger renvoie le même logger pour le même nom"""
        logger1 = setup_logger("same_logger")
        logger2 = setup_logger("same_logger")

        assert logger1 is logger2

    def test_setup_logger_with_file_handler(self):
        """Test de configuration avec handler de fichier"""
        # Le setup_logger n'accepte pas de paramètre log_file, on teste juste la création
        logger = setup_logger("file_logger")

        # Vérifier qu'un handler de fichier existe (créé automatiquement)
        file_handlers = [h for h in logger.handlers if hasattr(h, "baseFilename")]
        assert len(file_handlers) > 0


class TestLoggerIntegration:
    """Tests d'intégration du système de logging"""

    def test_end_to_end_logging(self):
        """Test d'intégration complète du logging"""
        # Configuration du logger
        logger = setup_logger("integration_test")

        # Test des différents niveaux de log
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")

        # Vérifier que le logger a bien été configuré avec des handlers
        assert len(logger.handlers) > 0

        # Vérifier que les logs par défaut sont créés dans ./logs
        log_dir = Path("./logs")
        if log_dir.exists():
            log_files = list(log_dir.glob("*.log"))
            assert len(log_files) > 0

    def test_multiple_loggers_independence(self):
        """Test que plusieurs loggers sont indépendants"""
        logger1 = setup_logger("module1")
        logger2 = setup_logger("module2")

        assert logger1 is not logger2
        assert logger1.name != logger2.name
