"""
Chat endpoints for RAG-based conversations.

This module provides the main chat endpoint for user questions
and responses based on document context.
"""

from typing import Any
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from datetime import datetime
import asyncio
import logging
import hashlib
import json
import numpy as np

from src.auth.middleware import get_optional_user
from src.api.middleware.rate_limit import limiter, get_client_identifier
from src.cache.lru_cache import ChatCacheService
from src.email_service.smtp_client import EmailService
from src.api.dependencies import (
    get_chat_cache_service,
    get_email_service,
    get_document_repository,
    get_rag_debug_service,
    get_budget_guard,
    get_rag_service,
)
from src.database.repository import DocumentRepository
from src.shared.models import BaseResponse
from src.monitoring.rag_debug_logger import RagDebugService
from src.cost.budget_guard import BudgetGuard, BudgetReservation
from src.config import settings

# RAG pipeline lives in src.services.rag_service: the stream route
# delegates to RagService.answer_stream() via Depends(get_rag_service); the
# route itself stays HTTP-pure (parse + budget gate + cache read + format).
# Imported as a module (not `from ... import RagService`) so no pipeline symbol
# is re-exported from this module's namespace -- the former re-import shims are
# fully gone; only the RagService type hint on the injected dependency remains.
from src.services import rag_service as rag_service_module

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    responses={
        400: {"description": "Bad request"},
        500: {"description": "Internal server error"},
    },
)


class ChatRequest(BaseModel):
    """Request model for chat questions."""

    question: str = Field(..., min_length=1, max_length=1000, description="User question")
    session_id: str | None = Field(None, description="Optional session ID for tracking")
    context_limit: int | None = Field(5, ge=1, le=10, description="Maximum context documents")
    include_sources: bool = Field(True, description="Whether to include source references")


class SourceReference(BaseModel):
    """Model for document source references."""

    document_id: str
    filename: str
    chunk_text: str
    similarity_score: float
    chunk_index: int
    total_chunks: int


class ChatResponse(BaseModel):
    """Response model for chat answers."""

    answer: str
    sources: list[SourceReference] = []
    confidence_score: float = Field(ge=0.0, le=1.0)
    session_id: str
    response_time_ms: int
    cached: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EscalationRequest(BaseModel):
    """Request model for escalating chat to human."""

    question: str
    session_id: str | None = None
    chat_history: list[dict[str, Any]] = []
    user_email: str | None = None
    additional_context: str | None = None


class EscalationResponse(BaseModel):
    """Response model for escalation requests."""

    success: bool
    message: str
    escalation_id: str | None = None


@router.post("/stream")
# Rate limit per JWT user with IP fallback: behind the nginx reverse
# proxy the source IP will be the proxy's, so the JWT key is the only reliable
# identity for authenticated routes. The limit check runs BEFORE the endpoint
# body, so a 429 is raised before any SSE byte is streamed; a stream under the
# limit passes through untouched (StreamingResponse is a Response subclass,
# no `response` param needed).
@limiter.limit(
    lambda: f"{settings.rate_limit_chat_per_minute}/minute", key_func=get_client_identifier
)
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    current_user: dict[str, Any] | None = Depends(get_optional_user),
    chat_cache: ChatCacheService = Depends(get_chat_cache_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    rag_debug: RagDebugService = Depends(get_rag_debug_service),
    budget_guard: BudgetGuard = Depends(get_budget_guard),
    rag_service: rag_service_module.RagService = Depends(get_rag_service),
):
    """
    Process user question with streaming response.
    Returns Server-Sent Events (SSE) stream.
    """

    # Budget gate in the SYNCHRONOUS body, BEFORE StreamingResponse is
    # constructed/returned: once StreamingResponse is returned
    # the client already has an implicit 200, so a real 429 is only possible
    # here. Do NOT move this check inside generate_sse -- that would yield a
    # 200 with an SSE error event instead of a genuine HTTP 429.
    #
    # JSONResponse (not `raise HTTPException`): main.py's global HTTPException
    # handler would rewrite the body to the generic "HTTP_429" shape (or crash
    # outright on a dict detail), defeating the distinct budget_exceeded
    # error_code -- returning a Response instance bypasses that handler and the
    # response_model machinery entirely, exactly like the slowapi 429 handler.
    #
    # asyncio.to_thread: reserve() is a blocking SQLite write -- keep it off
    # the event loop.
    reservation: BudgetReservation | None = await asyncio.to_thread(budget_guard.reserve, "chat")
    if reservation is None:
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "budget_exceeded",
                "error_message": "Plafond quotidien de dépense IA atteint.",
            },
        )

    # Idempotent settle guard shared between generate_sse() below and the
    # StreamingResponse background task. An async generator that is never
    # iterated -- client disconnected before Starlette starts streaming, or
    # the initial response send failed -- never executes its body nor its
    # finally blocks, so settlement logic living only inside generate_sse()
    # cannot cover that case: the reservation would stay charged until the
    # next daily reset.
    settle_state = {"settled": False}

    def _release_if_unsettled():
        """Release the reservation exactly once if no other path settled it.

        Runs as the StreamingResponse background task (after the response
        completes or the client disconnects) and as generate_sse's own
        finally fallback; the shared flag makes both call sites idempotent.
        Sync on purpose: Starlette runs sync background tasks in a
        threadpool, so the blocking SQLite write never blocks the loop.
        """
        if not settle_state["settled"]:
            settle_state["settled"] = True
            budget_guard.release(reservation)

    def convert_numpy_types(obj):
        """Recursively convert numpy types to native Python types."""
        if isinstance(obj, dict):
            return {k: convert_numpy_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_numpy_types(item) for item in obj]
        elif isinstance(obj, (np.integer, np.int32, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return obj

    async def generate_sse():
        start_time = datetime.utcnow()
        client_ip = _get_client_ip(request)

        try:
            session_id = chat_request.session_id or _generate_session_id(
                chat_request.question, client_ip
            )

            # Send start event
            yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"

            rag_debug.log_user_request(
                session_id=session_id,
                question=chat_request.question,
                user_context={
                    "client_ip": client_ip,
                    "user_type": current_user.get("user_type") if current_user else "anonymous",
                    "streaming": True,
                },
                context_limit=chat_request.context_limit,
            )

            # Snapshot the corpus version BEFORE consulting the cache: it is
            # part of the server-derived cache key, so any ingestion/deletion
            # (which bumps FaissVectorStore.last_updated) implicitly
            # invalidates all prior entries. The vector store lives inside the
            # injected RagService (the route does not depend on it directly).
            corpus_version = rag_service.vector_store.get_corpus_version()

            # Check the corpus-aware SSE cache
            cached_response = chat_cache.get_stream_response(chat_request.question, corpus_version)

            if cached_response:
                # No LLM call happens on a cache hit: release the reservation
                # so the daily ledger is not charged for work never done.
                # Mark settled BEFORE releasing so no other path can
                # double-settle even if release itself raises.
                settle_state["settled"] = True
                await asyncio.to_thread(budget_guard.release, reservation)
                yield f"data: {json.dumps({'type': 'chunk', 'content': cached_response['answer']})}\n\n"
                # Replay the citation event before done so a cache hit is
                # byte-for-byte indistinguishable from a fresh stream:
                # the live pipeline yields chunk -> citation -> done, and the
                # frontend must receive its [N] -> source map on hits too.
                yield f"data: {json.dumps({'type': 'citation', 'citations': cached_response.get('citations', {})})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'sources': cached_response.get('sources', []), 'confidence_score': cached_response.get('confidence_score', 0.0), 'cached': True})}\n\n"
                return

            # Delegate to the RAG service stream. RagService.answer_stream()
            # always settles the reservation internally in its outer finally
            # (finalize on success/partial usage, release if no LLM call was
            # made) before the generator finishes, including on a mid-stream
            # disconnect. It also writes the corpus-aware SSE cache after a
            # successful done event (passing corpus_version below). The
            # llm_service / vector_store / usage_tracker collaborators live
            # inside the injected RagService.
            settle_state["settled"] = True
            async for event in rag_service.answer_stream(
                question=chat_request.question,
                context_limit=chat_request.context_limit,
                include_sources=chat_request.include_sources,
                session_id=session_id,
                document_repository=document_repository,
                reservation=reservation,
                corpus_version=corpus_version,
            ):
                # Convert all numpy types before serialization
                event = convert_numpy_types(event)
                yield f"data: {json.dumps(event)}\n\n"

            end_time = datetime.utcnow()
            response_time_ms = int((end_time - start_time).total_seconds() * 1000)
            logger.info(f"Streaming completed - session: {session_id}, time: {response_time_ms}ms")

        except Exception as e:  # noqa: BLE001
            logger.error(f"Streaming error: {type(e).__name__} - {str(e)}")
            # Never leak raw exception details to the client (info disclosure);
            # the full error is kept in the server logs above.
            yield f"data: {json.dumps({'type': 'error', 'message': 'Une erreur interne est survenue.'})}\n\n"

        finally:
            # Settle-once fallback: covers GeneratorExit (client disconnect
            # at a yield point) and asyncio.CancelledError, neither of which
            # the `except Exception` above catches. No-op when the cache-hit
            # branch or the RAG stream pipeline already settled the
            # reservation. Awaiting (no yield) inside an async generator's
            # finally is legal during aclose(); asyncio.to_thread keeps the
            # blocking SQLite write off the event loop.
            if not settle_state["settled"]:
                settle_state["settled"] = True
                await asyncio.to_thread(budget_guard.release, reservation)

    # background=BackgroundTask(...) is the never-iterated-generator guard:
    # if the client disconnects before Starlette pulls the first SSE byte
    # (or the initial response send fails), generate_sse()'s body/finally
    # never run -- Starlette still runs the background task after the
    # response terminates, which then releases the orphaned reservation.
    # The shared settled flag keeps it a no-op in every normal case.
    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
        background=BackgroundTask(_release_if_unsettled),
    )


@router.post("/escalate", response_model=EscalationResponse)
async def escalate_to_human(
    request: Request,
    escalation_request: EscalationRequest,
    current_user: dict[str, Any] | None = Depends(get_optional_user),
    email_service: EmailService = Depends(get_email_service),
) -> EscalationResponse:
    """
    Escalate conversation to human operator.

    Args:
        request: FastAPI request object
        escalation_request: Escalation details
        current_user: Optional authenticated user
        email_service: Email service for sending escalation

    Returns:
        EscalationResponse: Escalation status and ID
    """
    try:
        client_ip = _get_client_ip(request)
        escalation_id = _generate_escalation_id()

        # Prepare user info
        user_info = {
            "ip_address": client_ip,
            "session_id": escalation_request.session_id,
            "user_email": escalation_request.user_email,
            "user_type": current_user.get("user_type") if current_user else "anonymous",
            "escalation_id": escalation_id,
            "additional_context": escalation_request.additional_context,
        }

        # Extract sources from chat history if available
        context_sources = _extract_sources_from_history(escalation_request.chat_history)

        # Send escalation email
        success = await email_service.send_escalation_email(
            user_question=escalation_request.question,
            chat_history=escalation_request.chat_history,
            user_info=user_info,
            context_sources=context_sources,
        )

        if success:
            logger.info(f"Escalation sent successfully - ID: {escalation_id}")
            return EscalationResponse(
                success=True,
                message="Votre demande a été transmise à notre équipe support. Vous recevrez une réponse dans les plus brefs délais.",
                escalation_id=escalation_id,
            )
        else:
            logger.error(f"Escalation failed - ID: {escalation_id}")
            return EscalationResponse(
                success=False,
                message="Impossible d'envoyer votre demande pour le moment. Veuillez réessayer plus tard.",
                escalation_id=None,
            )

    except Exception as e:  # noqa: BLE001
        logger.error(f"Escalation error: {e}")
        return EscalationResponse(
            success=False,
            message="Une erreur s'est produite lors de l'envoi de votre demande.",
            escalation_id=None,
        )


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str, current_user: dict[str, Any] | None = Depends(get_optional_user)
) -> dict[str, Any]:
    """
    Get chat history for a session.

    Args:
        session_id: Session identifier
        current_user: Optional authenticated user

    Returns:
        dict: Session history
    """
    return {"session_id": session_id, "messages": [], "created_at": datetime.utcnow()}


@router.delete("/sessions/{session_id}")
async def clear_session_history(
    session_id: str, current_user: dict[str, Any] | None = Depends(get_optional_user)
) -> BaseResponse:
    """
    Clear chat history for a session.

    Args:
        session_id: Session identifier
        current_user: Optional authenticated user

    Returns:
        BaseResponse: Operation result
    """
    return BaseResponse(
        success=True, message=f"Session {session_id} history cleared", timestamp=datetime.utcnow()
    )


def _get_client_ip(request: Request) -> str:
    """Extract client IP address from request."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    return request.client.host if request.client else "unknown"


def _generate_session_id(question: str, client_ip: str) -> str:
    """Generate unique session ID based on question and IP."""
    timestamp = datetime.utcnow().isoformat()
    data = f"{question[:50]}:{client_ip}:{timestamp}"
    return hashlib.md5(data.encode()).hexdigest()[:16]


def _generate_cache_key(question: str) -> str:
    """Generate cache key for question."""
    return hashlib.md5(question.lower().strip().encode()).hexdigest()


def _generate_escalation_id() -> str:
    """Generate unique escalation ID."""
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_suffix = hashlib.md5(str(datetime.utcnow()).encode()).hexdigest()[:6]
    return f"ESC-{timestamp}-{random_suffix.upper()}"


def _extract_sources_from_history(chat_history: list[dict[str, Any]]) -> list[str]:
    """Extract source references from chat history."""
    sources = set()

    for message in chat_history:
        if message.get("type") == "assistant" and "sources" in message:
            for source in message.get("sources", []):
                if isinstance(source, dict) and "filename" in source:
                    sources.add(source["filename"])
                elif isinstance(source, str):
                    sources.add(source)

    return list(sources)
