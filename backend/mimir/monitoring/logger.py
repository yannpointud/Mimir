"""
Centralized Logging System with Structured JSON Format
Provides consistent logging across all modules with rotation and multiple handlers
"""

import json
import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

# Import settings for dynamic log level configuration
from mimir.config import settings
from mimir.shared.clock import utc_now


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for better parsing and analysis"""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": utc_now().isoformat() + "Z",
            "level": record.levelname,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
            "process_id": record.process,
            "thread_id": record.thread,
            "thread_name": record.threadName,
        }

        # Add extra fields if present
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_obj.update(record.extra_fields)

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Add stack trace for errors if available
        if record.levelno >= logging.ERROR and record.stack_info:
            log_obj["stack_trace"] = self.formatStack(record.stack_info)

        return json.dumps(log_obj, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Simple human-readable format for console output"""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Setup centralized logger with multiple handlers
    All logs go to /logs directory with rotation
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Prevent duplicate handlers if logger already configured
    if logger.handlers:
        return logger

    # Create logs directory if not exists
    log_dir = Path("./logs")
    log_dir.mkdir(exist_ok=True)

    # JSON Formatter for file handlers
    json_formatter = JSONFormatter()

    # Console formatter for human readability
    console_formatter = ConsoleFormatter()

    # Handler 1: Main application log with daily rotation
    app_handler = TimedRotatingFileHandler(
        log_dir / "app.log",
        when="midnight",
        interval=1,
        backupCount=30,  # Keep 30 days
        encoding="utf-8",
    )
    app_handler.setLevel(getattr(logging, level.upper()))
    app_handler.setFormatter(json_formatter)

    # Handler 2: Error log (errors only) with size-based rotation
    error_handler = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=10_000_000,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)

    # Handler 3: Debug log (everything) with size-based rotation
    debug_handler = RotatingFileHandler(
        log_dir / "debug.log",
        maxBytes=50_000_000,  # 50MB
        backupCount=3,
        encoding="utf-8",
    )
    debug_handler.setLevel(getattr(logging, level.upper()))
    debug_handler.setFormatter(json_formatter)

    # Handler 4: Console output for development
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    # Add all handlers
    logger.addHandler(app_handler)
    logger.addHandler(error_handler)
    logger.addHandler(debug_handler)
    logger.addHandler(console_handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


# Global logger instance for main app - uses settings.log_level from config
app_logger = setup_logger("mimir", level=settings.log_level.upper())


def setup_frontend_logger(level: str = "DEBUG") -> logging.Logger:
    """Setup specialized logger for frontend logs
    Logs frontend events to dedicated frontend.log file
    """
    logger = logging.getLogger("frontend")
    logger.setLevel(getattr(logging, level.upper()))

    # Prevent duplicate handlers if logger already configured
    if logger.handlers:
        return logger

    # Create logs directory if not exists
    log_dir = Path("./logs")
    log_dir.mkdir(exist_ok=True)

    # JSON Formatter for frontend logs
    json_formatter = JSONFormatter()

    # Frontend-specific log file with rotation
    frontend_handler = RotatingFileHandler(
        log_dir / "frontend.log",
        maxBytes=20_000_000,  # 20MB
        backupCount=5,
        encoding="utf-8",
    )
    frontend_handler.setLevel(getattr(logging, level.upper()))
    frontend_handler.setFormatter(json_formatter)

    # Add handler
    logger.addHandler(frontend_handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


# Global logger instances - uses settings.log_level from config
frontend_logger = setup_frontend_logger(level=settings.log_level.upper())
