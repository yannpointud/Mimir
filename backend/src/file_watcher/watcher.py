"""
File system watcher for automatic document ingestion.

This module monitors specified directories for file changes and automatically
queues new or modified documents for ingestion processing.
"""

import os
import time
from pathlib import Path
from typing import Any
from collections.abc import Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
import threading
import logging

logger = logging.getLogger(__name__)


class DocumentFileHandler(FileSystemEventHandler):
    """File system event handler for document files."""

    def __init__(
        self,
        supported_extensions: set[str],
        on_file_added: Callable[[str], None],
        on_file_modified: Callable[[str], None] | None = None,
        ignore_hidden: bool = True,
        ignore_temp: bool = True,
    ):
        super().__init__()
        self.supported_extensions = {ext.lower() for ext in supported_extensions}
        self.on_file_added = on_file_added
        self.on_file_modified = on_file_modified
        self.ignore_hidden = ignore_hidden
        self.ignore_temp = ignore_temp

        # Tracking for avoiding duplicate events
        self._recently_processed: dict[str, float] = {}
        self._lock = threading.Lock()

        logger.info(f"DocumentFileHandler initialized - extensions: {self.supported_extensions}")

    def _should_ignore_file(self, file_path: str) -> bool:
        file_name = os.path.basename(file_path)

        # Ignore hidden files
        if self.ignore_hidden and file_name.startswith("."):
            return True

        # Ignore temporary files
        if self.ignore_temp:
            temp_patterns = [
                "~$",  # Microsoft Office temp files
                ".tmp",
                ".temp",
                ".part",  # Partial downloads
                ".crdownload",  # Chrome downloads
            ]
            if any(
                file_name.endswith(pattern) or pattern in file_name for pattern in temp_patterns
            ):
                return True

        # Check file extension
        file_ext = os.path.splitext(file_path)[1].lower()
        return file_ext not in self.supported_extensions

    def _is_recently_processed(self, file_path: str, event_type: str) -> bool:
        """Check if file was recently processed to avoid duplicates."""
        with self._lock:
            key = f"{file_path}:{event_type}"
            current_time = time.time()

            # Clean old entries (older than 5 seconds)
            to_remove = [
                k
                for k, timestamp in self._recently_processed.items()
                if current_time - timestamp > 5
            ]
            for k in to_remove:
                del self._recently_processed[k]

            # Check if recently processed
            if key in self._recently_processed:
                return True

            # Mark as processed
            self._recently_processed[key] = current_time
            return False

    def on_created(self, event: FileSystemEvent):
        """Handle file creation events."""
        if event.is_directory:
            return

        file_path = event.src_path

        if self._should_ignore_file(file_path):
            return

        if self._is_recently_processed(file_path, "created"):
            return

        # Wait a bit to ensure file is fully written
        self._wait_for_file_stability(file_path)

        if os.path.exists(file_path):
            logger.info(f"New file detected: {file_path}")
            try:
                self.on_file_added(file_path)
            except Exception as e:  # noqa: BLE001 - observer thread boundary: a failing callback must not stop the watcher
                logger.error(f"Error processing new file {file_path}: {e}")

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification events."""
        if event.is_directory:
            return

        if not self.on_file_modified:
            return

        file_path = event.src_path

        if self._should_ignore_file(file_path):
            return

        if self._is_recently_processed(file_path, "modified"):
            return

        # Wait a bit to ensure file modifications are complete
        self._wait_for_file_stability(file_path)

        if os.path.exists(file_path):
            logger.info(f"File modified: {file_path}")
            try:
                self.on_file_modified(file_path)
            except Exception as e:  # noqa: BLE001 - observer thread boundary: a failing callback must not stop the watcher
                logger.error(f"Error processing modified file {file_path}: {e}")

    def _wait_for_file_stability(self, file_path: str, max_wait: int = 5):
        """Wait for file to be stable (no size changes)."""
        try:
            if not os.path.exists(file_path):
                return

            previous_size = -1
            waited: float = 0

            while waited < max_wait:
                try:
                    current_size = os.path.getsize(file_path)
                    if current_size == previous_size and current_size > 0:
                        break
                    previous_size = current_size
                    time.sleep(0.5)
                    waited += 0.5
                except OSError:
                    # File might be locked or deleted
                    break

        except Exception as e:  # noqa: BLE001 - best effort: the event is handled even if the wait fails
            logger.debug(f"Error waiting for file stability: {e}")


class FileWatcher:
    """File system watcher service for document ingestion."""

    def __init__(
        self,
        watch_directories: list[str],
        supported_extensions: set[str],
        on_file_added: Callable[[str], None],
        on_file_modified: Callable[[str], None] | None = None,
        recursive: bool = True,
    ):
        self.watch_directories = [Path(d).resolve() for d in watch_directories]
        self.supported_extensions = supported_extensions
        self.recursive = recursive
        self.observer = Observer()
        self.is_running = False

        # Create handler
        self.handler = DocumentFileHandler(
            supported_extensions=supported_extensions,
            on_file_added=on_file_added,
            on_file_modified=on_file_modified,
        )

        # Statistics
        self.stats: dict[str, Any] = {
            "files_processed": 0,
            "files_added": 0,
            "files_modified": 0,
            "errors": 0,
            "start_time": None,
        }

        logger.info(f"FileWatcher initialized - directories: {self.watch_directories}")

    def start(self) -> bool:
        """Start the file watcher."""
        try:
            if self.is_running:
                logger.warning("FileWatcher is already running")
                return True

            # Validate directories
            valid_directories = []
            for directory in self.watch_directories:
                if directory.exists() and directory.is_dir():
                    valid_directories.append(directory)
                    logger.info(f"Watching directory: {directory}")
                else:
                    logger.warning(f"Directory does not exist or is not accessible: {directory}")

            if not valid_directories:
                logger.error("No valid directories to watch")
                return False

            # Set up watchers
            for directory in valid_directories:
                self.observer.schedule(self.handler, str(directory), recursive=self.recursive)

            # Start observer
            self.observer.start()
            self.is_running = True
            self.stats["start_time"] = time.time()

            logger.info("FileWatcher started successfully")
            return True

        except Exception as e:  # noqa: BLE001 - never raise: any failure is reported as not started
            logger.error(f"Failed to start FileWatcher: {e}")
            return False

    def stop(self, timeout: int = 5) -> bool:
        """Stop the file watcher."""
        try:
            if not self.is_running:
                return True

            logger.info("Stopping FileWatcher...")
            self.observer.stop()
            self.observer.join(timeout=timeout)

            self.is_running = False
            logger.info("FileWatcher stopped")
            return True

        except Exception as e:  # noqa: BLE001 - never raise: any failure is reported as not stopped
            logger.error(f"Error stopping FileWatcher: {e}")
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get file watcher statistics."""
        stats = self.stats.copy()
        stats["is_running"] = self.is_running
        stats["watched_directories"] = [str(d) for d in self.watch_directories]
        stats["supported_extensions"] = list(self.supported_extensions)

        if stats["start_time"]:
            stats["uptime_seconds"] = time.time() - stats["start_time"]

        return stats

    def add_directory(self, directory: str) -> bool:
        """Add a new directory to watch."""
        try:
            dir_path = Path(directory).resolve()

            if not dir_path.exists() or not dir_path.is_dir():
                logger.error(f"Directory does not exist: {directory}")
                return False

            if dir_path in self.watch_directories:
                logger.warning(f"Directory already being watched: {directory}")
                return True

            # Add to observer if running
            if self.is_running:
                self.observer.schedule(self.handler, str(dir_path), recursive=self.recursive)

            self.watch_directories.append(dir_path)
            logger.info(f"Added directory to watch list: {directory}")
            return True

        except Exception as e:  # noqa: BLE001 - never raise: any failure is reported as not added
            logger.error(f"Failed to add directory {directory}: {e}")
            return False

    def remove_directory(self, directory: str) -> bool:
        """Remove a directory from watching."""
        try:
            dir_path = Path(directory).resolve()

            if dir_path not in self.watch_directories:
                logger.warning(f"Directory not in watch list: {directory}")
                return False

            self.watch_directories.remove(dir_path)

            # Note: watchdog doesn't provide easy way to remove specific watch
            # Would need to restart observer to fully remove
            logger.info(f"Removed directory from watch list: {directory}")
            logger.info("Note: Restart file watcher to fully remove directory monitoring")

            return True

        except Exception as e:  # noqa: BLE001 - never raise: any failure is reported as not removed
            logger.error(f"Failed to remove directory {directory}: {e}")
            return False

    def scan_existing_files(self) -> list[str]:
        """Scan existing files in watched directories."""
        existing_files = []

        try:
            for directory in self.watch_directories:
                if not directory.exists():
                    continue

                # Use glob pattern to find files
                for ext in self.supported_extensions:
                    pattern = f"**/*{ext}" if self.recursive else f"*{ext}"
                    for file_path in directory.glob(pattern):
                        if file_path.is_file() and not self.handler._should_ignore_file(
                            str(file_path)
                        ):
                            existing_files.append(str(file_path))

            logger.info(f"Found {len(existing_files)} existing files")

        except Exception as e:  # noqa: BLE001 - best effort: return the files found so far
            logger.error(f"Error scanning existing files: {e}")

        return existing_files
