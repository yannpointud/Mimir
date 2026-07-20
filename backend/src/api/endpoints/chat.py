"""
Chat endpoints for RAG-based conversations.

This module provides the main chat endpoint for user questions
and responses based on document context.
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
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
from src.api.dependencies import get_chat_cache_service, get_email_service, get_llm_service, get_vector_store, get_document_repository, get_rag_debug_service, get_budget_guard, get_usage_tracker
from src.database.repository import DocumentRepository
from src.shared.models import BaseResponse
from src.llm_interface.implementations.mistral_api import MistralAPIService
from src.rag_core.implementations.faiss_store import FaissVectorStore
from src.monitoring.rag_debug_logger import RagDebugService
from src.cost.budget_guard import BudgetGuard, BudgetReservation
from src.cost.usage_tracker import UsageTracker
from src.config import settings
import re
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# System prompt template for RAG context-based responses
MIMIR_SYSTEM_PROMPT = """Vous êtes Mimir, un assistant documentaire intelligent.
Votre rôle est de répondre aux questions en vous basant UNIQUEMENT sur le contexte documentaire fourni.

Règles importantes:
1. Répondez UNIQUEMENT avec les informations présentes dans le contexte
2. Si la réponse n'est pas dans le contexte, dites-le clairement
3. Soyez précis et factuel
4. Utilisez un ton professionnel mais accessible

Contexte documentaire:
{context}

Répondez à la question suivante en vous basant sur ce contexte:"""

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    responses={
        400: {"description": "Bad request"},
        500: {"description": "Internal server error"},
    }
)


class ChatRequest(BaseModel):
    """Request model for chat questions."""
    question: str = Field(..., min_length=1, max_length=1000, description="User question")
    session_id: Optional[str] = Field(None, description="Optional session ID for tracking")
    context_limit: Optional[int] = Field(5, ge=1, le=10, description="Maximum context documents")
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
    sources: List[SourceReference] = []
    confidence_score: float = Field(ge=0.0, le=1.0)
    session_id: str
    response_time_ms: int
    cached: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EscalationRequest(BaseModel):
    """Request model for escalating chat to human."""
    question: str
    session_id: Optional[str] = None
    chat_history: List[Dict[str, Any]] = []
    user_email: Optional[str] = None
    additional_context: Optional[str] = None


class EscalationResponse(BaseModel):
    """Response model for escalation requests."""
    success: bool
    message: str
    escalation_id: Optional[str] = None


@router.post("/", response_model=ChatResponse)
# Rate limit parity with chat_stream (CR-01 deferred gap, closed here): the
# non-stream route runs the same costly RAG pipeline and was the only chat
# route without a rate limit until now.
@limiter.limit(lambda: f"{settings.rate_limit_chat_per_minute}/minute",
               key_func=get_client_identifier)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
    chat_cache: ChatCacheService = Depends(get_chat_cache_service),
    llm_service: MistralAPIService = Depends(get_llm_service),
    vector_store: FaissVectorStore = Depends(get_vector_store),
    document_repository: DocumentRepository = Depends(get_document_repository),
    rag_debug: RagDebugService = Depends(get_rag_debug_service),
    budget_guard: BudgetGuard = Depends(get_budget_guard),
    usage_tracker: UsageTracker = Depends(get_usage_tracker)
) -> ChatResponse:
    """
    Process user question and return RAG-based response.

    Args:
        request: FastAPI request object
        chat_request: User question and parameters
        current_user: Optional authenticated user info
        chat_cache: Chat response cache service

    Returns:
        ChatResponse: Answer with sources and metadata
    """
    start_time = datetime.utcnow()
    client_ip = _get_client_ip(request)

    # Chat endpoint logging
    logger.info(f"Chat endpoint started - Session: {chat_request.session_id}, Question: {chat_request.question[:50]}..., IP: {client_ip}")

    # Budget gate BEFORE the try block: the try/except below deliberately
    # catches every Exception to always return a friendly ChatResponse (never
    # propagate a raw error to the client), so raising here would be
    # swallowed into a 200 response. Reserving before any embed/generate call
    # and before the cache check guarantees a real HTTP 429.
    #
    # Returning a JSONResponse directly (NOT `raise HTTPException`) is
    # deliberate: main.py registers a global `@app.exception_handler(HTTPException)`
    # that intercepts EVERY HTTPException regardless of where it is raised
    # and rewrites the body to `{"error_code": f"HTTP_{status_code}", ...}`
    # with `error_message` typed as `str` -- a dict `detail` would either be
    # flattened into the exact same "HTTP_429" shape as the slowapi
    # rate-limit response (defeating the whole point of this distinct
    # error_code) or crash the handler outright (ErrorResponse.error_message
    # rejects a dict). Returning a Response instance bypasses FastAPI's
    # exception-handler and response_model machinery entirely, exactly like
    # the existing slowapi 429 handler in rate_limit.py already does for the
    # identical reason (see its docstring).
    #
    # asyncio.to_thread: reserve() is a blocking SQLite write (WAL
    # serializes writers, busy_timeout applies) -- run it off the event loop
    # so a contended ledger write never stalls other in-flight requests.
    reservation: Optional[BudgetReservation] = await asyncio.to_thread(
        budget_guard.reserve, "chat"
    )
    if reservation is None:
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "budget_exceeded",
                "error_message": "Plafond quotidien de dépense IA atteint."
            }
        )

    # Tracks whether the reservation has already been released/finalized, so
    # the except block below never double-settles it (both the cache-hit
    # branch and _process_question_with_rag settle it internally).
    reservation_settled = False

    try:
        # Generate session ID if not provided
        session_id = chat_request.session_id or _generate_session_id(
            chat_request.question, client_ip
        )

        # 1. Log user request for RAG debug
        rag_debug.log_user_request(
            session_id=session_id,
            question=chat_request.question,
            user_context={
                "client_ip": client_ip,
                "user_type": current_user.get("user_type") if current_user else "anonymous",
                "context_limit": chat_request.context_limit,
                "include_sources": chat_request.include_sources
            },
            context_limit=chat_request.context_limit
        )

        # Check cache first
        cache_key = _generate_cache_key(chat_request.question)
        cached_response = chat_cache.get_chat_response(
            question=chat_request.question,
            context_hash=""  # For now, no context differentiation
        )

        if cached_response:
            logger.debug(f"Cache hit for question: {chat_request.question[:50]}...")

            # No LLM call happens on a cache hit: release the reservation so
            # the daily ledger is not charged for work that never occurred.
            # Mark settled BEFORE releasing so the finally below can never
            # double-settle even if release itself raises.
            reservation_settled = True
            await asyncio.to_thread(budget_guard.release, reservation)

            # 6. Log final response for RAG debug (cached response)
            rag_debug.log_final_response(
                session_id=session_id,
                confidence_score=cached_response.get("confidence_score", 0.0),
                sources_count=len(cached_response.get("sources", [])),
                final_sources=cached_response.get("sources", []),
                total_processing_time_ms=5,  # Cache hit is very fast
                cached=True
            )

            # Update cached response with current session
            cached_response["session_id"] = session_id
            cached_response["cached"] = True
            cached_response["timestamp"] = datetime.utcnow()

            return ChatResponse(**cached_response)

        # Process question with RAG pipeline. _process_question_with_rag
        # always settles the reservation internally (finalize on success or
        # partial usage, release if no LLM call was made) before returning.
        reservation_settled = True
        response = await _process_question_with_rag(
            question=chat_request.question,
            context_limit=chat_request.context_limit,
            include_sources=chat_request.include_sources,
            session_id=session_id,
            llm_service=llm_service,
            vector_store=vector_store,
            document_repository=document_repository,
            rag_debug=rag_debug,
            budget_guard=budget_guard,
            usage_tracker=usage_tracker,
            reservation=reservation
        )

        # Calculate response time
        end_time = datetime.utcnow()
        response_time_ms = int((end_time - start_time).total_seconds() * 1000)
        response["response_time_ms"] = response_time_ms

        # Pop the internal error marker set by the pipeline's fallback path
        # (never sent to the client -- ChatResponse has no such field).
        is_error_response = response.pop("error", False)

        # Cache the response -- but NEVER cache the pipeline's error
        # fallback: a transient failure (Mistral 500, network blip) must be
        # retried on the next identical question, not replayed from cache
        # for 30 minutes (each cache hit would also release its reservation,
        # serving errors for free instead of retrying).
        if not is_error_response:
            chat_cache.set_chat_response(
                question=chat_request.question,
                response=response,
                context_hash="",
                ttl=1800  # 30 minutes
            )

        logger.info(f"Chat response generated - session: {session_id}, time: {response_time_ms}ms")

        # 6. Log final response for RAG debug
        rag_debug.log_final_response(
            session_id=session_id,
            confidence_score=response["confidence_score"],
            sources_count=len(response["sources"]),
            final_sources=response["sources"],
            total_processing_time_ms=response_time_ms,
            cached=False
        )

        return ChatResponse(**response)

    except Exception as e:
        import traceback
        logger.error(f"Chat processing error: {type(e).__name__} - {str(e)}")
        logger.debug(f"Chat error traceback: {traceback.format_exc()}")

        # Return error response
        error_response = {
            "answer": "Je suis désolé, une erreur s'est produite lors du traitement de votre question. Veuillez réessayer ou contacter le support si le problème persiste.",
            "sources": [],
            "confidence_score": 0.0,
            "session_id": chat_request.session_id or "error",
            "response_time_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
            "cached": False,
            "timestamp": datetime.utcnow()
        }

        return ChatResponse(**error_response)

    finally:
        # Settle-once guard in a finally so it also covers
        # asyncio.CancelledError (a BaseException in Python 3.11 that the
        # `except Exception` above does NOT catch): an exception or a
        # cancellation before the cache check / RAG pipeline call would
        # otherwise leave the reservation dangling until the next daily
        # reset. Once _process_question_with_rag has been entered it settles
        # the reservation internally (reservation_settled is set just before
        # the call), so this release only fires for the pre-pipeline window.
        if not reservation_settled:
            reservation_settled = True
            await asyncio.to_thread(budget_guard.release, reservation)


@router.post("/stream")
# Rate limit per JWT user with IP fallback (SEC-03): behind the phase-5 nginx
# proxy the source IP will be the proxy's, so the JWT key is the only reliable
# identity for authenticated routes. The limit check runs BEFORE the endpoint
# body, so a 429 is raised before any SSE byte is streamed; a stream under the
# limit passes through untouched (StreamingResponse is a Response subclass,
# no `response` param needed).
@limiter.limit(lambda: f"{settings.rate_limit_chat_per_minute}/minute",
               key_func=get_client_identifier)
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
    chat_cache: ChatCacheService = Depends(get_chat_cache_service),
    llm_service: MistralAPIService = Depends(get_llm_service),
    vector_store: FaissVectorStore = Depends(get_vector_store),
    document_repository: DocumentRepository = Depends(get_document_repository),
    rag_debug: RagDebugService = Depends(get_rag_debug_service),
    budget_guard: BudgetGuard = Depends(get_budget_guard),
    usage_tracker: UsageTracker = Depends(get_usage_tracker)
):
    """
    Process user question with streaming response.
    Returns Server-Sent Events (SSE) stream.
    """

    # Budget gate in the SYNCHRONOUS body, BEFORE StreamingResponse is
    # constructed/returned (Pitfall 3): once StreamingResponse is returned
    # the client already has an implicit 200, so a real 429 is only possible
    # here. Do NOT move this check inside generate_sse -- that would yield a
    # 200 with an SSE error event instead of a genuine HTTP 429.
    #
    # JSONResponse (not `raise HTTPException`) for the same reason as in
    # chat(): main.py's global HTTPException handler would flatten/crash on
    # a dict detail -- see the comment there for the full explanation.
    #
    # asyncio.to_thread: blocking SQLite write off the event loop (see chat()).
    reservation: Optional[BudgetReservation] = await asyncio.to_thread(
        budget_guard.reserve, "chat"
    )
    if reservation is None:
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "budget_exceeded",
                "error_message": "Plafond quotidien de dépense IA atteint."
            }
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
                    "streaming": True
                },
                context_limit=chat_request.context_limit
            )

            # Check cache
            cached_response = chat_cache.get_chat_response(
                question=chat_request.question,
                context_hash=""
            )

            if cached_response:
                # No LLM call happens on a cache hit: release the reservation
                # so the daily ledger is not charged for work never done.
                # Mark settled BEFORE releasing so no other path can
                # double-settle even if release itself raises.
                settle_state["settled"] = True
                await asyncio.to_thread(budget_guard.release, reservation)
                yield f"data: {json.dumps({'type': 'chunk', 'content': cached_response['answer']})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'sources': cached_response.get('sources', []), 'confidence_score': cached_response.get('confidence_score', 0.0), 'cached': True})}\n\n"
                return

            # Stream RAG pipeline. _process_question_with_rag_stream always
            # settles the reservation internally (finalize on success/partial
            # usage, release if no LLM call was made) before the generator
            # finishes, including on a mid-stream disconnect.
            settle_state["settled"] = True
            async for event in _process_question_with_rag_stream(
                question=chat_request.question,
                context_limit=chat_request.context_limit,
                include_sources=chat_request.include_sources,
                session_id=session_id,
                llm_service=llm_service,
                vector_store=vector_store,
                document_repository=document_repository,
                rag_debug=rag_debug,
                budget_guard=budget_guard,
                usage_tracker=usage_tracker,
                reservation=reservation
            ):
                # Convert all numpy types before serialization
                event = convert_numpy_types(event)
                yield f"data: {json.dumps(event)}\n\n"

            end_time = datetime.utcnow()
            response_time_ms = int((end_time - start_time).total_seconds() * 1000)
            logger.info(f"Streaming completed - session: {session_id}, time: {response_time_ms}ms")

        except Exception as e:
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
            "Connection": "keep-alive"
        },
        background=BackgroundTask(_release_if_unsettled)
    )


@router.post("/escalate", response_model=EscalationResponse)
async def escalate_to_human(
    request: Request,
    escalation_request: EscalationRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
    email_service: EmailService = Depends(get_email_service)
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
            "additional_context": escalation_request.additional_context
        }

        # Extract sources from chat history if available
        context_sources = _extract_sources_from_history(escalation_request.chat_history)

        # Send escalation email
        success = await email_service.send_escalation_email(
            user_question=escalation_request.question,
            chat_history=escalation_request.chat_history,
            user_info=user_info,
            context_sources=context_sources
        )

        if success:
            logger.info(f"Escalation sent successfully - ID: {escalation_id}")
            return EscalationResponse(
                success=True,
                message="Votre demande a été transmise à notre équipe support. Vous recevrez une réponse dans les plus brefs délais.",
                escalation_id=escalation_id
            )
        else:
            logger.error(f"Escalation failed - ID: {escalation_id}")
            return EscalationResponse(
                success=False,
                message="Impossible d'envoyer votre demande pour le moment. Veuillez réessayer plus tard.",
                escalation_id=None
            )

    except Exception as e:
        logger.error(f"Escalation error: {e}")
        return EscalationResponse(
            success=False,
            message="Une erreur s'est produite lors de l'envoi de votre demande.",
            escalation_id=None
        )


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user)
) -> Dict[str, Any]:
    """
    Get chat history for a session.

    Args:
        session_id: Session identifier
        current_user: Optional authenticated user

    Returns:
        dict: Session history
    """
    return {
        "session_id": session_id,
        "messages": [],
        "created_at": datetime.utcnow()
    }


@router.delete("/sessions/{session_id}")
async def clear_session_history(
    session_id: str,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user)
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
        success=True,
        message=f"Session {session_id} history cleared",
        timestamp=datetime.utcnow()
    )


def _clean_filename(filename: str) -> str:
    """
    Clean the filename to extract a human-readable name.
    Removes the hash, extension and underscores.

    Example: "2e821c8cd63bcacaca47f4f52576ff08fadbad66dde9e359a3fbae80da79a818_CV_Yann_POINTUD.pdf"
            -> "CV Yann POINTUD"
    """
    import os

    # Remove the path if present
    filename = os.path.basename(filename)

    # Remove the extension
    filename = os.path.splitext(filename)[0]

    # Remove the hash (64 hex characters at the beginning)
    if '_' in filename and len(filename.split('_')[0]) == 64:
        filename = '_'.join(filename.split('_')[1:])

    # Replace underscores with spaces
    filename = filename.replace('_', ' ')

    return filename.strip()


def _find_documents_by_fuzzy_match(question: str, document_repository, threshold: int = 70) -> List[tuple]:
    """
    Find documents whose filename matches the question via fuzzy matching.

    Args:
        question: The user question
        document_repository: Document repository
        threshold: Minimum fuzzy score threshold (0-100)

    Returns:
        List of tuples (document_id, filename, fuzzy_score)
    """
    all_documents = document_repository.get_all()
    matches = []

    for doc in all_documents:
        # Clean the filename
        clean_name = _clean_filename(doc.filename)

        # Calculate the fuzzy matching score
        fuzzy_score = fuzz.partial_ratio(question.lower(), clean_name.lower())

        if fuzzy_score >= threshold:
            matches.append((doc.id, doc.filename, fuzzy_score))
            logger.info(f"Fuzzy match trouvé: '{clean_name}' (score: {fuzzy_score}) pour question: '{question}'")

    # Sort by descending score
    matches.sort(key=lambda x: x[2], reverse=True)

    return matches


async def _pre_include_document_chunks(
    document_ids: List[int],
    question_embedding: List[float],
    vector_store,
    document_repository,
    boost_factor: float,
    filename_similarities: Dict[int, float]
) -> List[Any]:
    """
    Retrieve all chunks from specified documents and apply the boost.

    Args:
        document_ids: IDs of documents to pre-include
        question_embedding: Question embedding vector
        vector_store: The FAISS vector store
        document_repository: Document repository
        boost_factor: Boost factor to apply
        filename_similarities: Dictionary {document_id: fuzzy_score}

    Returns:
        List of chunks with boosted scores
    """
    pre_included_chunks = []

    for doc_id in document_ids:
        # Retrieve the document
        document = document_repository.get_by_id(doc_id)
        if not document:
            continue

        # Retrieve all chunks for this document from FAISS
        # Perform a search with a very large top_k and filter by document_id
        all_results = await asyncio.to_thread(vector_store.query, question_embedding, top_k=1000)

        # Filter to keep only chunks from this document
        doc_chunks = [r for r in all_results if int(r.document_id) == doc_id]

        # Apply boost to each chunk
        filename_similarity = filename_similarities.get(doc_id, 0) / 100.0  # Normalize 0-1

        for chunk in doc_chunks:
            # Calculate boost based on filename similarity
            boost_amount = boost_factor * filename_similarity
            boosted_score = chunk.similarity_score + boost_amount
            boosted_score = min(0.99, boosted_score)

            # Update the score
            chunk.similarity_score = boosted_score
            pre_included_chunks.append(chunk)

            logger.debug(f"Chunk pré-inclus: doc_id={doc_id}, chunk_index={chunk.chunk_index}, "
                        f"score_original={chunk.similarity_score - boost_amount:.3f}, "
                        f"boost={boost_amount:.3f}, score_final={boosted_score:.3f}")

    return pre_included_chunks


def _calculate_weighted_confidence(search_results: List[Any], algorithm: str = "weighted") -> float:
    """
    Calculate confidence score using different algorithms.

    Args:
        search_results: List of search results
        algorithm: "simple" or "weighted"

    Returns:
        Confidence score between 0.0 and 0.95
    """
    if not search_results:
        return 0.1

    scores = [r.similarity_score for r in search_results]

    if algorithm == "simple":
        # Original algorithm (for backward compatibility)
        avg_similarity = sum(scores) / len(scores)
        return min(0.9, avg_similarity * (len(search_results) / 5))

    elif algorithm == "weighted":
        # Improved algorithm with degressive weighting

        # 1. Position-weighted score (first results count more)
        weights = [1.0, 0.8, 0.6, 0.4, 0.2]  # Degressive weighting
        weighted_sum = sum(
            score * weights[min(i, len(weights)-1)]
            for i, score in enumerate(scores)
        )
        weight_total = sum(weights[:min(len(scores), len(weights))])
        base_score = weighted_sum / weight_total

        # 2. Coherence factor (penalizes highly dispersed scores)
        if len(scores) > 1:
            std_dev = np.std(scores)
            max_score = max(scores)
            # High coherence if standard deviation is low relative to max
            coherence_factor = max(0.5, 1 - (std_dev / max(max_score, 0.1)))
        else:
            coherence_factor = 1.0

        # 3. Quality factor (bonus if the best score is really good)
        best_score = max(scores)
        quality_bonus = 1.0
        if best_score > 0.9:
            quality_bonus = 1.2
        elif best_score > 0.8:
            quality_bonus = 1.1

        # 4. Combined final score
        confidence = min(0.95,
                        base_score * 0.7 +           # 70% weighted score
                        coherence_factor * 0.2 +     # 20% coherence
                        (best_score * 0.1) *         # 10% best result quality
                        quality_bonus
                        )

        logger.debug(
            f"Confiance calculée: base={base_score:.3f}, cohérence={coherence_factor:.3f}, "
            f"qualité={quality_bonus:.3f}, final={confidence:.3f}"
        )

        return confidence

    else:
        # Fallback to the simple algorithm
        logger.warning(f"Algorithme inconnu '{algorithm}', utilisation de 'simple'")
        return _calculate_weighted_confidence(search_results, "simple")


def _filter_dynamic_sources(search_results: List[Any], config: Any, question: str = "") -> List[Any]:
    """
    Dynamically filter sources based on relevance with gap detection.

    Args:
        search_results: List of search results (sorted by descending score)
        config: Configuration with similarity_threshold, min_sources, max_sources
        question: Question for named entity detection

    Returns:
        Filtered list of relevant sources
    """
    if not search_results:
        return []

    scores = [r.similarity_score for r in search_results]
    best_score = scores[0]

    logger.debug(f"Filtrage dynamique - Scores: {[f'{s:.3f}' for s in scores[:8]]}")

    # Dynamic filtering based on gap from the best score
    # Threshold = max(SIMILARITY_THRESHOLD, best_score x (1 - DYNAMIC_FILTER_PERCENTAGE))
    dynamic_threshold = best_score * (1 - config.dynamic_filter_percentage)
    final_threshold = max(config.similarity_threshold, dynamic_threshold)
    filtered_results = [r for r in search_results if r.similarity_score >= final_threshold]
    method = f"dynamic@{final_threshold:.3f}"

    logger.debug(f"Filtrage dynamique: best={best_score:.3f}, gap={config.dynamic_filter_percentage:.2f}, "
                f"seuil={final_threshold:.3f}, {len(search_results)} → {len(filtered_results)} chunks")

    # 4. Enforce min/max constraints
    original_count = len(filtered_results)

    if len(filtered_results) < config.min_sources:
        filtered_results = search_results[:config.min_sources]
        method += f"→min({config.min_sources})"
    elif len(filtered_results) > config.max_sources:
        filtered_results = filtered_results[:config.max_sources]
        method += f"→max({config.max_sources})"

    # 5. Detailed filtering log
    logger.info(
        f"Sources dynamiques: {len(search_results)} → {len(filtered_results)} sources "
        f"(méthode: {method})"
    )

    if len(filtered_results) != original_count:
        logger.debug(f"Ajustement contraintes: {original_count} → {len(filtered_results)}")

    return filtered_results


async def _process_question_with_rag(
    question: str,
    context_limit: int,
    include_sources: bool,
    session_id: str,
    llm_service: MistralAPIService,
    vector_store: FaissVectorStore,
    document_repository: DocumentRepository,
    rag_debug: RagDebugService,
    budget_guard: Optional["BudgetGuard"] = None,
    usage_tracker: Optional["UsageTracker"] = None,
    reservation: Optional["BudgetReservation"] = None
) -> Dict[str, Any]:
    """
    Process question using RAG pipeline.

    Full RAG system implementation:
    1. Generate embeddings for the question
    2. Search vector store for relevant documents
    3. Build context from retrieved documents
    4. Generate response using LLM
    5. Format response with sources

    Args:
        question: User question
        context_limit: Maximum number of context documents
        include_sources: Whether to include source references
        session_id: Session identifier
        llm_service: LLM service for embeddings and generation
        vector_store: Vector store for similarity search
        budget_guard: Optional BudgetGuard used to finalize/release the
            caller's reservation once the real cost is known
        usage_tracker: Optional UsageTracker used to price and persist the
            embedding and generation usage rows
        reservation: The BudgetReservation captured by the caller before
            this pipeline started; settled (finalize or release) internally
            so the caller never has to reason about partial-failure cost

    Returns:
        dict: Response data
    """
    # Accumulates the real euro cost of every LLM call actually made, so the
    # reservation can be finalized with the true total instead of released
    # outright once at least one paid call has happened.
    total_cost_eur = 0.0
    llm_call_made = False
    try:
        # Step 1: Generate embeddings for the question
        logger.info(f"Generating embeddings for question: {question[:50]}...")
        start_embedding = datetime.utcnow()
        embedding_response = await llm_service.embed([question], session_id=session_id, rag_debug=rag_debug)
        embedding_time = (datetime.utcnow() - start_embedding).total_seconds() * 1000
        question_embedding = np.array(embedding_response.embeddings[0], dtype=np.float32)

        llm_call_made = True
        if usage_tracker is not None:
            # asyncio.to_thread: record() is a blocking SQLite write.
            total_cost_eur += await asyncio.to_thread(
                usage_tracker.record,
                "embedding",
                embedding_response.model,
                embedding_response.prompt_tokens,
                embedding_response.completion_tokens,
                estimated=False,
                session_id=session_id
            )

        # Step 1.5: Filename pre-inclusion (fuzzy matching)
        pre_included_chunks = []
        if settings.filename_pre_inclusion:
            logger.info(f"Checking for filename fuzzy matches...")
            matched_docs = _find_documents_by_fuzzy_match(
                question,
                document_repository,
                threshold=settings.filename_fuzzy_threshold
            )

            if matched_docs:
                # Prepare the similarities dictionary
                filename_similarities = {doc_id: score for doc_id, _, score in matched_docs}
                document_ids = [doc_id for doc_id, _, _ in matched_docs]

                # Pre-include all chunks from matched documents
                pre_included_chunks = await _pre_include_document_chunks(
                    document_ids=document_ids,
                    question_embedding=question_embedding,
                    vector_store=vector_store,
                    document_repository=document_repository,
                    boost_factor=settings.filename_boost,
                    filename_similarities=filename_similarities
                )

                logger.info(f"Pré-inclusion: {len(pre_included_chunks)} chunks de {len(matched_docs)} document(s) matchés")

        # Step 2: Search vector store for relevant documents
        logger.info(f"Searching for relevant context in vector store...")
        start_search = datetime.utcnow()
        search_results = await asyncio.to_thread(vector_store.query,
            vector=question_embedding,
            top_k=settings.max_sources * 2,  # Retrieve more to filter afterwards
            filter_dict=None  # No filter for now
        )
        search_time = (datetime.utcnow() - start_search).total_seconds() * 1000

        # 2. Log vector search results for RAG debug
        rag_debug.log_vector_search(
            session_id=session_id,
            search_results=search_results,
            embedding_tokens=embedding_response.usage_tokens,
            search_time_ms=search_time
        )

        # Step 2.1: Merge pre-included chunks with vector search results
        if pre_included_chunks:
            # Create a set of pre-included chunk_ids to avoid duplicates
            pre_included_ids = {chunk.chunk_id for chunk in pre_included_chunks}

            # Filter vector results to remove duplicates
            unique_vector_results = [r for r in search_results if r.chunk_id not in pre_included_ids]

            # Merge: pre-included first, then vector results
            search_results = pre_included_chunks + unique_vector_results

            # Sort by descending score
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)

            logger.info(f"Merge: {len(pre_included_chunks)} pre-included + {len(unique_vector_results)} vector = {len(search_results)} total")

        # Step 2.5: Apply dynamic source filtering
        if search_results:
            search_results = _filter_dynamic_sources(search_results, settings, question)

        # Step 3: Build context from retrieved documents
        context_parts = []
        sources = []

        if search_results:
            logger.info(f"Found {len(search_results)} relevant chunks")

            for result in search_results:
                context_parts.append(
                    f"[Source: {result.source}] {result.text}"
                )

                if include_sources:
                    # Retrieve the original document name
                    try:
                        document = document_repository.get_by_id(int(result.document_id))
                        filename = document.filename if document else str(result.source)
                    except Exception:
                        # Fallback if retrieval error
                        filename = str(result.source)

                    sources.append({
                        "document_id": int(result.document_id),
                        "filename": filename,
                        "chunk_text": result.text,
                        "similarity_score": float(round(result.similarity_score, 3)),
                        "chunk_index": int(result.chunk_index),
                        "total_chunks": int(result.total_chunks)
                    })

        # Step 4: Build prompt for LLM
        if context_parts:
            context_text = "\n\n".join(context_parts)
            system_prompt = MIMIR_SYSTEM_PROMPT
            full_prompt = system_prompt.format(context=context_text)
        else:
            # No context found
            logger.warning("No relevant context found in vector store")
            context_text = ""
            system_prompt = """Vous êtes Mimir, un assistant documentaire intelligent.
L'utilisateur vous pose une question mais aucun contexte pertinent n'a été trouvé dans la documentation.

Informez poliment l'utilisateur que vous ne trouvez pas d'information pertinente dans la documentation disponible pour répondre à sa question, et suggérez-lui de:
1. Reformuler sa question avec d'autres mots-clés
2. Contacter le support humain si nécessaire

Restez professionnel et utile."""
            full_prompt = system_prompt

        # 3. Log context building for RAG debug
        rag_debug.log_context_building(
            session_id=session_id,
            system_prompt=system_prompt,
            context_text=context_text,
            context_chunks=len(context_parts),
            filtered_sources=sources
        )

        # Step 5: Generate response using LLM
        logger.info("Generating response with LLM...")
        start_llm = datetime.utcnow()
        generation_response = await llm_service.generate(
            prompt=question,
            system_prompt=full_prompt,
            max_tokens=800,
            temperature=0.1,
            session_id=session_id,  # Pass session_id for LLM logging
            rag_debug=rag_debug  # Pass debug service for LLM logging
        )
        llm_time = (datetime.utcnow() - start_llm).total_seconds() * 1000

        if usage_tracker is not None:
            # asyncio.to_thread: record() is a blocking SQLite write.
            total_cost_eur += await asyncio.to_thread(
                usage_tracker.record,
                "chat",
                generation_response.model,
                generation_response.prompt_tokens,
                generation_response.completion_tokens,
                estimated=False,
                session_id=session_id
            )

        answer = generation_response.content


        # Calculate confidence score using the configured algorithm
        confidence_score = _calculate_weighted_confidence(
            search_results, settings.confidence_algorithm
        )

        logger.info(
            f"RAG response generated successfully - confidence: {confidence_score:.2f} "
            f"(algorithm: {settings.confidence_algorithm})"
        )

        return {
            "answer": answer,
            "sources": sources,
            "confidence_score": round(confidence_score, 2),
            "session_id": session_id,
            "cached": False,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        logger.error(f"RAG pipeline failed: {str(e)}", exc_info=True)

        # Log error to RAG debug as well
        rag_debug.log_error(
            session_id=session_id,
            error_type=type(e).__name__,
            error_message=str(e),
            stage="rag_pipeline"
        )

        # Fallback response in case of error. The "error" marker is consumed
        # (popped) by the caller so it never reaches the client: it tells
        # chat() to SKIP caching -- otherwise a transient failure (Mistral
        # 500, network blip) would be served from cache for 30 minutes to
        # every identical question instead of being retried.
        return {
            "answer": "Je suis désolé, une erreur technique s'est produite lors du traitement de votre question. L'équipe technique a été notifiée. Veuillez réessayer dans quelques instants ou contacter le support si le problème persiste.",
            "sources": [],
            "confidence_score": 0.0,
            "session_id": session_id,
            "cached": False,
            "timestamp": datetime.utcnow(),
            "error": True
        }

    finally:
        # Settle the reservation exactly once, in a finally so it also runs
        # on asyncio.CancelledError (a BaseException in Python 3.11 that the
        # `except Exception` above does NOT catch -- e.g. server shutdown or
        # task cancellation during an awaited embed/generate call). Finalize
        # with whatever real cost was already incurred (e.g. embedding
        # succeeded but generation failed/was cancelled) or release outright
        # if no LLM call happened at all -- symmetric with the stream
        # variant's outer finally. asyncio.to_thread keeps the blocking
        # SQLite ledger write off the event loop.
        if budget_guard is not None and reservation is not None:
            if llm_call_made:
                await asyncio.to_thread(budget_guard.finalize, reservation, total_cost_eur)
            else:
                await asyncio.to_thread(budget_guard.release, reservation)


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


def _extract_sources_from_history(chat_history: List[Dict[str, Any]]) -> List[str]:
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


async def _process_question_with_rag_stream(
    question: str,
    context_limit: int,
    include_sources: bool,
    session_id: str,
    llm_service: MistralAPIService,
    vector_store: FaissVectorStore,
    document_repository: DocumentRepository,
    rag_debug: RagDebugService,
    budget_guard: Optional["BudgetGuard"] = None,
    usage_tracker: Optional["UsageTracker"] = None,
    reservation: Optional["BudgetReservation"] = None
):
    """
    Process question using RAG pipeline with streaming.
    Yields SSE events as processing progresses.

    budget_guard/usage_tracker/reservation mirror _process_question_with_rag,
    but the reservation is settled in an OUTER finally block here (see below)
    because a mid-stream client disconnect throws GeneratorExit -- a
    BaseException, not caught by `except Exception` -- straight through this
    generator; only a finally at the outermost scope is guaranteed to run in
    every case (normal completion, error, or disconnect).
    """
    # Accumulates the real euro cost of every LLM call actually made.
    total_cost_eur = 0.0
    llm_call_made = False
    try:
        # Step 1: Generate embeddings
        logger.info(f"Generating embeddings for streaming question")
        start_embedding = datetime.utcnow()
        embedding_response = await llm_service.embed([question], session_id=session_id, rag_debug=rag_debug)
        question_embedding = np.array(embedding_response.embeddings[0], dtype=np.float32)

        llm_call_made = True
        if usage_tracker is not None:
            # asyncio.to_thread: record() is a blocking SQLite write.
            total_cost_eur += await asyncio.to_thread(
                usage_tracker.record,
                "embedding",
                embedding_response.model,
                embedding_response.prompt_tokens,
                embedding_response.completion_tokens,
                estimated=False,
                session_id=session_id
            )

        # Step 1.5: Filename pre-inclusion
        pre_included_chunks = []
        if settings.filename_pre_inclusion:
            matched_docs = _find_documents_by_fuzzy_match(
                question,
                document_repository,
                threshold=settings.filename_fuzzy_threshold
            )

            if matched_docs:
                filename_similarities = {doc_id: score for doc_id, _, score in matched_docs}
                document_ids = [doc_id for doc_id, _, _ in matched_docs]

                pre_included_chunks = await _pre_include_document_chunks(
                    document_ids=document_ids,
                    question_embedding=question_embedding,
                    vector_store=vector_store,
                    document_repository=document_repository,
                    boost_factor=settings.filename_boost,
                    filename_similarities=filename_similarities
                )

        # Step 2: Vector search
        start_search = datetime.utcnow()
        search_results = await asyncio.to_thread(vector_store.query,
            vector=question_embedding,
            top_k=settings.max_sources * 2,
            filter_dict=None
        )
        search_time = (datetime.utcnow() - start_search).total_seconds() * 1000

        rag_debug.log_vector_search(
            session_id=session_id,
            search_results=search_results,
            embedding_tokens=embedding_response.usage_tokens,
            search_time_ms=search_time
        )

        # Step 2.1: Merge pre-included chunks
        if pre_included_chunks:
            pre_included_ids = {chunk.chunk_id for chunk in pre_included_chunks}
            unique_vector_results = [r for r in search_results if r.chunk_id not in pre_included_ids]
            search_results = pre_included_chunks + unique_vector_results
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)

        # Step 2.5: Apply filtering
        if search_results:
            search_results = _filter_dynamic_sources(search_results, settings, question)

        # Step 3: Build context
        context_parts = []
        sources = []

        if search_results:
            for result in search_results:
                context_parts.append(f"[Source: {result.source}] {result.text}")

                if include_sources:
                    try:
                        document = document_repository.get_by_id(int(result.document_id))
                        filename = document.filename if document else str(result.source)
                    except Exception:
                        filename = str(result.source)

                    sources.append({
                        "document_id": int(result.document_id),
                        "filename": filename,
                        "chunk_text": result.text,
                        "similarity_score": float(round(result.similarity_score, 3)),
                        "chunk_index": int(result.chunk_index),
                        "total_chunks": int(result.total_chunks)
                    })

        # Step 4: Build prompt
        if context_parts:
            context_text = "\n\n".join(context_parts)
            system_prompt = MIMIR_SYSTEM_PROMPT
            full_prompt = system_prompt.format(context=context_text)
        else:
            logger.warning("No relevant context found")
            context_text = ""
            system_prompt = """Vous êtes Mimir, un assistant documentaire intelligent.
L'utilisateur vous pose une question mais aucun contexte pertinent n'a été trouvé dans la documentation."""
            full_prompt = system_prompt

        rag_debug.log_context_building(
            session_id=session_id,
            system_prompt=system_prompt,
            context_text=context_text,
            context_chunks=len(context_parts),
            filtered_sources=sources
        )

        # Step 5: Stream LLM generation
        logger.info("Starting streaming LLM generation...")
        full_answer = ""
        usage_out: Dict[str, Any] = {}
        chat_usage_recorded = False

        try:
            async for chunk in llm_service.generate_stream(
                prompt=question,
                system_prompt=full_prompt,
                max_tokens=800,
                temperature=0.1,
                session_id=session_id,
                rag_debug=rag_debug,
                usage_out=usage_out
            ):
                full_answer += chunk
                yield {"type": "chunk", "content": chunk}

            # Stream completed and the final SSE chunk carried real usage.
            if usage_tracker is not None and usage_out:
                # asyncio.to_thread: record() is a blocking SQLite write.
                total_cost_eur += await asyncio.to_thread(
                    usage_tracker.record,
                    "chat",
                    llm_service.model_name,
                    usage_out.get("prompt_tokens", 0),
                    usage_out.get("completion_tokens", 0),
                    estimated=False,
                    session_id=session_id
                )
                chat_usage_recorded = True
        finally:
            # Guarantee exactly one chat usage row per request (T-03-12): if
            # the async-for loop ended -- normal completion without a final
            # usage chunk, an exception, or a mid-stream client disconnect
            # (GeneratorExit) -- without recording real usage above, estimate
            # tokens from the text lengths instead. The prompt side MUST be
            # estimated too: Mistral bills the full prompt (system prompt +
            # entire document context) even for an interrupted stream, and
            # in this RAG pipeline the prompt is usually the dominant share
            # of billed tokens -- recording prompt_tokens=0 would make the
            # ledger drift below the real Mistral spend on every disconnect.
            # asyncio.to_thread: awaiting (no yield) in an async generator's
            # finally is legal during aclose(); keeps the blocking SQLite
            # write off the event loop.
            if usage_tracker is not None and not chat_usage_recorded:
                estimated_prompt_tokens = max(1, (len(full_prompt) + len(question)) // 4)
                estimated_completion_tokens = max(1, len(full_answer) // 4)
                total_cost_eur += await asyncio.to_thread(
                    usage_tracker.record,
                    "chat",
                    llm_service.model_name,
                    estimated_prompt_tokens,
                    estimated_completion_tokens,
                    estimated=True,
                    session_id=session_id
                )
                chat_usage_recorded = True

        # Calculate confidence
        confidence_score = _calculate_weighted_confidence(search_results, settings.confidence_algorithm)

        # Send completion event - convert numpy types to Python native
        yield {
            "type": "done",
            "sources": sources,
            "confidence_score": float(round(confidence_score, 2)),
            "cached": False
        }

        logger.info(f"Streaming RAG completed - confidence: {confidence_score:.2f}")

    except Exception as e:
        logger.error(f"Streaming RAG pipeline failed: {str(e)}", exc_info=True)
        rag_debug.log_error(
            session_id=session_id,
            error_type=type(e).__name__,
            error_message=str(e),
            stage="streaming_rag_pipeline"
        )
        # Generic client-facing message; details stay in logs/rag_debug only
        yield {"type": "error", "message": "Une erreur interne est survenue."}

    finally:
        # Settle the reservation exactly once, regardless of normal
        # completion, an exception caught above, or a mid-stream client
        # disconnect (GeneratorExit propagates straight through the except
        # clause -- which only catches Exception -- but always runs this
        # finally before the generator closes). asyncio.to_thread keeps the
        # blocking SQLite ledger write off the event loop; awaiting (no
        # yield) in a finally is legal during aclose().
        if budget_guard is not None and reservation is not None:
            if llm_call_made:
                await asyncio.to_thread(budget_guard.finalize, reservation, total_cost_eur)
            else:
                await asyncio.to_thread(budget_guard.release, reservation)