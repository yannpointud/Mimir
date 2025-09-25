"""
Ingestion Task Models
Provides task priority and data structures for document processing
"""

from dataclasses import dataclass, field
from enum import IntEnum
from datetime import datetime
from typing import Dict, Any

class TaskPriority(IntEnum):
    """Task priority levels (lower number = higher priority)"""
    URGENT = 1      # Protected documents, critical updates
    HIGH = 2        # Manual uploads, user-triggered processing
    NORMAL = 3      # Regular file watcher events
    LOW = 4         # Maintenance, optimization tasks

@dataclass
class IngestionTask:
    """Task for document ingestion processing"""
    file_path: str
    document_id: str
    priority: TaskPriority = TaskPriority.NORMAL
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure priority is TaskPriority enum"""
        if isinstance(self.priority, int):
            self.priority = TaskPriority(self.priority)

    def __lt__(self, other):
        """For priority queue ordering"""
        if not isinstance(other, IngestionTask):
            return NotImplemented
        # Primary: priority (lower = higher priority)
        # Secondary: creation time (older = higher priority)
        return (self.priority.value, self.created_at) < (other.priority.value, other.created_at)

    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return self.retry_count < self.max_retries

    def increment_retry(self):
        """Increment retry count and adjust priority"""
        self.retry_count += 1
        # Increase priority for retries (up to URGENT)
        if self.priority.value > TaskPriority.URGENT.value:
            self.priority = TaskPriority(max(TaskPriority.URGENT.value, self.priority.value - 1))

