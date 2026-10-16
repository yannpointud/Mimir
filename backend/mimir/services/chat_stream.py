"""
Server-Sent Events stream of a chat answer.

The route reserves the AI budget and returns the stream; this module produces
the SSE events (start, then either the cached answer replay or the live RAG
pipeline events) and makes sure the reservation is settled exactly once.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from mimir.cache.lru_cache import ChatCacheService
from mimir.cost.budget_guard import BudgetGuard, BudgetReservation
from mimir.database.repository import DocumentRepository
from mimir.monitoring.rag_debug_logger import RagDebugService
from mimir.services.rag_service import RagService

logger = logging.getLogger(__name__)

ERROR_MESSAGE = "Une erreur interne est survenue."

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    # Disable nginx response buffering so events reach the client immediately
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def generate_session_id(question: str, client_ip: str) -> str:
    """Session id derived from the question, the client IP and the time."""
    timestamp = datetime.utcnow().isoformat()
    data = f"{question[:50]}:{client_ip}:{timestamp}"
    return hashlib.md5(data.encode()).hexdigest()[:16]


def convert_numpy_types(obj: Any) -> Any:
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


def sse_event(payload: dict[str, Any]) -> str:
    """One SSE ``data:`` frame carrying the JSON payload."""
    return f"data: {json.dumps(payload)}\n\n"


class ReservationSettlement:
    """Settle-once guard of a budget reservation.

    Shared between the SSE generator and the StreamingResponse background
    task. An async generator that is never iterated (client disconnected
    before Starlette starts streaming, or the initial response send failed)
    never runs its body nor its finally blocks, so settlement living only in
    the generator could not cover that case: the reservation would stay
    charged until the next daily reset.
    """

    def __init__(self, budget_guard: BudgetGuard, reservation: BudgetReservation) -> None:
        self.budget_guard = budget_guard
        self.reservation = reservation
        self.settled = False

    def release_if_unsettled(self) -> None:
        """Release the reservation unless another path already settled it.

        Sync on purpose: Starlette runs sync background tasks in a threadpool,
        so the blocking SQLite write never blocks the event loop.
        """
        if not self.settled:
            self.settled = True
            self.budget_guard.release(self.reservation)

    async def release(self) -> None:
        """Release now, off the event loop. Marked settled BEFORE releasing so
        no other path can double-settle even if release itself raises."""
        self.settled = True
        await asyncio.to_thread(self.budget_guard.release, self.reservation)

    async def release_in_thread_if_unsettled(self) -> None:
        if not self.settled:
            await self.release()


@dataclass(frozen=True)
class ChatQuestion:
    """The parts of a chat request the stream needs."""

    question: str
    session_id: str | None
    context_limit: int | None
    include_sources: bool
    client_ip: str
    current_user: dict[str, Any] | None


class ChatStream:
    """Produces the SSE events answering one question."""

    def __init__(
        self,
        *,
        rag_service: RagService,
        chat_cache: ChatCacheService,
        document_repository: DocumentRepository,
        rag_debug: RagDebugService,
    ) -> None:
        self.rag_service = rag_service
        self.chat_cache = chat_cache
        self.document_repository = document_repository
        self.rag_debug = rag_debug

    async def events(
        self, chat: ChatQuestion, settlement: ReservationSettlement
    ) -> AsyncIterator[str]:
        """SSE frames: start, then the cached replay or the live pipeline events.

        Any failure becomes a generic error event; the reservation is settled
        exactly once whatever happens.
        """
        start_time = datetime.utcnow()
        try:
            session_id = chat.session_id or generate_session_id(chat.question, chat.client_ip)
            yield sse_event({"type": "start", "session_id": session_id})
            self._log_request(chat, session_id)

            # Snapshot the corpus version BEFORE consulting the cache: it is
            # part of the server-derived cache key, so any ingestion/deletion
            # (which bumps FaissVectorStore.last_updated) implicitly
            # invalidates all prior entries. The vector store lives inside the
            # injected RagService (the route does not depend on it directly).
            corpus_version = self.rag_service.vector_store.get_corpus_version()
            cached_response = self.chat_cache.get_stream_response(chat.question, corpus_version)
            if cached_response:
                # No LLM call happens on a cache hit: release the reservation
                # so the daily ledger is not charged for work never done.
                await settlement.release()
                for frame in _replay_cached(cached_response):
                    yield frame
                return

            # RagService.answer_stream() always settles the reservation in its
            # outer finally (finalize on success/partial usage, release if no
            # LLM call was made), including on a mid-stream disconnect, and
            # writes the corpus-aware cache after a successful done event.
            settlement.settled = True
            async for event in self.rag_service.answer_stream(
                question=chat.question,
                context_limit=chat.context_limit,
                include_sources=chat.include_sources,
                session_id=session_id,
                document_repository=self.document_repository,
                reservation=settlement.reservation,
                corpus_version=corpus_version,
            ):
                yield sse_event(convert_numpy_types(event))

            response_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            logger.info(f"Streaming completed - session: {session_id}, time: {response_time_ms}ms")

        except Exception as e:  # noqa: BLE001 - SSE boundary: any failure becomes an error event
            logger.error(f"Streaming error: {type(e).__name__} - {str(e)}")
            # Never leak raw exception details to the client (info disclosure);
            # the full error is kept in the server logs above.
            yield sse_event({"type": "error", "message": ERROR_MESSAGE})

        finally:
            # Settle-once fallback: covers GeneratorExit (client disconnect at
            # a yield point) and asyncio.CancelledError, neither of which the
            # `except Exception` above catches. No-op when the cache-hit branch
            # or the RAG pipeline already settled the reservation. Awaiting
            # (no yield) inside an async generator's finally is legal during
            # aclose().
            await settlement.release_in_thread_if_unsettled()

    def _log_request(self, chat: ChatQuestion, session_id: str) -> None:
        self.rag_debug.log_user_request(
            session_id=session_id,
            question=chat.question,
            user_context={
                "client_ip": chat.client_ip,
                "user_type": (
                    chat.current_user.get("user_type") if chat.current_user else "anonymous"
                ),
                "streaming": True,
            },
            context_limit=chat.context_limit,
        )


def _replay_cached(cached_response: dict[str, Any]) -> Iterator[str]:
    """Frames replaying a cached answer.

    The citation event is replayed before done so a cache hit is
    indistinguishable from a fresh stream: the live pipeline yields
    chunk -> citation -> done, and the frontend needs its [N] -> source map
    on hits too.
    """
    yield sse_event({"type": "chunk", "content": cached_response["answer"]})
    yield sse_event({"type": "citation", "citations": cached_response.get("citations", {})})
    yield sse_event(
        {
            "type": "done",
            "sources": cached_response.get("sources", []),
            "confidence_score": cached_response.get("confidence_score", 0.0),
            "cached": True,
        }
    )
