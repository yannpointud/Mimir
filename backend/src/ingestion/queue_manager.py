"""
Ingestion Task Models
Provides data structures for document processing
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class IngestionTask:
    """Task for document ingestion processing"""

    file_path: str
    document_id: str
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return self.retry_count < self.max_retries

    def increment_retry(self):
        """Increment retry count"""
        self.retry_count += 1
