"""Main FastAPI application for Mimir: entry point with the full configuration."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from mimir.api.dependencies import (
    close_llm_service,
    get_bm25_store,
    get_document_repository,
    get_llm_service,
    get_vector_store,
    set_ingestion_processor,
)

# Import API endpoints
from mimir.api.endpoints import admin, auth, chat, documents, health, logs

# Import middleware
from mimir.api.middleware.cors import configure_cors_middleware
from mimir.api.middleware.rate_limit import configure_rate_limiting
from mimir.api.responses import budget_exceeded_response

# Import services
from mimir.cache.lru_cache import cache_service, chat_cache_service
from mimir.config import settings
from mimir.database.connection import db_manager, init_database
from mimir.database.repository import DocumentRepository
from mimir.email_service.smtp_client import email_service
from mimir.ingestion.chunking import ChunkingConfig
from mimir.ingestion.processor import IngestionProcessor
from mimir.monitoring.alerting import setup_alerting
from mimir.monitoring.logger import setup_logger
from mimir.security.admin_password import resolve_admin_password
from mimir.security.startup_validation import validate_production_secrets
from mimir.shared.errors import BudgetExceeded, ConflictError, MimirError, NotFoundError
from mimir.shared.models import ErrorResponse, RootResponse

# Logging configuration with centralized system
logger = setup_logger("main", level=settings.log_level.upper())

# Global ingestion processor instance
ingestion_processor: IngestionProcessor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager: initialization at startup, cleanup at shutdown."""
    logger.info("Starting Mimir application - API & Services...")
    # The effective admin hash comes from ADMIN_PASSWORD first, so the
    # default-secret checks run against the hash actually used at runtime.
    resolve_admin_password(settings)
    validate_production_secrets(settings)
    init_database()
    _log_services_status()
    setup_alerting()
    await _start_ingestion()
    logger.info("Application startup completed successfully")

    yield

    logger.info("Shutting down Mimir application...")
    cache_service.invalidate_all()
    chat_cache_service.invalidate_all()
    await _stop_ingestion()
    await _close_llm_service()
    logger.info("Application shutdown completed")


def _log_services_status() -> None:
    """Log the cache sizes and whether the email service is configured."""
    cache_stats = cache_service.get_stats()
    chat_cache_stats = chat_cache_service.get_stats()
    logger.info(
        f"Cache services initialized - Main: {cache_stats['max_size']} entries, Chat: {chat_cache_stats['max_size']} entries"
    )

    email_config = email_service.get_configuration_status()
    if email_config["configured"]:
        logger.info("Email service configured and ready")
    else:
        logger.warning("Email service not fully configured - escalation features will be limited")


async def _start_ingestion() -> None:
    """Start the ingestion processor and queue the pending documents."""
    global ingestion_processor
    chunking_config = ChunkingConfig(
        chunk_size=settings.max_chunk_size,
        overlap=settings.chunk_overlap,
        section_title_tracking=settings.structure_aware_chunking_enabled,
    )

    with db_manager.get_session_context() as session:
        document_repo = get_document_repository(session)

        ingestion_processor = IngestionProcessor(
            llm_service=get_llm_service(),
            vector_store=get_vector_store(),
            document_repository=document_repo,
            chunking_config=chunking_config,
            max_file_size_mb=settings.max_file_size_mb,
            max_chunks_per_doc=settings.max_chunks_per_doc,
            bm25_store=get_bm25_store(),
        )
        await ingestion_processor.start()
        logger.info("Ingestion processor started successfully")

        _ensure_bm25_index()

        # Make the processor available to API endpoints
        set_ingestion_processor(ingestion_processor)

        _queue_pending_documents(document_repo, ingestion_processor)


def _ensure_bm25_index() -> None:
    """Rebuild the BM25 index from FAISS when it is missing or unreadable on disk.

    BM25 is derived from the FAISS chunks; without this, every hybrid query
    would degrade to dense-only until the next ingestion.
    """
    bm25_store = get_bm25_store()
    if bm25_store.is_built:
        return
    active_chunks = get_vector_store().snapshot_active_chunks()
    bm25_store.rebuild(active_chunks)
    logger.info(f"BM25 lexical index rebuilt at startup from {len(active_chunks)} active chunks")


def _queue_pending_documents(
    document_repo: DocumentRepository, processor: IngestionProcessor
) -> None:
    """Queue the documents left pending by a previous run."""
    pending_documents = document_repo.get_by_status("pending")
    if not pending_documents:
        return

    logger.info(f"Found {len(pending_documents)} pending documents, queuing for processing")
    for doc in pending_documents:
        if not doc.path or not Path(doc.path).exists():
            logger.warning(f"Document file not found: {doc.path}")
        elif not processor.queue_document(file_path=doc.path, document_id=str(doc.id)):
            logger.warning(f"Ingestion queue full, pending document left for next start: {doc.id}")


async def _stop_ingestion() -> None:
    """Gracefully stop the ingestion processor, if it was started."""
    if not ingestion_processor:
        return
    try:
        success = await ingestion_processor.stop(timeout=10.0)
        if success:
            logger.info("Ingestion processor stopped gracefully")
        else:
            logger.warning("Ingestion processor stop timeout")
    except Exception as e:  # noqa: BLE001 - shutdown boundary: keep releasing the other resources
        logger.error(f"Error stopping ingestion processor: {e}")


async def _close_llm_service() -> None:
    """Close the LLM service's HTTP session to avoid "Event loop is closed"."""
    try:
        await close_llm_service()
    except Exception as e:  # noqa: BLE001 - shutdown boundary: keep releasing the other resources
        logger.error(f"Error closing LLM service: {e}")


# FastAPI application configuration
class MimirAPI(FastAPI):
    """FastAPI application whose OpenAPI schema declares the JWT bearer scheme."""

    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema:
            return self.openapi_schema
        schema = super().openapi()
        schema["components"]["securitySchemes"] = {
            "Bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        }
        return schema


app = MimirAPI(
    title="Mimir",
    description="Chatbot documentaire d'entreprise on-premise - API & Services",
    version=settings.api_version,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url=f"/api/{settings.api_version}/openapi.json",
    lifespan=lifespan,
)


# Middleware configuration

# CORS middleware (advanced configuration)
configure_cors_middleware(app)

# Rate limiting middleware
configure_rate_limiting(app)

# Host Header attack protection. Driven by settings.trusted_hosts (comma-separated)
# so an on-prem operator can lock the allowed Host headers down in production; the
# default "*" preserves the permissive behaviour for local/dev deploys where the
# hostname is not known ahead of time.
_trusted_hosts = [h.strip() for h in settings.trusted_hosts.split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts or ["*"])


# Custom middleware for request logging
@app.middleware("http")
async def request_logging_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Log all HTTP requests with timing and detailed information"""
    start_time = time.time()

    # Client information extraction
    client_ip = request.headers.get(
        "X-Forwarded-For",
        request.headers.get("X-Real-IP", request.client.host if request.client else "unknown"),
    )

    # Log incoming request (less verbose for health checks)
    if not request.url.path.startswith("/health"):
        logger.debug(f"Request: {request.method} {request.url.path} from {client_ip}")

    # Process the request
    response = await call_next(request)

    # Calculate processing time
    process_time = time.time() - start_time

    # Log response (with appropriate level based on status code)
    if response.status_code >= 400:
        logger.warning(
            f"Response: {request.method} {request.url.path} -> {response.status_code} ({process_time:.3f}s)"
        )
    elif not request.url.path.startswith("/health"):
        logger.debug(
            f"Response: {request.method} {request.url.path} -> {response.status_code} ({process_time:.3f}s)"
        )

    # Add monitoring headers
    response.headers["X-Process-Time"] = f"{process_time:.3f}"
    response.headers["X-Request-ID"] = f"req_{int(start_time * 1000000)}"

    return response


def _error_response(
    request: Request, status_code: int, error_code: str, message: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error_code=error_code,
            error_message=message,
            details={"path": str(request.url.path)},
        ).model_dump(mode="json"),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _error_response(request, exc.status_code, f"HTTP_{exc.status_code}", exc.detail)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return _error_response(request, 404, "NOT_FOUND", str(exc))


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return _error_response(request, 409, "CONFLICT", str(exc))


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Unexpected error: logged with its traceback; production hides its text."""
    logger.error(f"Unhandled error on {request.url.path}: {exc}", exc_info=True)
    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error_code="INTERNAL_ERROR", error_message="Internal server error"
            ).model_dump(mode="json"),
        )
    return _error_response(request, 500, "INTERNAL_ERROR", str(exc))


@app.exception_handler(BudgetExceeded)
async def budget_exceeded_handler(request: Request, exc: BudgetExceeded) -> JSONResponse:
    """Daily AI budget exhausted: the same 429 as the chat route."""
    logger.warning(f"Daily budget exceeded on {request.url.path}: {exc}")
    return budget_exceeded_response()


@app.exception_handler(MimirError)
async def domain_error_handler(request: Request, exc: MimirError) -> JSONResponse:
    """Domain error escaping a route: the same 500 payload as an unexpected error."""
    return await general_exception_handler(request, exc)


# Base routes


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    """Main API entry point"""
    return RootResponse(
        name="Mimir",
        description="Chatbot documentaire d'entreprise",
        version=settings.api_version,
        status="running",
        docs_url="/docs" if not settings.is_production else None,
    )


# API endpoints registration
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(documents.reader_router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")


# Development entry point
if __name__ == "__main__":
    logger.info(f"Starting Mimir in development mode on {settings.api_host}:{settings.api_port}")

    uvicorn.run(
        "mimir.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,  # Hot reload in development
        log_level=settings.log_level.lower(),
        access_log=True,
    )
