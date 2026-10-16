"""
Tests unitaires pour le système de logging centralisé
"""

import pytest
import json
import logging
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime

from src.monitoring.logger import (
    JSONFormatter,
    ConsoleFormatter,
    setup_logger,
    log_api_request,
    log_ingestion_event,
    log_search_query,
    log_llm_request,
    log_vector_operation,
    log_auth_event,
    log_health_check,
    log_system_event,
    log_performance,
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


class TestLoggingHelpers:
    """Tests pour les fonctions helpers de logging"""

    @pytest.fixture
    def mock_logger(self):
        """Logger mocké pour les tests"""
        return Mock(spec=logging.Logger)

    def test_log_api_request(self, mock_logger):
        """Test de log des requêtes API"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            log_api_request(method="POST", endpoint="/api/test", status_code=200)

            mock_logger.log.assert_called_once()
            call_args = mock_logger.log.call_args
            assert "API POST /api/test" in str(call_args[0])

    def test_log_search_query(self, mock_logger):
        """Test de log des requêtes de recherche"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            log_search_query(query="test search", results_count=5, duration_ms=200)

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "Search:" in str(call_args[0])

    def test_log_ingestion_event(self, mock_logger):
        """Test de log des événements d'ingestion"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            log_ingestion_event(document="doc.pdf", status="processed")

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "Ingestion:" in str(call_args[0])

    def test_log_ingestion_event_with_error(self, mock_logger):
        """Test de log des événements d'ingestion avec erreur"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            # Les fonctions de log n'ont pas de paramètre success, elles logguent toujours en info
            log_ingestion_event(document="doc.pdf", status="failed")

            mock_logger.info.assert_called_once()

    def test_log_auth_event(self, mock_logger):
        """Test de log des événements d'authentification"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            log_auth_event(event="login_success")

            mock_logger.log.assert_called_once()
            call_args = mock_logger.log.call_args
            assert "Auth login_success" in str(call_args[0])

    def test_log_performance(self, mock_logger):
        """Test de log des métriques de performance"""
        # log_performance est un décorateur, pas un gestionnaire de contexte
        with patch("src.monitoring.logger.app_logger", mock_logger):

            @log_performance("search_operation")
            def test_function():
                return "result"

            result = test_function()

            # Vérifier qu'il y a eu un log de performance
            assert mock_logger.debug.call_count >= 1
            assert result == "result"

    def test_log_llm_request(self, mock_logger):
        """Test de log des requêtes LLM"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            log_llm_request(
                model="mistral-small", operation="generate", tokens=10, duration_ms=1500
            )

            mock_logger.log.assert_called_once()
            call_args = mock_logger.log.call_args
            assert "LLM generate" in str(call_args[0])


class TestAdditionalLoggerFunctions:
    """Tests pour les fonctions supplémentaires de logging"""

    @pytest.fixture
    def mock_logger(self):
        """Logger mocké pour les tests"""
        return Mock(spec=logging.Logger)

    def test_log_vector_operation(self, mock_logger):
        """Test de log des opérations vectorielles"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            log_vector_operation(operation="similarity_search", vector_count=1000, duration_ms=300)

            mock_logger.log.assert_called_once()
            call_args = mock_logger.log.call_args
            assert "Vector similarity_search" in str(call_args[0])

    def test_log_health_check(self, mock_logger):
        """Test de log des health checks"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            log_health_check(component="database", status="healthy")

            mock_logger.log.assert_called_once()
            call_args = mock_logger.log.call_args
            assert "Health check: database - healthy" in str(call_args[0])

    def test_log_system_event(self, mock_logger):
        """Test de log des événements système"""
        with patch("src.monitoring.logger.app_logger", mock_logger):
            log_system_event(event="service_startup")

            mock_logger.log.assert_called_once()
            call_args = mock_logger.log.call_args
            assert "System: service_startup" in str(call_args[0])


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
