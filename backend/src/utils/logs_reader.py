"""
Log Reader Utility for Admin Dashboard
Provides unified access to backend and frontend logs with filtering capabilities.
"""

import json
import logging
from datetime import datetime, timedelta  # noqa: F401
from pathlib import Path
from typing import Any
import re  # noqa: F401

logger = logging.getLogger(__name__)

# Log file paths
BACKEND_LOG = Path("./logs/app.log")
FRONTEND_LOG = Path("./logs/frontend.log")

class LogEntry:
    """Unified log entry model"""
    def __init__(self, timestamp: str, level: str, source: str, module: str,
                 message: str, details: dict[str, Any] | None = None):
        self.timestamp = timestamp
        self.level = level
        self.source = source
        self.module = module
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "source": self.source,
            "module": self.module,
            "message": self.message,
            "details": self.details
        }

def _parse_timestamp(timestamp_str: str) -> datetime:
    """Parse ISO timestamp string to datetime object"""
    try:
        # Remove 'Z' suffix if present and parse
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1] + '+00:00'
        return datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        # Fallback to current time if parsing fails
        return datetime.utcnow()

def _parse_backend_log_line(line: str) -> LogEntry | None:
    """Parse a single line from backend app.log"""
    try:
        log_data = json.loads(line.strip())

        # Extract basic fields
        timestamp = log_data.get('timestamp', '')
        level = log_data.get('level', 'INFO')
        module = log_data.get('module', 'unknown')
        message = log_data.get('message', '')

        # Extract details (everything except basic fields)
        details = {k: v for k, v in log_data.items()
                  if k not in ['timestamp', 'level', 'module', 'message']}

        return LogEntry(
            timestamp=timestamp,
            level=level,
            source='backend',
            module=module,
            message=message,
            details=details
        )
    except Exception as e:
        logger.debug(f"Failed to parse backend log line: {e}")
        return None

def _parse_frontend_log_line(line: str) -> LogEntry | None:
    """Parse a single line from frontend.log"""
    try:
        log_data = json.loads(line.strip())

        # Extract basic fields
        timestamp = log_data.get('timestamp', '')
        level = log_data.get('level', 'INFO')

        # Frontend logs have different structure
        if 'extra_fields' in log_data:
            extra = log_data['extra_fields']
            module = extra.get('frontend_module', 'frontend')

            # Extract message from log entry
            message = log_data.get('message', '')
            # Remove module prefix if present in message
            if message.startswith(f'[{module}]'):
                message = message[len(f'[{module}]'):].strip()

            # Build details from extra fields
            details = {k: v for k, v in extra.items()
                      if k not in ['frontend_module', 'frontend_timestamp']}
        else:
            # Fallback parsing
            module = log_data.get('module', 'frontend')
            message = log_data.get('message', '')
            details = {k: v for k, v in log_data.items()
                      if k not in ['timestamp', 'level', 'module', 'message']}

        return LogEntry(
            timestamp=timestamp,
            level=level,
            source='frontend',
            module=module,
            message=message,
            details=details
        )
    except Exception as e:
        logger.debug(f"Failed to parse frontend log line: {e}")
        return None

def _read_log_file(file_path: Path, max_lines: int = 1000) -> list[str]:
    """Read last N lines from log file efficiently"""
    try:
        if not file_path.exists():
            return []

        lines = []
        with open(file_path, encoding='utf-8') as f:
            # Read all lines for now, optimize later if needed
            all_lines = f.readlines()
            # Take last max_lines
            lines = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines

        return lines
    except Exception as e:
        logger.error(f"Failed to read log file {file_path}: {e}")
        return []

def _apply_filters(logs: list[LogEntry],
                  level: str | None = None,
                  source: str | None = None,
                  module: str | None = None,
                  search: str | None = None,
                  since: str | None = None) -> list[LogEntry]:
    """Apply filters to log entries"""
    filtered_logs = logs

    # Filter by level
    if level and level != 'ALL':
        # Map WARNING to WARN for consistency
        filter_level = 'WARNING' if level == 'WARN' else level
        filtered_logs = [log for log in filtered_logs
                        if log.level == filter_level or
                           (level == 'WARN' and log.level in ['WARN', 'WARNING'])]

    # Filter by source
    if source and source != 'ALL':
        filtered_logs = [log for log in filtered_logs if log.source == source.lower()]

    # Filter by module
    if module and module != 'ALL':
        filtered_logs = [log for log in filtered_logs
                        if module.lower() in log.module.lower()]

    # Filter by search text
    if search:
        search_lower = search.lower()
        filtered_logs = [log for log in filtered_logs
                        if search_lower in log.message.lower() or
                           search_lower in log.module.lower()]

    # Filter by timestamp
    if since:
        try:
            since_dt = _parse_timestamp(since)
            filtered_logs = [log for log in filtered_logs
                           if _parse_timestamp(log.timestamp) >= since_dt]
        except (TypeError, ValueError):
            logger.warning(f"Invalid since timestamp: {since}")

    return filtered_logs

def get_logs(level: str | None = None,
            source: str | None = None,
            module: str | None = None,
            search: str | None = None,
            since: str | None = None,
            limit: int = 50) -> tuple[list[dict[str, Any]], int]:
    """
    Get filtered logs from backend and frontend sources.

    Args:
        level: Log level filter (ALL, DEBUG, INFO, WARN, ERROR)
        source: Source filter (ALL, backend, frontend)
        module: Module name filter
        search: Text search in message
        since: ISO timestamp to filter logs since
        limit: Maximum number of logs to return (1-200)

    Returns:
        Tuple of (filtered_logs, total_count)
    """
    try:
        # Limit bounds checking
        limit = max(1, min(limit, 200))

        all_logs = []

        # Read backend logs if not filtered to frontend only
        if not source or source.lower() in ['all', 'backend']:
            backend_lines = _read_log_file(BACKEND_LOG, max_lines=2000)
            for line in backend_lines:
                log_entry = _parse_backend_log_line(line)
                if log_entry:
                    all_logs.append(log_entry)

        # Read frontend logs if not filtered to backend only
        if not source or source.lower() in ['all', 'frontend']:
            frontend_lines = _read_log_file(FRONTEND_LOG, max_lines=1000)
            for line in frontend_lines:
                log_entry = _parse_frontend_log_line(line)
                if log_entry:
                    all_logs.append(log_entry)

        # Apply filters
        filtered_logs = _apply_filters(all_logs, level, source, module, search, since)

        # Sort by timestamp (newest first)
        filtered_logs.sort(key=lambda x: _parse_timestamp(x.timestamp), reverse=True)

        # Apply limit
        limited_logs = filtered_logs[:limit]

        # Convert to dictionaries
        result_logs = [log.to_dict() for log in limited_logs]

        logger.info(f"Retrieved {len(result_logs)} logs (filtered from {len(all_logs)} total)")

        return result_logs, len(filtered_logs)

    except Exception as e:
        logger.error(f"Error retrieving logs: {e}")
        return [], 0

def get_available_modules() -> list[str]:
    """Get list of available modules from recent logs"""
    try:
        modules = set()

        # Get modules from backend logs
        backend_lines = _read_log_file(BACKEND_LOG, max_lines=500)
        for line in backend_lines:
            log_entry = _parse_backend_log_line(line)
            if log_entry:
                modules.add(log_entry.module)

        # Get modules from frontend logs
        frontend_lines = _read_log_file(FRONTEND_LOG, max_lines=200)
        for line in frontend_lines:
            log_entry = _parse_frontend_log_line(line)
            if log_entry:
                modules.add(log_entry.module)

        return sorted(list(modules))

    except Exception as e:
        logger.error(f"Error getting available modules: {e}")
        return []

def get_logs_summary() -> dict[str, Any]:
    """Get summary statistics about available logs"""
    try:
        # Count recent logs by level and source
        backend_lines = _read_log_file(BACKEND_LOG, max_lines=1000)
        frontend_lines = _read_log_file(FRONTEND_LOG, max_lines=500)

        summary = {
            'backend_logs_count': len(backend_lines),
            'frontend_logs_count': len(frontend_lines),
            'total_logs_count': len(backend_lines) + len(frontend_lines),
            'levels_available': ['ALL', 'DEBUG', 'INFO', 'WARN', 'ERROR'],
            'sources_available': ['ALL', 'backend', 'frontend'],
            'modules_available': get_available_modules()[:10],  # Top 10 modules
            'last_updated': datetime.utcnow().isoformat() + 'Z'
        }

        return summary

    except Exception as e:
        logger.error(f"Error getting logs summary: {e}")
        return {
            'backend_logs_count': 0,
            'frontend_logs_count': 0,
            'total_logs_count': 0,
            'levels_available': ['ALL', 'DEBUG', 'INFO', 'WARN', 'ERROR'],
            'sources_available': ['ALL', 'backend', 'frontend'],
            'modules_available': [],
            'last_updated': datetime.utcnow().isoformat() + 'Z'
        }