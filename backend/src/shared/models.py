"""
Modèles Pydantic partagés pour validation et sérialisation
Utilisés par les APIs pour garantir la cohérence des données
"""

from pydantic import BaseModel, Field, validator, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    """Énumération des statuts de documents"""
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    ERROR = "error"


class UserType(str, Enum):
    """Types d'utilisateurs pour l'audit"""
    ADMIN = "admin"
    USER = "user"
    SYSTEM = "system"


# Modèles de base

class BaseResponse(BaseModel):
    """Modèle de réponse de base avec timestamps"""
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    success: bool = True
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginationModel(BaseModel):
    """Modèle pour la pagination"""
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    order_by: str = Field(default="created_at")
    desc_order: bool = Field(default=True)


# Modèles Document

class DocumentBase(BaseModel):
    """Modèle de base pour les documents"""
    filename: str = Field(..., min_length=1, max_length=255)
    path: Optional[str] = Field(None, max_length=500)
    preserve: bool = Field(default=False)


class DocumentCreate(DocumentBase):
    """Modèle pour créer un document"""
    file_hash: str = Field(..., min_length=64, max_length=64)
    
    @validator('file_hash')
    def validate_hash(cls, v):
        if not all(c in '0123456789abcdef' for c in v.lower()):
            raise ValueError('Hash must be hexadecimal')
        return v.lower()


class DocumentUpdate(BaseModel):
    """Modèle pour mettre à jour un document"""
    status: Optional[DocumentStatus] = None
    error_message: Optional[str] = Field(None, max_length=1000)
    chunk_count: Optional[int] = Field(None, ge=0)
    preserve: Optional[bool] = None


class DocumentResponse(DocumentBase):
    """Modèle de réponse pour les documents"""
    id: int
    file_hash: str
    status: DocumentStatus
    error_message: Optional[str] = None
    chunk_count: int
    created_at: datetime
    indexed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True  # Pour SQLAlchemy compatibility


class ChunkResponse(BaseModel):
    """Modèle de réponse pour les chunks de document"""
    id: int
    document_id: int
    chunk_index: int
    text: str
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class DocumentWithChunksResponse(DocumentBase):
    """Modèle de réponse pour un document avec ses chunks"""
    id: int
    file_hash: str
    status: DocumentStatus
    error_message: Optional[str] = None
    chunk_count: int
    created_at: datetime
    indexed_at: Optional[datetime] = None
    chunks: List[ChunkResponse] = []
    content: Optional[str] = None  # Contenu original si disponible
    file_size: Optional[int] = None
    mime_type: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentListResponse(BaseResponse):
    """Réponse pour la liste des documents"""
    documents: List[DocumentResponse]
    total_count: int
    pagination: Dict[str, Any]


class DocumentStatsResponse(BaseResponse):
    """Réponse pour les statistiques des documents"""
    stats: Dict[str, Any]


# Modèles Configuration

class ConfigurationBase(BaseModel):
    """Modèle de base pour la configuration"""
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=0)


class ConfigurationCreate(ConfigurationBase):
    """Modèle pour créer une configuration"""
    pass


class ConfigurationUpdate(BaseModel):
    """Modèle pour mettre à jour une configuration"""
    value: str = Field(..., min_length=0)


class ConfigurationResponse(ConfigurationBase):
    """Modèle de réponse pour les configurations"""
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ConfigurationListResponse(BaseResponse):
    """Réponse pour la liste des configurations"""
    configurations: List[ConfigurationResponse]


# Modèles Audit

class AuditLogBase(BaseModel):
    """Modèle de base pour les logs d'audit"""
    user_type: UserType
    action: str = Field(..., min_length=1, max_length=100)
    details: Optional[str] = Field(None, max_length=1000)
    ip_address: Optional[str] = Field(None, max_length=45)
    user_agent: Optional[str] = None
    success: bool = True


class AuditLogCreate(AuditLogBase):
    """Modèle pour créer un log d'audit"""
    pass


class AuditLogResponse(AuditLogBase):
    """Modèle de réponse pour les logs d'audit"""
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class AuditLogListResponse(BaseResponse):
    """Réponse pour la liste des logs d'audit"""
    logs: List[AuditLogResponse]
    total_count: int


# Modèles pour les futures fonctionnalités (prêts pour Jalon 2-3)

class HealthCheckResponse(BaseResponse):
    """Réponse des health checks"""
    status: str = Field(default="healthy")
    checks: Dict[str, Any] = Field(default_factory=dict)
    uptime_seconds: Optional[float] = None
    version: Optional[str] = None


class ErrorResponse(BaseModel):
    """Modèle de réponse d'erreur standardisé"""
    success: bool = False
    error_code: str
    error_message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Modèles de validation spécialisés

class FileUploadValidation(BaseModel):
    """Validation pour les uploads de fichiers"""
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
    """Statistiques de la base de données"""
    table_counts: Dict[str, int]
    database_size_mb: Optional[float] = None
    last_backup: Optional[datetime] = None


# Utilitaires de validation

def validate_filename(filename: str) -> bool:
    """Valide un nom de fichier pour la sécurité"""
    import os
    import re
    
    # Pas de chemins relatifs ou absolus
    if os.path.isabs(filename) or '..' in filename:
        return False
    
    # Pas de caractères dangereux
    dangerous_chars = r'[<>:"|?*\x00-\x1f]'
    if re.search(dangerous_chars, filename):
        return False
    
    # Longueur raisonnable
    if len(filename) == 0 or len(filename) > 255:
        return False
    
    return True


def sanitize_filename(filename: str) -> str:
    """Assainit un nom de fichier"""
    import re
    import unicodedata
    
    # Normalise Unicode
    filename = unicodedata.normalize('NFKD', filename)
    
    # Remplace les caractères dangereux
    filename = re.sub(r'[<>:"|?*\x00-\x1f]', '_', filename)
    
    # Supprime les espaces en début/fin
    filename = filename.strip()
    
    # Limite la longueur
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    
    return filename


# Configuration des modèles Pydantic

class Config:
    """Configuration globale pour tous les modèles"""
    # Permet l'utilisation avec SQLAlchemy
    from_attributes = True
    
    # Validation stricte
    validate_assignment = True
    
    # Sérialisation JSON des datetime
    json_encoders = {
        datetime: lambda v: v.isoformat()
    }