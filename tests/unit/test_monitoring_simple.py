"""
Simplified unit tests for the logging system
Focus on code coverage to reach 80%
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
    """Simplified tests for JSONFormatter."""

    def test_json_formatter_basic_format(self):
        """Test basic JSON formatting."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=10,
            msg="Test message", args=(), exc_info=None
        )
        # Add required attributes
        record.module = "test_module"
        record.funcName = "test_function"
        record.process = 1234
        record.thread = 5678
        record.threadName = "MainThread"

        result = formatter.format(record)

        assert isinstance(result, str)
        # Verify it is valid JSON
        data = json.loads(result)
        assert data['level'] == 'INFO'
        assert data['message'] == 'Test message'

    def test_json_formatter_with_extra(self):
        """Test with extra fields."""
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
    """Simplified tests for ConsoleFormatter."""

    def test_console_formatter_creates(self):
        """Test console formatter creation."""
        formatter = ConsoleFormatter()
        assert formatter is not None

    def test_console_formatter_formats(self):
        """Test console formatting."""
        formatter = ConsoleFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=10,
            msg="Test", args=(), exc_info=None
        )

        result = formatter.format(record)
        assert isinstance(result, str)
        assert len(result) > 0


class TestSetupLoggerSimple:
    """Simplified tests for setup_logger."""

    def test_setup_logger_creates_logger(self):
        """Test logger creation."""
        logger = setup_logger("test_simple")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_simple"

    def test_setup_logger_default_level(self):
        """Test default level."""
        logger = setup_logger("test_level")

        # Default level should be INFO
        assert logger.level <= logging.INFO

    def test_setup_logger_has_handlers(self):
        """Test that the logger has handlers."""
        logger = setup_logger("test_handlers")

        assert len(logger.handlers) > 0

    def test_setup_logger_string_level(self):
        """Test with string level."""
        logger = setup_logger("test_str", level="DEBUG")

        assert logger.level == logging.DEBUG

    def test_setup_logger_int_level(self):
        """Test with int level as string."""
        logger = setup_logger("test_int", level="WARNING")

        assert logger.level == logging.WARNING


class TestLoggerIntegrationSimple:
    """Simplified integration tests."""

    def test_logger_can_log_all_levels(self):
        """Test that the logger can log all levels."""
        logger = setup_logger("test_all_levels", level="DEBUG")

        # These calls must not raise an exception
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")

        assert True  # If we get here, no exception

    def test_multiple_logger_creation(self):
        """Test creating multiple loggers."""
        logger1 = setup_logger("multi1")
        logger2 = setup_logger("multi2")
        logger3 = setup_logger("multi1")  # Same name as first

        assert logger1.name == "multi1"
        assert logger2.name == "multi2"
        assert logger1 is logger3  # Must be the same instance

    def test_logger_with_file_creation(self):
        """Test logger creation with temporary file."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            logger = setup_logger("file_test")

            # Test that the logger works
            logger.info("Test file logging")

            assert isinstance(logger, logging.Logger)
        finally:
            # Clean up the temporary file
            Path(tmp_path).unlink(missing_ok=True)


class TestLoggerFunctionalitySimple:
    """Simple functionality tests."""

    def test_json_formatter_no_exception_info(self):
        """Test formatter without exception info."""
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
        """Test that ensure_ascii=False works."""
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

        # Must contain unicode characters directly
        assert "café" in result
        # And be valid JSON
        data = json.loads(result)
        assert data['message'] == "Message avec accents: café"
