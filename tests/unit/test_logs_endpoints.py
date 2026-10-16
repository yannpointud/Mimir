"""
Frontend log endpoint tests.
"""

from unittest.mock import patch

import pytest

from mimir.api.endpoints.logs import (
    FrontendLogEntry,
    LogResponse,
    receive_frontend_log,
)


class TestFrontendLogEntry:
    """FrontendLogEntry model tests."""

    def test_minimal_log_entry(self):
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
    """LogResponse model tests."""

    def test_log_response_creation(self):
        response = LogResponse(status="success", message="Log stored successfully")

        assert response.status == "success"
        assert response.message == "Log stored successfully"


class TestReceiveFrontendLog:
    """receive_frontend_log endpoint tests."""

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_success_info(self, mock_logger):
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="INFO", module="app", message="Test message"
        )

        response = receive_frontend_log(log_entry)

        assert response.status == "success"
        assert response.message == "Log entry stored successfully"

        # Check that the logger was called with the right parameters
        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 20  # logging.INFO
        assert "[app] Test message" in call_args[0][1]

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_success_error(self, mock_logger):
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="ERROR", module="auth", message="Login failed"
        )

        response = receive_frontend_log(log_entry)

        assert response.status == "success"
        assert response.message == "Log entry stored successfully"

        # Check that the logger was called with the ERROR level
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 40  # logging.ERROR
        assert "[auth] Login failed" in call_args[0][1]

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_with_optional_fields(self, mock_logger):
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

        response = receive_frontend_log(log_entry)

        assert response.status == "success"

        # Check that every extra field is present
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
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="UNKNOWN", module="app", message="Test message"
        )

        response = receive_frontend_log(log_entry)

        assert response.status == "success"

        # Check that the default INFO level was used
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 20  # logging.INFO

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_debug_level(self, mock_logger):
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z", level="DEBUG", module="debug", message="Debug info"
        )

        response = receive_frontend_log(log_entry)

        assert response.status == "success"

        # Check the DEBUG level
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 10  # logging.DEBUG

    @pytest.mark.asyncio
    @patch("mimir.api.endpoints.logs.frontend_logger")
    async def test_receive_log_critical_level(self, mock_logger):
        log_entry = FrontendLogEntry(
            timestamp="2023-12-01T10:00:00Z",
            level="CRITICAL",
            module="system",
            message="Critical error",
        )

        response = receive_frontend_log(log_entry)

        assert response.status == "success"

        # Check the CRITICAL level
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == 50  # logging.CRITICAL
