"""
Pydantic models of the API requests and responses, and filename validation.
"""

import os
import re
import unicodedata
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mimir.shared.clock import utc_now


class DocumentStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    ERROR = "error"


class BaseResponse(BaseModel):
    success: bool = True
    message: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class PaginationModel(BaseModel):
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    order_by: str = Field(default="created_at")
    desc_order: bool = Field(default=True)


class DocumentBase(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    path: str | None = Field(None, max_length=500)
    preserve: bool = Field(default=False)


class DocumentResponse(DocumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_hash: str
    status: DocumentStatus
    error_message: str | None = None
    chunk_count: int
    created_at: datetime
    indexed_at: datetime | None = None


class ChunkResponse(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    text: str
    metadata: dict[str, Any] | None = None


class DocumentWithChunksResponse(DocumentResponse):
    chunks: list[ChunkResponse] = []
    content: str | None = None  # Text extracted from the original file, if readable
    file_size: int | None = None
    mime_type: str | None = None


class DocumentListResponse(BaseResponse):
    documents: list[DocumentResponse]
    total_count: int
    pagination: dict[str, Any]


class HealthCheckResponse(BaseResponse):
    status: str = Field(default="healthy")
    checks: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    error_message: str
    details: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=utc_now)


# Statistics, administration and maintenance responses.
#
# Field names, order and types mirror the JSON these routes returned when they
# were typed as plain dicts: values pre-formatted with isoformat() stay `str`,
# datetimes serialized by Pydantic stay `datetime`, and counters stay `int`
# (a `float` field would turn 0 into 0.0).


class RootResponse(BaseModel):
    """API entry point (GET /)"""

    name: str
    description: str
    version: str
    status: str
    docs_url: str | None


class DocumentStatusCounts(BaseModel):
    """Number of documents per ingestion status"""

    pending: int
    indexing: int
    indexed: int
    error: int


class VectorStoreOverview(BaseModel):
    """Vector store figures shown with the document statistics"""

    total_vectors: int
    active_vectors: int
    deleted_vectors: int
    total_documents: int
    memory_usage_mb: float
    health_status: bool


class StorageInfo(BaseModel):
    """Upload storage settings"""

    upload_directory: str
    supported_extensions: list[str]
    max_file_size_mb: int


class DocumentStatsOverview(BaseModel):
    """Document statistics with vector store health"""

    total_documents: int
    by_status: DocumentStatusCounts
    total_chunks: int
    preserved_documents: int
    vector_store: VectorStoreOverview
    storage_info: StorageInfo
    timestamp: datetime


class ConsistencyValidationResponse(BaseModel):
    """Outcome of a SQLite/FAISS consistency validation"""

    success: bool
    message: str
    # Report built by VectorStoreValidator.validate_consistency (also saved
    # as JSON and audited as is).
    validation_result: dict[str, Any]
    report_path: str | None
    timestamp: datetime


class CacheStats(BaseModel):
    """Counters of one LRU cache (CacheService.get_stats)"""

    size: int
    max_size: int
    utilization_percent: float
    hit_rate_percent: float
    total_requests: int
    hits: int
    misses: int
    evictions: int
    expired_entries: int


class AdminCacheStats(CacheStats):
    """Cache counters plus the `utilization` key read by the admin frontend"""

    utilization: float


class CacheGlobalStats(BaseModel):
    """Totals over the main and chat caches"""

    total_requests: int
    hit_ratio: float
    total_hits: int
    total_misses: int


class CacheStatsResponse(BaseModel):
    """Statistics of every cache service"""

    main_cache: AdminCacheStats
    chat_cache: AdminCacheStats
    global_stats: CacheGlobalStats
    timestamp: datetime


class ApplicationConfig(BaseModel):
    """Read-only application settings (secrets masked)"""

    api_version: str
    max_chunk_size: int
    chunk_overlap: int
    embedding_dimension: int
    supported_file_extensions: list[str]
    max_file_size_mb: int
    jwt_expiration_hours: int
    mistral_api_key: str
    mistral_model: str
    mistral_embedding_model: str


class AdminConfigurationResponse(BaseModel):
    """Dynamic (database) and static (settings) configuration, secrets masked"""

    database_config: dict[str, str]
    application_config: ApplicationConfig
    timestamp: datetime


class AuditLogEntry(BaseModel):
    """One audit log row as listed in the admin audit view"""

    id: int
    timestamp: datetime
    user_type: str
    action: str
    details: str | None
    ip_address: str | None
    success: bool


class AuditLogFilters(BaseModel):
    """Filters applied to an audit log listing"""

    action: str | None
    user_type: str | None
    success: bool | None
    days_back: int


class AuditLogPage(BaseModel):
    """A page of audit log entries"""

    entries: list[AuditLogEntry]
    total: int
    offset: int
    limit: int
    has_more: bool
    filters: AuditLogFilters
    timestamp: datetime


class ModelUsageToday(BaseModel):
    """Today's LLM usage of one model"""

    model: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_eur: float


class DailyModelUsage(BaseModel):
    """LLM usage of one model on one day"""

    date: str
    model: str
    calls: int
    tokens: int
    cost_eur: float


class UsageResponse(BaseModel):
    """LLM spend for the admin cost dashboard"""

    today_by_model: list[ModelUsageToday]
    history: list[DailyModelUsage]
    spent_today_eur: float
    daily_budget_eur: float
    timestamp: datetime


# Validation utilities


def validate_filename(filename: str) -> bool:
    """Reject paths, control and shell-special characters, and empty or long names."""
    if os.path.isabs(filename) or ".." in filename:
        return False
    if re.search(r'[<>:"|?*\x00-\x1f]', filename):
        return False
    return 0 < len(filename) <= 255


def sanitize_filename(filename: str) -> str:
    """Normalize the name, replace dangerous characters and cap its length at 255."""
    filename = unicodedata.normalize("NFKD", filename)
    filename = re.sub(r'[<>:"|?*\x00-\x1f]', "_", filename).strip()
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[: 255 - len(ext)] + ext
    return filename
