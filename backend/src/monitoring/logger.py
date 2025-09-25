"""
Centralized Logging System with Structured JSON Format
Provides consistent logging across all modules with rotation and multiple handlers
"""

import logging
import json
import sys
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Dict, Any, Optional

# Import settings for dynamic log level configuration
from src.config import settings

class JSONFormatter(logging.Formatter):
    """Format logs as JSON for better parsing and analysis"""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_obj = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'message': record.getMessage(),
            'process_id': record.process,
            'thread_id': record.thread,
            'thread_name': record.threadName
        }

        # Add extra fields if present
        if hasattr(record, 'extra_fields') and isinstance(record.extra_fields, dict):
            log_obj.update(record.extra_fields)

        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)

        # Add stack trace for errors if available
        if record.levelno >= logging.ERROR and record.stack_info:
            log_obj['stack_trace'] = self.formatStack(record.stack_info)

        return json.dumps(log_obj, ensure_ascii=False)

class ConsoleFormatter(logging.Formatter):
    """Simple human-readable format for console output"""

    def __init__(self):
        super().__init__(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    Setup centralized logger with multiple handlers
    All logs go to /logs directory with rotation

    Args:
        name: Logger name (usually __name__)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Configured logger instance
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
        encoding='utf-8'
    )
    app_handler.setLevel(getattr(logging, level.upper()))
    app_handler.setFormatter(json_formatter)

    # Handler 2: Error log (errors only) with size-based rotation
    error_handler = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=10_000_000,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)

    # Handler 3: Debug log (everything) with size-based rotation
    debug_handler = RotatingFileHandler(
        log_dir / "debug.log",
        maxBytes=50_000_000,  # 50MB
        backupCount=3,
        encoding='utf-8'
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
    """
    Setup specialized logger for frontend logs
    Logs frontend events to dedicated frontend.log file
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
    Returns:
        Configured frontend logger instance
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
        encoding='utf-8'
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

def log_api_request(endpoint: str,
                   method: str,
                   duration_ms: Optional[float] = None,
                   status_code: Optional[int] = None,
                   user_type: Optional[str] = None,
                   **kwargs):
    """
    Helper to log API requests consistently

    Args:
        endpoint: API endpoint path
        method: HTTP method
        duration_ms: Request duration in milliseconds
        status_code: HTTP status code
        user_type: Type of user (admin, user, etc.)
        **kwargs: Additional fields
    """
    extra_fields = {
        'endpoint': endpoint,
        'method': method,
        'type': 'api_request',
        **kwargs
    }

    if duration_ms is not None:
        extra_fields['duration_ms'] = duration_ms
    if status_code is not None:
        extra_fields['status_code'] = status_code
    if user_type is not None:
        extra_fields['user_type'] = user_type

    message = f"API {method} {endpoint}"
    if status_code:
        message += f" [{status_code}]"
    if duration_ms:
        message += f" ({duration_ms:.1f}ms)"

    level = logging.INFO
    if status_code and status_code >= 400:
        level = logging.WARNING if status_code < 500 else logging.ERROR

    app_logger.log(level, message, extra={'extra_fields': extra_fields})

def log_ingestion_event(document: str,
                       status: str,
                       duration_ms: Optional[float] = None,
                       chunk_count: Optional[int] = None,
                       file_size_mb: Optional[float] = None,
                       **kwargs):
    """
    Helper to log ingestion events

    Args:
        document: Document filename or path
        status: Processing status
        duration_ms: Processing duration in milliseconds
        chunk_count: Number of chunks created
        file_size_mb: File size in megabytes
        **kwargs: Additional fields
    """
    extra_fields = {
        'document': document,
        'status': status,
        'type': 'ingestion',
        **kwargs
    }

    if duration_ms is not None:
        extra_fields['duration_ms'] = duration_ms
    if chunk_count is not None:
        extra_fields['chunk_count'] = chunk_count
    if file_size_mb is not None:
        extra_fields['file_size_mb'] = file_size_mb

    message = f"Ingestion: {document} - {status}"
    if chunk_count:
        message += f" ({chunk_count} chunks)"
    if duration_ms:
        message += f" in {duration_ms:.1f}ms"

    app_logger.info(message, extra={'extra_fields': extra_fields})

def log_search_query(query: str,
                    results_count: int,
                    duration_ms: float,
                    user_type: Optional[str] = None,
                    similarity_threshold: Optional[float] = None,
                    **kwargs):
    """
    Helper to log search queries

    Args:
        query: Search query (truncated for privacy)
        results_count: Number of results returned
        duration_ms: Search duration in milliseconds
        user_type: Type of user performing search
        similarity_threshold: Minimum similarity threshold used
        **kwargs: Additional fields
    """
    # Truncate query for privacy and log size
    query_truncated = query[:100] + "..." if len(query) > 100 else query

    extra_fields = {
        'query_length': len(query),
        'results_count': results_count,
        'duration_ms': duration_ms,
        'type': 'search',
        **kwargs
    }

    if user_type is not None:
        extra_fields['user_type'] = user_type
    if similarity_threshold is not None:
        extra_fields['similarity_threshold'] = similarity_threshold

    app_logger.info(
        f"Search: '{query_truncated}' - {results_count} results in {duration_ms:.1f}ms",
        extra={'extra_fields': extra_fields}
    )

def log_llm_request(model: str,
                   operation: str,
                   tokens: int,
                   duration_ms: float,
                   success: bool = True,
                   error: Optional[str] = None,
                   **kwargs):
    """
    Helper to log LLM API requests

    Args:
        model: LLM model name
        operation: Operation type (generate, embed)
        tokens: Number of tokens processed
        duration_ms: Request duration in milliseconds
        success: Whether request succeeded
        error: Error message if failed
        **kwargs: Additional fields
    """
    extra_fields = {
        'model': model,
        'operation': operation,
        'tokens': tokens,
        'duration_ms': duration_ms,
        'success': success,
        'type': 'llm_request',
        **kwargs
    }

    if error:
        extra_fields['error'] = error

    message = f"LLM {operation}: {model} - {tokens} tokens in {duration_ms:.1f}ms"
    if not success and error:
        message += f" [ERROR: {error}]"

    level = logging.INFO if success else logging.ERROR
    app_logger.log(level, message, extra={'extra_fields': extra_fields})

def log_vector_operation(operation: str,
                        vector_count: int,
                        duration_ms: float,
                        success: bool = True,
                        error: Optional[str] = None,
                        **kwargs):
    """
    Helper to log vector store operations

    Args:
        operation: Operation type (upsert, query, delete)
        vector_count: Number of vectors involved
        duration_ms: Operation duration in milliseconds
        success: Whether operation succeeded
        error: Error message if failed
        **kwargs: Additional fields
    """
    extra_fields = {
        'operation': operation,
        'vector_count': vector_count,
        'duration_ms': duration_ms,
        'success': success,
        'type': 'vector_operation',
        **kwargs
    }

    if error:
        extra_fields['error'] = error

    message = f"Vector {operation}: {vector_count} vectors in {duration_ms:.1f}ms"
    if not success and error:
        message += f" [ERROR: {error}]"

    level = logging.INFO if success else logging.ERROR
    app_logger.log(level, message, extra={'extra_fields': extra_fields})

def log_auth_event(event: str,
                  user_type: Optional[str] = None,
                  ip_address: Optional[str] = None,
                  success: bool = True,
                  reason: Optional[str] = None,
                  **kwargs):
    """
    Helper to log authentication events

    Args:
        event: Event type (login, logout, token_refresh)
        user_type: Type of user (admin, user)
        ip_address: Client IP address
        success: Whether event succeeded
        reason: Failure reason if applicable
        **kwargs: Additional fields
    """
    extra_fields = {
        'event': event,
        'success': success,
        'type': 'auth',
        **kwargs
    }

    if user_type:
        extra_fields['user_type'] = user_type
    if ip_address:
        extra_fields['ip_address'] = ip_address
    if reason:
        extra_fields['reason'] = reason

    message = f"Auth {event}"
    if user_type:
        message += f" ({user_type})"
    if not success and reason:
        message += f" - FAILED: {reason}"

    level = logging.INFO if success else logging.WARNING
    app_logger.log(level, message, extra={'extra_fields': extra_fields})

def log_health_check(component: str,
                    status: str,
                    duration_ms: Optional[float] = None,
                    details: Optional[Dict[str, Any]] = None,
                    **kwargs):
    """
    Helper to log health check events

    Args:
        component: Component name (database, llm, vector_store)
        status: Health status (healthy, unhealthy, degraded)
        duration_ms: Check duration in milliseconds
        details: Additional health details
        **kwargs: Additional fields
    """
    extra_fields = {
        'component': component,
        'status': status,
        'type': 'health_check',
        **kwargs
    }

    if duration_ms is not None:
        extra_fields['duration_ms'] = duration_ms
    if details:
        extra_fields['details'] = details

    message = f"Health check: {component} - {status}"
    if duration_ms:
        message += f" ({duration_ms:.1f}ms)"

    level = logging.INFO if status == 'healthy' else logging.WARNING
    app_logger.log(level, message, extra={'extra_fields': extra_fields})

def log_system_event(event: str,
                    severity: str = "info",
                    details: Optional[Dict[str, Any]] = None,
                    **kwargs):
    """
    Helper to log system-level events

    Args:
        event: Event description
        severity: Event severity (info, warning, error, critical)
        details: Additional event details
        **kwargs: Additional fields
    """
    extra_fields = {
        'event': event,
        'severity': severity,
        'type': 'system',
        **kwargs
    }

    if details:
        extra_fields['details'] = details

    level_mapping = {
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL
    }

    level = level_mapping.get(severity.lower(), logging.INFO)
    app_logger.log(level, f"System: {event}", extra={'extra_fields': extra_fields})

# Performance monitoring decorator
def log_performance(operation: str):
    """
    Decorator to automatically log function performance

    Args:
        operation: Operation name for logging
    """
    import functools
    import time

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000

                app_logger.debug(
                    f"Performance: {operation} completed in {duration_ms:.1f}ms",
                    extra={'extra_fields': {
                        'operation': operation,
                        'function': func.__name__,
                        'duration_ms': duration_ms,
                        'success': True,
                        'type': 'performance'
                    }}
                )

                return result

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000

                app_logger.error(
                    f"Performance: {operation} failed after {duration_ms:.1f}ms - {str(e)}",
                    extra={'extra_fields': {
                        'operation': operation,
                        'function': func.__name__,
                        'duration_ms': duration_ms,
                        'success': False,
                        'error': str(e),
                        'type': 'performance'
                    }}
                )

                raise

        return wrapper
    return decorator