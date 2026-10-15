"""
Shared Pydantic models for validation and serialization
Used by APIs to ensure data consistency
"""

from pydantic import BaseModel, Field, validator, ConfigDict
from typing import Any
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    ERROR = "error"


class UserType(str, Enum):
    """User types for audit logging"""

    ADMIN = "admin"
    USER = "user"
    SYSTEM = "system"


# Base models


class BaseResponse(BaseModel):
    """Base response model with timestamps"""

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    success: bool = True
    message: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginationModel(BaseModel):
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    order_by: str = Field(default="created_at")
    desc_order: bool = Field(default=True)


# Document models


class DocumentBase(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    path: str | None = Field(None, max_length=500)
    preserve: bool = Field(default=False)


class DocumentCreate(DocumentBase):
    file_hash: str = Field(..., min_length=64, max_length=64)

    @validator("file_hash")
    def validate_hash(cls, v):
        if not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError("Hash must be hexadecimal")
        return v.lower()


class DocumentUpdate(BaseModel):
    status: DocumentStatus | None = None
    error_message: str | None = Field(None, max_length=1000)
    chunk_count: int | None = Field(None, ge=0)
    preserve: bool | None = None


class DocumentResponse(DocumentBase):
    id: int
    file_hash: str
    status: DocumentStatus
    error_message: str | None = None
    chunk_count: int
    created_at: datetime
    indexed_at: datetime | None = None

    class Config:
        from_attributes = True  # For SQLAlchemy compatibility


class ChunkResponse(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    text: str
    metadata: dict[str, Any] | None = None

    class Config:
        from_attributes = True


class DocumentWithChunksResponse(DocumentBase):
    id: int
    file_hash: str
    status: DocumentStatus
    error_message: str | None = None
    chunk_count: int
    created_at: datetime
    indexed_at: datetime | None = None
    chunks: list[ChunkResponse] = []
    content: str | None = None  # Original content if available
    file_size: int | None = None
    mime_type: str | None = None

    class Config:
        from_attributes = True


class DocumentListResponse(BaseResponse):
    documents: list[DocumentResponse]
    total_count: int
    pagination: dict[str, Any]


class DocumentStatsResponse(BaseResponse):
    stats: dict[str, Any]


# Configuration models


class ConfigurationBase(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=0)


class ConfigurationCreate(ConfigurationBase):
    pass


class ConfigurationUpdate(BaseModel):
    value: str = Field(..., min_length=0)


class ConfigurationResponse(ConfigurationBase):
    updated_at: datetime

    class Config:
        from_attributes = True


class ConfigurationListResponse(BaseResponse):
    configurations: list[ConfigurationResponse]


# Audit models


class AuditLogBase(BaseModel):
    user_type: UserType
    action: str = Field(..., min_length=1, max_length=100)
    details: str | None = Field(None, max_length=1000)
    ip_address: str | None = Field(None, max_length=45)
    user_agent: str | None = None
    success: bool = True


class AuditLogCreate(AuditLogBase):
    pass


class AuditLogResponse(AuditLogBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseResponse):
    logs: list[AuditLogResponse]
    total_count: int


# Models for future features (ready for Milestone 2-3)


class HealthCheckResponse(BaseResponse):
    status: str = Field(default="healthy")
    checks: dict[str, Any] = Field(default_factory=dict)
    uptime_seconds: float | None = None
    version: str | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    error_message: str
    details: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Specialized validation models


class FileUploadValidation(BaseModel):
    max_size_mb: int = Field(default=100, ge=1, le=1000)
    allowed_extensions: list[str] = Field(default=[".pdf", ".docx", ".txt", ".md"], min_length=1)

    @validator("allowed_extensions")
    def validate_extensions(cls, v):
        for ext in v:
            if not ext.startswith("."):
                raise ValueError("Extensions must start with a dot")
        return [ext.lower() for ext in v]


class DatabaseStatsResponse(BaseResponse):
    table_counts: dict[str, int]
    database_size_mb: float | None = None
    last_backup: datetime | None = None


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
    cache_max_size: int
    cache_ttl_seconds: int
    supported_file_extensions: list[str]
    max_file_size_mb: int
    jwt_expiration_hours: int
    llm_provider: str
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
    additional_data: dict[str, Any] | None


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


class AdminDocumentSummary(BaseModel):
    """Document row of the admin document list"""

    id: int
    filename: str
    status: str
    created_at: str | None
    file_size: int
    preserve: bool


class AdminDocumentList(BaseModel):
    """A page of the admin document list"""

    documents: list[AdminDocumentSummary]
    total: int
    page: int
    limit: int
    total_pages: int


class AdminDocumentStats(BaseModel):
    """Document statistics of the admin dashboard"""

    total_documents: int
    by_status: DocumentStatusCounts
    by_type: dict[str, Any]
    total_size_mb: int | float
    timestamp: datetime


class UploadedDocument(BaseModel):
    """Document created by an admin upload"""

    id: int
    filename: str
    status: str
    created_at: str | None


class AdminUploadResponse(BaseModel):
    """Result of an admin upload"""

    success: bool
    message: str
    document: UploadedDocument
    timestamp: datetime


# Validation utilities


def validate_filename(filename: str) -> bool:
    """Validate a filename for security"""
    import os
    import re

    # No relative or absolute paths
    if os.path.isabs(filename) or ".." in filename:
        return False

    # No dangerous characters
    dangerous_chars = r'[<>:"|?*\x00-\x1f]'
    if re.search(dangerous_chars, filename):
        return False

    # Reasonable length
    return 0 < len(filename) <= 255


def sanitize_filename(filename: str) -> str:
    import os
    import re
    import unicodedata

    # Normalize Unicode
    filename = unicodedata.normalize("NFKD", filename)

    # Replace dangerous characters
    filename = re.sub(r'[<>:"|?*\x00-\x1f]', "_", filename)

    # Strip leading/trailing whitespace
    filename = filename.strip()

    # Limit the length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[: 255 - len(ext)] + ext

    return filename
