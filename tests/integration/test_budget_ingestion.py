"""
Integration tests for the ingestion budget fail-closed path.

Covers three guarantees:
  - A budget-exhausted document stops cleanly with status 'error' and message
    "Daily budget exceeded", and is NOT retried (BudgetExceeded is
    caught before the generic except, non-retriable).
  - A budget-blocked ingestion makes no embedding call to Mistral.
  - A successful ingestion records the embedding usage as a llm_usage row
    keyed by session_id doc:{document_id}, and finalizes the reservation.

All tests are hermetic: the LLM service is fully mocked (zero real Mistral
API calls); the success-case test uses an isolated temporary SQLite
db_manager (BudgetGuard/UsageTracker open their own sessions via the real
db_manager singleton, not the test_session fixture -- mirrors
tests/integration/test_budget_guard_endpoints.py). The fail-closed and
release-on-failure cases use mocked budget_guard/usage_tracker injected via
the IngestionProcessor constructor -- no real DB session is ever opened.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from mimir.cost.budget_guard import BudgetGuard, BudgetReservation
from mimir.cost.usage_tracker import UsageTracker
from mimir.database.connection import db_manager
from mimir.database.models import LlmUsage
from mimir.ingestion.processor import IngestionProcessor
from mimir.ingestion.queue_manager import IngestionTask
from mimir.llm_interface.interfaces import EmbeddingResponse
from mimir.shared.errors import BudgetExceeded


def _usage_rows():
    """All llm_usage rows in insertion order, from the isolated db_manager."""
    session = db_manager.get_session()
    try:
        return session.query(LlmUsage).order_by(LlmUsage.id.asc()).all()
    finally:
        session.close()


@pytest.fixture
def mock_document_repository():
    """Document repository mocked -- tracks update_status calls without a
    real DB (document status lives in the app's own `documents` table, not
    exercised here)."""
    repo = Mock()
    doc = Mock()
    doc.id = 123
    repo.get_by_id.return_value = doc
    repo.update_status.return_value = None
    return repo


@pytest.fixture
def mock_vector_store():
    store = Mock()
    store.upsert.return_value = True
    store.persist.return_value = True
    return store


def _single_chunk_task(document_id="123"):
    return IngestionTask(file_path="dummy.txt", document_id=document_id)


def _patched_pipeline(processor, text="Sample text for budget test"):
    """Context manager patching extraction/chunking so the pipeline reaches
    the embeddings step with exactly one chunk."""
    return patch.object(processor, "_extract_text", return_value=text), patch.object(
        processor.chunking_strategy,
        "chunk_text",
        return_value=[
            {
                "text": "chunk",
                "chunk_index": 0,
                "total_chunks": 1,
                "start_char": 0,
                "end_char": 5,
                "word_count": 1,
                "char_count": 5,
            }
        ],
    )


class TestBudgetFailClosed:
    """A budget-exhausted document stops cleanly, is NOT retried, and never
    calls the embedding API."""

    @pytest.mark.asyncio
    async def test_fail_closed_reserve_none_stops_cleanly_non_retriable(
        self, mock_document_repository, mock_vector_store
    ):
        rejecting_guard = Mock(spec=BudgetGuard)
        rejecting_guard.reserve = Mock(return_value=None)
        rejecting_guard.finalize = Mock()
        rejecting_guard.release = Mock()

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock()

        processor = IngestionProcessor(
            llm_service=mock_llm,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            budget_guard=rejecting_guard,
            usage_tracker=Mock(),
        )

        task = _single_chunk_task()
        extract_patch, chunk_patch = _patched_pipeline(processor)

        with extract_patch, chunk_patch:
            success = await processor._process_task(task)

        assert success is False
        mock_llm.embed.assert_not_called()

        mock_document_repository.update_status.assert_any_call(
            123, "error", error_message="Daily budget exceeded"
        )
        # Last call must be the fail-closed status update, not a generic
        # "Processing pipeline failed" message.
        last_call = mock_document_repository.update_status.call_args_list[-1]
        assert last_call.args[1] == "error"
        assert last_call.kwargs.get("error_message") == "Daily budget exceeded"

        # Non-retriable: the task's retry budget was exhausted so the async
        # queue worker loop will not re-queue it.
        assert task.can_retry() is False

    @pytest.mark.asyncio
    async def test_rejected_reservation_raises_budget_exceeded_from_pipeline(
        self, mock_document_repository, mock_vector_store
    ):
        """Direct pipeline-level check (bypassing _process_task) that a
        rejected reservation raises BudgetExceeded, proving the raise
        site independently of the _process_task fail-closed handling."""
        rejecting_guard = Mock(spec=BudgetGuard)
        rejecting_guard.reserve = Mock(return_value=None)

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock()

        processor = IngestionProcessor(
            llm_service=mock_llm,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            budget_guard=rejecting_guard,
            usage_tracker=Mock(),
        )

        task = _single_chunk_task()
        extract_patch, chunk_patch = _patched_pipeline(processor)

        with extract_patch, chunk_patch, pytest.raises(BudgetExceeded):
            await processor._process_document_pipeline(task)

        mock_llm.embed.assert_not_called()


class TestSuccessfulIngestionUsageRecording:
    """A successful ingestion records exactly one llm_usage row keyed by
    session_id doc:{document_id} and finalizes the reservation with the
    real cost."""

    @pytest.mark.asyncio
    async def test_successful_embedding_records_usage_row_keyed_by_document(
        self, isolated_db_manager, mock_document_repository, mock_vector_store
    ):
        real_budget_guard = BudgetGuard()
        real_usage_tracker = UsageTracker()

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock(
            return_value=EmbeddingResponse(
                embeddings=[[0.1, 0.2, 0.3]],
                model="mistral-embed",
                usage_tokens=10,
                prompt_tokens=10,
                completion_tokens=0,
            )
        )

        processor = IngestionProcessor(
            llm_service=mock_llm,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            budget_guard=real_budget_guard,
            usage_tracker=real_usage_tracker,
        )

        task = _single_chunk_task(document_id="123")
        extract_patch, chunk_patch = _patched_pipeline(processor)

        with extract_patch, chunk_patch:
            success = await processor._process_task(task)

        assert success is True
        mock_llm.embed.assert_called_once()

        rows = _usage_rows()
        embedding_rows = [r for r in rows if r.call_type == "embedding"]
        assert len(embedding_rows) == 1
        assert embedding_rows[0].session_id == "doc:123"
        assert embedding_rows[0].model == "mistral-embed"
        assert embedding_rows[0].estimated is False


class TestReleaseOnEmbeddingFailure:
    """A reservation accepted before a failing embedding call is released
    (refunded), not silently leaked."""

    @pytest.mark.asyncio
    async def test_embedding_exception_after_reservation_releases_it(
        self, mock_document_repository, mock_vector_store
    ):
        reservation = BudgetReservation(today="2024-01-01", estimate_eur=0.001)
        accepting_guard = Mock(spec=BudgetGuard)
        accepting_guard.reserve = Mock(return_value=reservation)
        accepting_guard.finalize = Mock()
        accepting_guard.release = Mock()

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock(side_effect=Exception("Mistral API error"))

        processor = IngestionProcessor(
            llm_service=mock_llm,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            budget_guard=accepting_guard,
            usage_tracker=Mock(),
        )

        task = _single_chunk_task()
        extract_patch, chunk_patch = _patched_pipeline(processor)

        with extract_patch, chunk_patch:
            success = await processor._process_task(task)

        assert success is False
        accepting_guard.release.assert_called_once_with(reservation)
        accepting_guard.finalize.assert_not_called()

        # Not the fail-closed budget path -- a generic pipeline failure, so
        # the task's retry budget is untouched and the retry loop applies
        # normally.
        assert task.can_retry() is True
