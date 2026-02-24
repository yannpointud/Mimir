"""
Main FastAPI application for Mimir
Application entry point with full configuration - Milestone 3: API & Services
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
import uvicorn
import logging
import time
import json
from datetime import datetime
from contextlib import asynccontextmanager

from src.config import settings
from src.database.connection import init_database, db_manager
from src.shared.models import ErrorResponse, HealthCheckResponse

# Import API endpoints
from src.api.endpoints import health, auth, chat, documents, admin, logs

# Import middleware
from src.api.middleware.cors import configure_cors_middleware
from src.api.middleware.rate_limit import configure_rate_limiting

# Import services
from src.cache.lru_cache import cache_service, chat_cache_service
from src.email_service.smtp_client import email_service
from src.monitoring.logger import setup_logger
from src.ingestion.processor import IngestionProcessor
from src.ingestion.chunking import ChunkingConfig
from src.api.dependencies import get_llm_service, get_vector_store, get_document_repository, set_ingestion_processor
from pathlib import Path


# Logging configuration with centralized system
logger = setup_logger("main", level=settings.log_level.upper())

# Global ingestion processor instance
ingestion_processor = None


# Custom JSON encoder to handle datetime objects
class CustomJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=self.json_encoder
        ).encode("utf-8")

    def json_encoder(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager - Milestone 3
    Initialization at startup, cleanup at shutdown
    """
    # Startup
    logger.info("Starting Mimir application - Jalon 3: API & Services...")

    try:
        # Database initialization
        init_database()
        logger.info("Database initialized successfully")

        # Cache services initialization
        cache_stats = cache_service.get_stats()
        chat_cache_stats = chat_cache_service.get_stats()
        logger.info(f"Cache services initialized - Main: {cache_stats['max_size']} entries, Chat: {chat_cache_stats['max_size']} entries")

        # Email service verification
        email_config = email_service.get_configuration_status()
        if email_config["configured"]:
            logger.info("Email service configured and ready")
        else:
            logger.warning("Email service not fully configured - escalation features will be limited")

        # Ingestion services initialization
        global ingestion_processor
        try:
            # Create chunking configuration
            chunking_config = ChunkingConfig(
                chunk_size=settings.max_chunk_size,
                overlap=settings.chunk_overlap
            )

            # Get database session
            from src.database.connection import db_manager
            with db_manager.get_session_context() as session:
                document_repo = get_document_repository(session)

                # Initialize ingestion processor
                ingestion_processor = IngestionProcessor(
                    llm_service=get_llm_service(),
                    vector_store=get_vector_store(),
                    document_repository=document_repo,
                    chunking_config=chunking_config,
                    max_file_size_mb=settings.max_file_size_mb,
                    max_chunks_per_doc=settings.max_chunks_per_doc
                )

                # Start the processor
                await ingestion_processor.start()
                logger.info("Ingestion processor started successfully")

                # Make the processor available to API endpoints
                set_ingestion_processor(ingestion_processor)

                # Process any pending documents
                pending_documents = document_repo.get_by_status('pending')
                if pending_documents:
                    logger.info(f"Found {len(pending_documents)} pending documents, queuing for processing")
                    for doc in pending_documents:
                        if Path(doc.path).exists():
                            ingestion_processor.queue_document(
                                file_path=doc.path,
                                document_id=str(doc.id),
                                preserve=doc.preserve,
                                metadata={}
                            )
                        else:
                            logger.warning(f"Document file not found: {doc.path}")

        except Exception as e:
            logger.error(f"Failed to initialize ingestion processor: {e}")
            # Continue without ingestion processor (non-blocking)

        logger.info("Application startup completed successfully")

    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down Mimir application...")

    try:
        # Cache cleanup
        cache_service.invalidate_all()
        chat_cache_service.invalidate_all()
        logger.info("Cache services cleaned up")

        # Graceful shutdown of ingestion services
        if ingestion_processor:
            try:
                success = await ingestion_processor.stop(timeout=10.0)
                if success:
                    logger.info("Ingestion processor stopped gracefully")
                else:
                    logger.warning("Ingestion processor stop timeout")
            except Exception as e:
                logger.error(f"Error stopping ingestion processor: {e}")

        # Graceful LLM service shutdown to avoid "Event loop is closed"
        try:
            from src.api.dependencies import _llm_service
            if _llm_service is not None:
                await _llm_service.close()
                logger.info("LLM service closed gracefully")
        except Exception as e:
            logger.error(f"Error closing LLM service: {e}")

        logger.info("Application shutdown completed")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


# FastAPI application configuration
app = FastAPI(
    title="Mimir",
    description="Chatbot documentaire d'entreprise on-premise - API & Services",
    version=settings.api_version,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url=f"/api/{settings.api_version}/openapi.json",
    lifespan=lifespan
)


# Middleware configuration - Milestone 3

# CORS middleware (advanced configuration)
configure_cors_middleware(app)

# Rate limiting middleware
configure_rate_limiting(app)

# Host Header attack protection
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "*"] if not settings.is_production else ["*"]
)


# Custom middleware for request logging
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all HTTP requests with timing and detailed information"""
    start_time = time.time()

    # Client information extraction
    client_ip = request.headers.get("X-Forwarded-For",
                                   request.headers.get("X-Real-IP",
                                                     request.client.host if request.client else "unknown"))

    # Log incoming request (less verbose for health checks)
    if not request.url.path.startswith("/health"):
        logger.debug(f"Request: {request.method} {request.url.path} from {client_ip}")

    # Process the request
    response = await call_next(request)

    # Calculate processing time
    process_time = time.time() - start_time

    # Log response (with appropriate level based on status code)
    if response.status_code >= 400:
        logger.warning(f"Response: {request.method} {request.url.path} -> {response.status_code} ({process_time:.3f}s)")
    elif not request.url.path.startswith("/health"):
        logger.debug(f"Response: {request.method} {request.url.path} -> {response.status_code} ({process_time:.3f}s)")

    # Add monitoring headers
    response.headers["X-Process-Time"] = f"{process_time:.3f}"
    response.headers["X-Request-ID"] = f"req_{int(start_time * 1000000)}"

    return response


# Global exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Standardized handler for HTTP errors"""
    return CustomJSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=f"HTTP_{exc.status_code}",
            error_message=exc.detail,
            details={"path": str(request.url.path)}
        ).model_dump()
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handler for business validation errors"""
    logger.warning(f"Validation error on {request.url.path}: {exc}")
    return CustomJSONResponse(
        status_code=400,
        content=ErrorResponse(
            error_code="VALIDATION_ERROR",
            error_message=str(exc),
            details={"path": str(request.url.path)}
        ).model_dump()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handler for unexpected errors"""
    logger.error(f"Unhandled error on {request.url.path}: {exc}", exc_info=True)

    # In production, do not expose internal details
    error_message = "Internal server error" if settings.is_production else str(exc)

    return CustomJSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="INTERNAL_ERROR",
            error_message=error_message,
            details={"path": str(request.url.path)} if not settings.is_production else None
        ).model_dump()
    )


# Base routes

@app.get("/", response_model=dict)
async def root():
    """Main API entry point"""
    return {
        "name": "Mimir",
        "description": "Chatbot documentaire d'entreprise",
        "version": settings.api_version,
        "status": "running",
        "docs_url": f"/docs" if not settings.is_production else None
    }


# API endpoints registration - Milestone 3
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")


# Compatibility route for root health check
@app.get("/health", response_model=HealthCheckResponse)
async def root_health_check():
    """
    Root health check for compatibility
    Delegates to the full Milestone 3 health check
    """
    try:
        # Delegate to the full health check
        from src.api.endpoints.health import health_check
        from src.database.connection import get_db_session

        # Create a session for the health check
        with db_manager.get_session_context() as session:
            return await health_check(db=session)

    except Exception as e:
        logger.error(f"Root health check failed: {e}")
        return CustomJSONResponse(
            status_code=503,
            content={
                "success": False,
                "status": "unhealthy",
                "message": f"Health check failed: {e}",
                "timestamp": time.time()
            }
        )


# Custom OpenAPI configuration
def custom_openapi():
    """OpenAPI configuration with security information"""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security information for API endpoints
    openapi_schema["components"]["securitySchemes"] = {
        "Bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# Development entry point
if __name__ == "__main__":
    logger.info(f"Starting Mimir in development mode on {settings.api_host}:{settings.api_port}")
    
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,  # Hot reload in development
        log_level=settings.log_level.lower(),
        access_log=True
    )