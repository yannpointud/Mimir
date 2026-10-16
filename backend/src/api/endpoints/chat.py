"""
Chat endpoints for RAG-based conversations.

This module provides the main chat endpoint for user questions
and responses based on document context.
"""

from typing import Any
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from datetime import datetime
import asyncio
import logging
import hashlib

from src.auth.middleware import get_optional_user
from src.api.middleware.rate_limit import limiter, get_client_identifier
from src.api.responses import budget_exceeded_response
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

# RAG pipeline lives in src.services.rag_service and the SSE stream in
# src.services.chat_stream: the route stays HTTP-pure (parse + budget gate +
# response). rag_service is imported as a module (not `from ... import
# RagService`) so no pipeline symbol is re-exported from this module's
# namespace; only the RagService type hint on the injected dependency remains.
from src.services import rag_service as rag_service_module
from src.services.chat_stream import (
    SSE_HEADERS,
    ChatQuestion,
    ChatStream,
    ReservationSettlement,
)

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
    question: str = Field(..., min_length=1, max_length=1000, description="User question")
    session_id: str | None = Field(None, description="Optional session ID for tracking")
    context_limit: int | None = Field(5, ge=1, le=10, description="Maximum context documents")
    include_sources: bool = Field(True, description="Whether to include source references")


class SourceReference(BaseModel):
    document_id: str
    filename: str
    chunk_text: str
    similarity_score: float
    chunk_index: int
    total_chunks: int


class ChatResponse(BaseModel):
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
    """Process user question with streaming response (Server-Sent Events)."""
    # Budget gate BEFORE the StreamingResponse is returned: once it is, the
    # client already has an implicit 200, so a real 429 is only possible here
    # (never move this check into the stream). Returned rather than raised so
    # slowapi adds its rate-limit headers. reserve() is a blocking SQLite
    # write, kept off the event loop.
    reservation: BudgetReservation | None = await asyncio.to_thread(budget_guard.reserve, "chat")
    if reservation is None:
        return budget_exceeded_response()

    settlement = ReservationSettlement(budget_guard, reservation)
    stream = ChatStream(
        rag_service=rag_service,
        chat_cache=chat_cache,
        document_repository=document_repository,
        rag_debug=rag_debug,
    )
    question = ChatQuestion(
        question=chat_request.question,
        session_id=chat_request.session_id,
        context_limit=chat_request.context_limit,
        include_sources=chat_request.include_sources,
        client_ip=_get_client_ip(request),
        current_user=current_user,
    )
    # The background task releases the reservation if the stream is never
    # iterated (client gone before the first byte); a no-op otherwise.
    return StreamingResponse(
        stream.events(question, settlement),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
        background=BackgroundTask(settlement.release_if_unsettled),
    )


@router.post("/escalate", response_model=EscalationResponse)
async def escalate_to_human(
    request: Request,
    escalation_request: EscalationRequest,
    current_user: dict[str, Any] | None = Depends(get_optional_user),
    email_service: EmailService = Depends(get_email_service),
) -> EscalationResponse:
    """Escalate conversation to human operator."""
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

    except Exception as e:  # noqa: BLE001 - API boundary: any failure becomes a failed escalation
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
    """Get chat history for a session."""
    return {"session_id": session_id, "messages": [], "created_at": datetime.utcnow()}


@router.delete("/sessions/{session_id}")
async def clear_session_history(
    session_id: str, current_user: dict[str, Any] | None = Depends(get_optional_user)
) -> BaseResponse:
    """Clear chat history for a session."""
    return BaseResponse(
        success=True, message=f"Session {session_id} history cleared", timestamp=datetime.utcnow()
    )


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    return request.client.host if request.client else "unknown"


def _generate_cache_key(question: str) -> str:
    return hashlib.md5(question.lower().strip().encode()).hexdigest()


def _generate_escalation_id() -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_suffix = hashlib.md5(str(datetime.utcnow()).encode()).hexdigest()[:6]
    return f"ESC-{timestamp}-{random_suffix.upper()}"


def _extract_sources_from_history(chat_history: list[dict[str, Any]]) -> list[str]:
    sources = set()

    for message in chat_history:
        if message.get("type") == "assistant" and "sources" in message:
            for source in message.get("sources", []):
                if isinstance(source, dict) and "filename" in source:
                    sources.add(source["filename"])
                elif isinstance(source, str):
                    sources.add(source)

    return list(sources)
