"""
FastAPI dependency injection for services.

This module provides dependency injection functions for accessing
various services throughout the API endpoints.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from mimir.database.connection import get_db_session
from mimir.database.repository import (
    DocumentRepository,
    ConfigurationRepository,
    AuditLogRepository,
    UsageRepository,
)
from mimir.cache.lru_cache import cache_service, chat_cache_service
from mimir.email_service.smtp_client import email_service
from mimir.auth.jwt_handler import jwt_handler
from mimir.cost.budget_guard import budget_guard, BudgetGuard
from mimir.cost.usage_tracker import usage_tracker, UsageTracker
from mimir.config import settings
from mimir.llm_interface.implementations.mistral_api import MistralAPIService
from mimir.rag_core.implementations.faiss_store import FaissVectorStore
from mimir.rag_core.implementations.bm25_store import Bm25LexicalStore
from mimir.monitoring.rag_debug_logger import rag_debug_service
from mimir.services.rag_service import RagService
from mimir.monitoring.logger import setup_logger

logger = setup_logger(__name__)


def get_document_repository(db: Session = Depends(get_db_session)) -> DocumentRepository:
    return DocumentRepository(db)


def get_configuration_repository(db: Session = Depends(get_db_session)) -> ConfigurationRepository:
    return ConfigurationRepository(db)


def get_audit_log_repository(db: Session = Depends(get_db_session)) -> AuditLogRepository:
    return AuditLogRepository(db)


def get_usage_repository(db: Session = Depends(get_db_session)) -> UsageRepository:
    return UsageRepository(db)


def get_cache_service():
    return cache_service


def get_chat_cache_service():
    return chat_cache_service


def get_email_service():
    return email_service


def get_jwt_handler():
    return jwt_handler


def get_budget_guard() -> BudgetGuard:
    return budget_guard


def get_usage_tracker() -> UsageTracker:
    return usage_tracker


# Global service instances (singleton pattern)
_llm_service = None
_vector_store = None
_ingestion_processor = None


def get_llm_service() -> MistralAPIService:
    global _llm_service
    if _llm_service is None:
        _llm_service = MistralAPIService(
            api_key=settings.mistral_api_key,
            model=settings.mistral_model,
            embedding_model=settings.mistral_embedding_model,
            max_retries=3,
            retry_delay=1.0,
        )
    return _llm_service


def get_vector_store() -> FaissVectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = FaissVectorStore(
            dimension=settings.embedding_dimension,
            index_path=settings.faiss_index_path,
            metadata_path=settings.faiss_metadata_path,
            similarity_threshold=settings.similarity_threshold,
            index_type="FlatL2",
        )
    return _vector_store


# BM25 lexical store singleton (mirrors _vector_store above). Only consumed by
# the hybrid retrieval path, which is gated behind settings.hybrid_search_enabled.
_bm25_store = None


def get_bm25_store() -> Bm25LexicalStore:
    """Get BM25 lexical store instance (singleton).

    Built once and, like get_vector_store(), loads any index already persisted on
    disk (staying empty if none exists yet). Used by the hybrid retrieval branch
    of RagService; the dense-only path never touches it.
    """
    global _bm25_store
    if _bm25_store is None:
        _bm25_store = Bm25LexicalStore(index_path=settings.bm25_index_path)
        try:
            _bm25_store.load()
        except Exception as e:  # noqa: BLE001 - startup boundary: never fail on a bad/missing index
            logger.warning(f"BM25 lexical index failed to load, starting empty: {e}")
    return _bm25_store


def get_ingestion_processor():
    global _ingestion_processor
    if _ingestion_processor is None:
        raise RuntimeError(
            "Ingestion processor not initialized. Application startup may have failed."
        )
    return _ingestion_processor


def set_ingestion_processor(processor):
    """Set the ingestion processor instance (called by main.py at startup)."""
    global _ingestion_processor
    _ingestion_processor = processor


def get_rag_debug_service():
    # Configure the service from settings on first call
    rag_debug_service.configure(
        enabled=settings.rag_debug_enabled,
        log_prompts=settings.rag_debug_log_prompts,
        log_context=settings.rag_debug_log_context,
        log_responses=settings.rag_debug_log_responses,
    )
    return rag_debug_service


# Global service instance (singleton pattern, mirrors _llm_service/_vector_store above)
_rag_service = None


def get_rag_service() -> RagService:
    """Get RagService instance (singleton).

    HTTP-agnostic: RagService imports nothing from FastAPI and is safe to
    call directly outside a request context -- notably by the RAGAS
    evaluation harness. document_repository is deliberately NOT baked in
    here (it is request-scoped, see get_document_repository()); it stays a
    per-call argument to RagService.answer()/answer_stream().
    """
    global _rag_service
    if _rag_service is None:
        _rag_service = RagService(
            llm_service=get_llm_service(),
            vector_store=get_vector_store(),
            rag_debug=get_rag_debug_service(),
            budget_guard=get_budget_guard(),
            usage_tracker=get_usage_tracker(),
            chat_cache=get_chat_cache_service(),
            bm25_store=get_bm25_store(),
        )
    return _rag_service
