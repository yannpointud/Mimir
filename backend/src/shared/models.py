"""
Shared Pydantic models for validation and serialization
Used by APIs to ensure data consistency
"""

from pydantic import BaseModel, Field, validator, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    """Document status enumeration"""
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
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginationModel(BaseModel):
    """Pagination model"""
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    order_by: str = Field(default="created_at")
    desc_order: bool = Field(default=True)


# Document models

class DocumentBase(BaseModel):
    """Base model for documents"""
    filename: str = Field(..., min_length=1, max_length=255)
    path: Optional[str] = Field(None, max_length=500)
    preserve: bool = Field(default=False)


class DocumentCreate(DocumentBase):
    """Model for creating a document"""
    file_hash: str = Field(..., min_length=64, max_length=64)
    
    @validator('file_hash')
    def validate_hash(cls, v):
        if not all(c in '0123456789abcdef' for c in v.lower()):
            raise ValueError('Hash must be hexadecimal')
        return v.lower()


class DocumentUpdate(BaseModel):
    """Model for updating a document"""
    status: Optional[DocumentStatus] = None
    error_message: Optional[str] = Field(None, max_length=1000)
    chunk_count: Optional[int] = Field(None, ge=0)
    preserve: Optional[bool] = None


class DocumentResponse(DocumentBase):
    """Response model for documents"""
    id: int
    file_hash: str
    status: DocumentStatus
    error_message: Optional[str] = None
    chunk_count: int
    created_at: datetime
    indexed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True  # For SQLAlchemy compatibility


class ChunkResponse(BaseModel):
    """Response model for document chunks"""
    id: int
    document_id: int
    chunk_index: int
    text: str
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class DocumentWithChunksResponse(DocumentBase):
    """Response model for a document with its chunks"""
    id: int
    file_hash: str
    status: DocumentStatus
    error_message: Optional[str] = None
    chunk_count: int
    created_at: datetime
    indexed_at: Optional[datetime] = None
    chunks: List[ChunkResponse] = []
    content: Optional[str] = None  # Original content if available
    file_size: Optional[int] = None
    mime_type: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentListResponse(BaseResponse):
    """Response for the document list"""
    documents: List[DocumentResponse]
    total_count: int
    pagination: Dict[str, Any]


class DocumentStatsResponse(BaseResponse):
    """Response for document statistics"""
    stats: Dict[str, Any]


# Configuration models

class ConfigurationBase(BaseModel):
    """Base model for configuration"""
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=0)


class ConfigurationCreate(ConfigurationBase):
    """Model for creating a configuration"""
    pass


class ConfigurationUpdate(BaseModel):
    """Model for updating a configuration"""
    value: str = Field(..., min_length=0)


class ConfigurationResponse(ConfigurationBase):
    """Response model for configurations"""
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ConfigurationListResponse(BaseResponse):
    """Response for the configuration list"""
    configurations: List[ConfigurationResponse]


# Audit models

class AuditLogBase(BaseModel):
    """Base model for audit logs"""
    user_type: UserType
    action: str = Field(..., min_length=1, max_length=100)
    details: Optional[str] = Field(None, max_length=1000)
    ip_address: Optional[str] = Field(None, max_length=45)
    user_agent: Optional[str] = None
    success: bool = True


class AuditLogCreate(AuditLogBase):
    """Model for creating an audit log"""
    pass


class AuditLogResponse(AuditLogBase):
    """Response model for audit logs"""
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class AuditLogListResponse(BaseResponse):
    """Response for the audit log list"""
    logs: List[AuditLogResponse]
    total_count: int


# Models for future features (ready for Milestone 2-3)

class HealthCheckResponse(BaseResponse):
    """Health check response"""
    status: str = Field(default="healthy")
    checks: Dict[str, Any] = Field(default_factory=dict)
    uptime_seconds: Optional[float] = None
    version: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standardized error response model"""
    success: bool = False
    error_code: str
    error_message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Specialized validation models

class FileUploadValidation(BaseModel):
    """Validation for file uploads"""
    max_size_mb: int = Field(default=100, ge=1, le=1000)
    allowed_extensions: List[str] = Field(
        default=['.pdf', '.docx', '.txt', '.md'],
        min_items=1
    )
    
    @validator('allowed_extensions')
    def validate_extensions(cls, v):
        for ext in v:
            if not ext.startswith('.'):
                raise ValueError('Extensions must start with a dot')
        return [ext.lower() for ext in v]


class DatabaseStatsResponse(BaseResponse):
    """Database statistics"""
    table_counts: Dict[str, int]
    database_size_mb: Optional[float] = None
    last_backup: Optional[datetime] = None


# Validation utilities

def validate_filename(filename: str) -> bool:
    """Validate a filename for security"""
    import os
    import re
    
    # No relative or absolute paths
    if os.path.isabs(filename) or '..' in filename:
        return False
    
    # No dangerous characters
    dangerous_chars = r'[<>:"|?*\x00-\x1f]'
    if re.search(dangerous_chars, filename):
        return False
    
    # Reasonable length
    if len(filename) == 0 or len(filename) > 255:
        return False
    
    return True


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename"""
    import os
    import re
    import unicodedata
    
    # Normalize Unicode
    filename = unicodedata.normalize('NFKD', filename)
    
    # Replace dangerous characters
    filename = re.sub(r'[<>:"|?*\x00-\x1f]', '_', filename)
    
    # Strip leading/trailing whitespace
    filename = filename.strip()
    
    # Limit the length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    
    return filename