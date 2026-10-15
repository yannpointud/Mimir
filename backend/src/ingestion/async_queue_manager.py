"""
Async Queue Manager for sequential document processing
Provides async queue with retry logic and basic monitoring
Replaces threading-based QueueManager with full asyncio implementation
"""

import asyncio
import contextlib
import random
import time
from typing import Any
from collections.abc import Callable
from datetime import datetime

from .queue_manager import IngestionTask
from ..monitoring.logger import setup_logger

logger = setup_logger(__name__)

class AsyncQueueManager:
    """
    Async queue manager for document ingestion processing
    Implements single-worker pattern using asyncio for sequential processing
    """

    def __init__(self,
                 max_size: int = 1000,
                 worker_timeout: float = 60.0,
                 stats_interval: float = 300.0,  # 5 minutes
                 retry_base_delay: float = 2.0,
                 retry_max_delay: float = 60.0):
        """
        Initialize async queue manager

        Args:
            max_size: Maximum queue size (0 = unlimited)
            worker_timeout: Timeout for processing callback
            stats_interval: Interval for logging statistics
            retry_base_delay: Base delay (s) for exponential backoff before re-queuing a failed task
            retry_max_delay: Cap (s) for the exponential backoff between retries
        """
        self.max_size = max_size
        self.worker_timeout = worker_timeout
        self.stats_interval = stats_interval
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay

        # Async queue for tasks
        self.queue: asyncio.Queue[IngestionTask] = asyncio.Queue(maxsize=max_size)

        # Worker task management
        self.worker_task: asyncio.Task | None = None
        self.stop_event = asyncio.Event()
        self.processing_callback: Callable[[IngestionTask], bool] | None = None

        # Statistics and monitoring
        self.stats = {
            'tasks_processed': 0,
            'tasks_failed': 0,
            'tasks_retried': 0,
            'total_processing_time': 0.0,
            'avg_processing_time': 0.0,
            'queue_size': 0,
            'worker_active': False,
            'last_task_at': None,
            'started_at': None
        }

        self._last_stats_log = time.time()

        logger.info(f"Async queue manager initialized (max_size={max_size})")

    async def start(self, processing_callback: Callable[[IngestionTask], bool]):
        """
        Start the async worker task

        Args:
            processing_callback: Async function to process tasks, returns True on success
        """
        if self.worker_task and not self.worker_task.done():
            logger.warning("Worker task already running")
            return

        self.processing_callback = processing_callback
        self.stop_event.clear()

        # Create and start worker task
        self.worker_task = asyncio.create_task(
            self._worker_loop(),
            name="IngestionWorker"
        )

        self.stats['started_at'] = datetime.utcnow()
        self.stats['worker_active'] = True

        logger.info("Async queue manager started with worker task")

    async def stop(self, timeout: float = 30.0) -> bool:
        """
        Stop the worker task gracefully

        Args:
            timeout: Maximum time to wait for worker to stop

        Returns:
            True if stopped successfully
        """
        if not self.worker_task or self.worker_task.done():
            logger.info("Worker task not running")
            return True

        logger.info("Stopping async queue manager...")

        # Signal stop
        self.stop_event.set()

        # Wait for worker to finish
        try:
            await asyncio.wait_for(self.worker_task, timeout=timeout)
        except TimeoutError:
            logger.error(f"Worker task did not stop within {timeout}s, cancelling...")
            self.worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker_task

        self.stats['worker_active'] = False
        logger.info("Async queue manager stopped successfully")
        return True

    def add_task(self, task: IngestionTask) -> bool:
        """
        Add task to processing queue

        Args:
            task: IngestionTask to process

        Returns:
            True if task was added successfully
        """
        try:
            # Use put_nowait for non-blocking add
            self.queue.put_nowait(task)

            self.stats['queue_size'] = self.queue.qsize()

            logger.debug(
                f"Added task to queue: {task.file_path}",
                extra={'extra_fields': {
                    'file_path': task.file_path,
                    'document_id': task.document_id,
                    'queue_size': self.queue.qsize(),
                    'type': 'task_queued'
                }}
            )

            return True

        except asyncio.QueueFull:
            logger.error(
                f"Queue is full ({self.max_size}), cannot add task: {task.file_path}",
                extra={'extra_fields': {
                    'file_path': task.file_path,
                    'queue_size': self.queue.qsize(),
                    'max_size': self.max_size,
                    'type': 'queue_full'
                }}
            )
            return False

    async def _worker_loop(self):
        """Main async worker loop - processes tasks sequentially"""
        logger.info("Async worker task started")

        while not self.stop_event.is_set():
            try:
                # Get task with timeout
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)

                # Update queue size
                self.stats['queue_size'] = self.queue.qsize()

                # Process the task
                success = await self._process_task(task)

                # Handle result
                if success:
                    logger.debug(f"Task completed successfully: {task.file_path}")
                else:
                    # Handle retry logic
                    if task.can_retry():
                        task.increment_retry()

                        # Exponential backoff with jitter before retrying. The
                        # dominant failure here is Mistral rate limiting (429):
                        # re-queuing immediately would burn the retry budget
                        # while the limit is still saturated. Waiting lets the
                        # quota recover before the next attempt.
                        delay = self._compute_retry_delay(task.retry_count)
                        logger.warning(
                            f"Task failed, retrying ({task.retry_count}/{task.max_retries}) "
                            f"after {delay:.1f}s: {task.file_path}"
                        )
                        await asyncio.sleep(delay)

                        # Re-queue for retry
                        try:
                            self.queue.put_nowait(task)
                            self.stats['tasks_retried'] += 1
                            self.stats['queue_size'] = self.queue.qsize()
                        except asyncio.QueueFull:
                            logger.error(f"Cannot re-queue failed task (queue full): {task.file_path}")
                            self.stats['tasks_failed'] += 1
                    else:
                        logger.error(f"Task failed after {task.max_retries} retries: {task.file_path}")
                        self.stats['tasks_failed'] += 1

                # Mark task as done
                self.queue.task_done()

                # Log statistics periodically
                self._maybe_log_stats()

            except TimeoutError:
                # Timeout waiting for task - normal, continue
                continue
            except Exception as e:
                logger.error(f"Worker loop error: {str(e)}")
                await asyncio.sleep(1.0)  # Brief pause to prevent tight error loop

        logger.info("Async worker task stopped")

    def _compute_retry_delay(self, retry_count: int) -> float:
        """
        Compute the wait before a retry using capped exponential backoff + jitter.

        Args:
            retry_count: The task's retry attempt number (1 for the first retry)

        Returns:
            Delay in seconds: min(base * 2^(retry_count-1), max) + uniform jitter
        """
        exp = self.retry_base_delay * (2 ** max(0, retry_count - 1))
        delay = min(exp, self.retry_max_delay)
        # Full jitter within one base delay to desynchronize concurrent batches
        return delay + random.uniform(0.0, self.retry_base_delay)

    async def _process_task(self, task: IngestionTask) -> bool:
        """
        Process a single task with timing and error handling

        Args:
            task: Task to process

        Returns:
            True if processing succeeded
        """
        if not self.processing_callback:
            logger.error("No processing callback configured")
            return False

        start_time = time.time()

        try:
            logger.info(
                f"Processing task: {task.file_path} (attempt {task.retry_count + 1})",
                extra={'extra_fields': {
                    'file_path': task.file_path,
                    'document_id': task.document_id,
                    'retry_count': task.retry_count,
                    'type': 'task_processing'
                }}
            )

            # Process with async callback
            success = await self.processing_callback(task)

            processing_time = time.time() - start_time

            self.stats['tasks_processed'] += 1
            self.stats['total_processing_time'] += processing_time
            self.stats['avg_processing_time'] = (
                self.stats['total_processing_time'] / self.stats['tasks_processed']
            )
            self.stats['last_task_at'] = datetime.utcnow()

            if success:
                logger.info(
                    f"Task processed successfully in {processing_time:.2f}s: {task.file_path}",
                    extra={'extra_fields': {
                        'file_path': task.file_path,
                        'processing_time': processing_time,
                        'type': 'task_completed'
                    }}
                )
            else:
                logger.warning(f"Task processing returned False: {task.file_path}")

            return success

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(
                f"Task processing failed after {processing_time:.2f}s: {task.file_path} - {str(e)}",
                extra={'extra_fields': {
                    'file_path': task.file_path,
                    'processing_time': processing_time,
                    'error': str(e),
                    'type': 'task_error'
                }}
            )
            return False

    def _maybe_log_stats(self):
        """Log statistics periodically"""
        current_time = time.time()
        if current_time - self._last_stats_log >= self.stats_interval:
            self._log_stats()
            self._last_stats_log = current_time

    def _log_stats(self):
        """Log current statistics"""
        stats = self.get_stats()

        # Convert datetime objects to ISO strings for JSON serialization
        stats_serializable = stats.copy()
        if stats_serializable.get('started_at'):
            stats_serializable['started_at'] = stats_serializable['started_at'].isoformat() + 'Z'
        if stats_serializable.get('last_task_at'):
            stats_serializable['last_task_at'] = stats_serializable['last_task_at'].isoformat() + 'Z'

        logger.info(
            f"Queue stats: processed={stats['tasks_processed']}, "
            f"failed={stats['tasks_failed']}, queue_size={stats['queue_size']}, "
            f"avg_time={stats['avg_processing_time']:.2f}s",
            extra={'extra_fields': {
                **stats_serializable,
                'type': 'queue_stats'
            }}
        )

    def get_stats(self) -> dict[str, Any]:
        """
        Get current queue statistics

        Returns:
            Statistics dictionary
        """
        stats_copy = self.stats.copy()
        stats_copy['queue_size'] = self.queue.qsize()
        return stats_copy

    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self.queue.qsize()

    def is_empty(self) -> bool:
        """Check if queue is empty"""
        return self.queue.empty()

    def is_running(self) -> bool:
        """Check if worker task is running"""
        return (self.worker_task is not None and
                not self.worker_task.done() and
                not self.stop_event.is_set())

    async def clear_queue(self) -> int:
        """
        Clear all pending tasks from queue

        Returns:
            Number of tasks cleared
        """
        count = 0
        try:
            while True:
                self.queue.get_nowait()
                count += 1
        except asyncio.QueueEmpty:
            pass

        self.stats['queue_size'] = 0

        logger.warning(f"Cleared {count} pending tasks from queue")
        return count