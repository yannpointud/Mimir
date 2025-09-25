"""
FastAPI dependency injection for services.

This module provides dependency injection functions for accessing
various services throughout the API endpoints.
"""

from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session

from src.database.connection import get_db_session
from src.database.repository import DocumentRepository, ConfigurationRepository, AuditLogRepository
from src.cache.lru_cache import cache_service, chat_cache_service
from src.email_service.smtp_client import email_service
from src.auth.jwt_handler import jwt_handler
from src.config import settings
from src.llm_interface.implementations.mistral_api import MistralAPIService
from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.monitoring.rag_debug_logger import rag_debug_service


def get_document_repository(db: Session = Depends(get_db_session)) -> DocumentRepository:
    """Get document repository instance."""
    return DocumentRepository(db)


def get_configuration_repository(db: Session = Depends(get_db_session)) -> ConfigurationRepository:
    """Get configuration repository instance."""
    return ConfigurationRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db_session)) -> AuditLogRepository:
    """Get audit log repository instance."""
    return AuditLogRepository(db)


def get_cache_service():
    """Get cache service instance."""
    return cache_service


def get_chat_cache_service():
    """Get chat cache service instance."""
    return chat_cache_service


def get_email_service():
    """Get email service instance."""
    return email_service


def get_jwt_handler():
    """Get JWT handler instance."""
    return jwt_handler


# Global service instances (singleton pattern)
_llm_service = None
_vector_store = None
_ingestion_processor = None


def get_llm_service() -> MistralAPIService:
    """Get LLM service instance (singleton)."""
    global _llm_service
    if _llm_service is None:
        _llm_service = MistralAPIService(
            api_key=settings.mistral_api_key,
            model=settings.mistral_model,
            embedding_model=settings.mistral_embedding_model,
            max_retries=3,
            retry_delay=1.0
        )
    return _llm_service


def get_vector_store() -> FaissVectorStore:
    """Get vector store instance (singleton)."""
    global _vector_store
    if _vector_store is None:
        _vector_store = FaissVectorStore(
            dimension=settings.embedding_dimension,
            index_path=settings.faiss_index_path,
            metadata_path=settings.faiss_metadata_path,
            similarity_threshold=settings.similarity_threshold,
            index_type="FlatL2"
        )
    return _vector_store


def get_ingestion_processor():
    """Get ingestion processor instance (singleton)."""
    global _ingestion_processor
    if _ingestion_processor is None:
        raise RuntimeError("Ingestion processor not initialized. Application startup may have failed.")
    return _ingestion_processor


def set_ingestion_processor(processor):
    """Set the ingestion processor instance (called by main.py at startup)."""
    global _ingestion_processor
    _ingestion_processor = processor


def get_rag_debug_service():
    """Get RAG debug service instance."""
    # Configure the service from settings on first call
    rag_debug_service.configure(
        enabled=settings.rag_debug_enabled,
        log_prompts=settings.rag_debug_log_prompts,
        log_context=settings.rag_debug_log_context,
        log_responses=settings.rag_debug_log_responses
    )
    return rag_debug_service