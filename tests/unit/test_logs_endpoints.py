"""
Tests pour les endpoints de logs frontend.
"""

import pytest
from unittest.mock import patch, MagicMock

from fastapi import HTTPException

from mimir.api.endpoints.logs import (
    FrontendLogEntry,
    LogResponse,
    receive_frontend_log,
    frontend_logging_health,
)


class TestFrontendLogEntry:
    """Tests pour le modèle FrontendLogEntry."""

    def test_minimal_log_entry(self):
        """Test création d'une entrée de log minimale."""
        entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="INFO", module="app", message="Test message"
        )

        assert entry.timestamp == "2023-12-01T10:00:00Z"
        assert entry.level == "INFO"
        assert entry.module == "app"
        assert entry.message == "Test message"
        assert entry.url is None
        assert entry.userAgent is None
        assert entry.timeSinceStart is None
        assert entry.extra_data is None

    def test_complete_log_entry(self):
        """Test création d'une entrée de log complète."""
        entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z",
            level="ERROR",
            module="auth",
            message="Login failed",
            url="https://example.com/login",
            userAgent="Mozilla/5.0",
            timeSinceStart="120000",
            extra_data={"error_code": "AUTH_001", "user_id": "123"},
        )

        assert entry.url == "https://example.com/login"
        assert entry.userAgent == "Mozilla/5.0"
        assert entry.timeSinceStart == "120000"
        assert entry.extra_data == {"error_code": "AUTH_001", "user_id": "123"}


class TestLogResponse:
    """Tests pour le modèle LogResponse."""

    def test_log_response_creation(self):
        """Test création d'une réponse de log."""
        response = LogResponse(status="success", message="Log stored successfully")

        assert response.status == "success"
        assert response.message == "Log stored successfully"


class TestReceiveFrontendLog:
    """Tests pour l'endpoint receive_frontend_log."""

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_success_info(self, mock_logger):
        """Test réception d'un log INFO avec succès."""
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="INFO", module="app", message="Test message"
        )

        response = await receive_frontend_log(log_entry)

        assert response.status == "success"
        assert response.message == "Log entry stored successfully"

        # Vérifier que le logger a été appelé avec les bons paramètres
        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 20  # logging.INFO
        assert "[app] Test message" in call_args[0][1]

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_success_error(self, mock_logger):
        """Test réception d'un log ERROR avec succès."""
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="ERROR", module="auth", message="Login failed"
        )

        response = await receive_frontend_log(log_entry)

        assert response.status == "success"
        assert response.message == "Log entry stored successfully"

        # Vérifier que le logger a été appelé avec le niveau ERROR
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 40  # logging.ERROR
        assert "[auth] Login failed" in call_args[0][1]

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_with_optional_fields(self, mock_logger):
        """Test réception d'un log avec tous les champs optionnels."""
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z",
            level="WARNING",
            module="ui",
            message="Component warning",
            url="https://example.com/dashboard",
            userAgent="Mozilla/5.0",
            timeSinceStart="45000",
            extra_data={"component": "UserTable", "props": {"id": 123}},
        )

        response = await receive_frontend_log(log_entry)

        assert response.status == "success"

        # Vérifier que tous les champs extra sont présents
        call_args = mock_logger.log.call_args
        extra_fields = call_args[1]["extra"]["extra_fields"]

        assert extra_fields["url"] == "https://example.com/dashboard"
        assert extra_fields["user_agent"] == "Mozilla/5.0"
        assert extra_fields["time_since_start"] == "45000"
        assert extra_fields["component"] == "UserTable"
        assert extra_fields["props"] == {"id": 123}

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_unknown_level(self, mock_logger):
        """Test réception d'un log avec un niveau inconnu."""
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="UNKNOWN", module="app", message="Test message"
        )

        response = await receive_frontend_log(log_entry)

        assert response.status == "success"

        # Vérifier que le niveau par défaut INFO a été utilisé
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 20  # logging.INFO

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_debug_level(self, mock_logger):
        """Test réception d'un log DEBUG."""
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="DEBUG", module="debug", message="Debug info"
        )

        response = await receive_frontend_log(log_entry)

        assert response.status == "success"

        # Vérifier le niveau DEBUG
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 10  # logging.DEBUG

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_critical_level(self, mock_logger):
        """Test réception d'un log CRITICAL."""
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z",
            level="CRITICAL",
            module="system",
            message="Critical error",
        )

        response = await receive_frontend_log(log_entry)

        assert response.status == "success"

        # Vérifier le niveau CRITICAL
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 50  # logging.CRITICAL

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    @patch("mimir.api.endpoints.logs.logger")
    async def test_receive_log_exception_handling(self, mock_backend_logger, mock_frontend_logger):
        """Test gestion d'exception lors du traitement du log."""
        mock_frontend_logger.log.side_effect = Exception("Logging failed")

        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="INFO", module="app", message="Test message"
        )

        with pytest.raises(HTTPException):
            await receive_frontend_log(log_entry)

        # Vérifier que l'erreur a été loggée
        mock_backend_logger.error.assert_called_once()
        assert "Failed to process frontend log" in mock_backend_logger.error.call_args[0][0]


class TestFrontendLoggingHealth:
    """Tests pour l'endpoint frontend_logging_health."""

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_health_check_success(self, mock_logger):
        """Test health check avec succès."""
        # Simuler un logger avec handlers
        mock_handler1 = MagicMock()
        mock_handler2 = MagicMock()
        mock_logger.handlers = [mock_handler1, mock_handler2]
        mock_logger.level = 20  # logging.INFO

        result = await frontend_logging_health()

        assert result["status"] == "healthy"
        assert result["frontend_logger_configured"] is True
        assert result["handlers_count"] == 2
        assert result["log_level"] == "INFO"
        assert "timestamp" in result

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_health_check_no_handlers(self, mock_logger):
        """Test health check sans handlers configurés."""
        mock_logger.handlers = []
        mock_logger.level = 30  # logging.WARNING

        result = await frontend_logging_health()

        assert result["status"] == "healthy"  # Status reste healthy
        assert result["frontend_logger_configured"] is False
        assert result["handlers_count"] == 0
        assert result["log_level"] == "WARNING"

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_health_check_exception(self, mock_logger):
        """Test health check avec exception."""
        # Simuler une exception lors de l'accès aux handlers
        type(mock_logger).handlers = property(lambda x: exec('raise Exception("Test error")'))

        result = await frontend_logging_health()

        assert result["status"] == "unhealthy"
        assert "error" in result
        assert "timestamp" in result
