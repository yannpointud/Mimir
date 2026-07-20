"""
White-box unit tests for the RAG pipeline (RagService).

These tests exercise the RAG pipeline functions directly, in their new home
backend/src/services/rag_service.py (DEBT-01, plan 04-04). They were migrated
verbatim from tests/unit/test_api_endpoints_chat.py -- the assertions are
identical to the pre-migration versions, which is the isofunctional proof that
the extraction of the pipeline out of chat.py did not change its behaviour.

Mock-based: AsyncMock LLM service, Mock vector store / document repository /
rag_debug. No real Mistral API call, no real FAISS index.
"""

import asyncio
from unittest.mock import Mock, AsyncMock

from src.services.rag_service import _process_question_with_rag


class TestProcessQuestionWithRag:
    """Direct (white-box) tests of the _process_question_with_rag pipeline."""

    def test_process_question_with_rag_placeholder(self):
        """Test RAG processing (placeholder)."""
        # Mock dependencies
        mock_llm_service = AsyncMock()
        mock_vector_store = Mock()
        mock_document_repository = Mock()
        mock_rag_debug = Mock()

        # Mock log_user_request and other methods
        mock_rag_debug.log_user_request = Mock()
        mock_rag_debug.log_vector_search = Mock()
        mock_rag_debug.log_llm_generation = Mock()

        # Configure mocks to return expected values
        mock_vector_store.query.return_value = []
        mock_llm_service.embed.return_value = AsyncMock(embeddings=[[0.1] * 1024], usage_tokens=10)
        mock_llm_service.generate.return_value = AsyncMock(
            content="L'IA (Intelligence Artificielle) est une technologie qui simule l'intelligence humaine.",
            model="mistral",
            usage_tokens=100,
            finish_reason="stop"
        )

        # Call the function with all required parameters
        result = asyncio.run(_process_question_with_rag(
            question="Qu'est-ce que l'IA ?",
            context_limit=5,
            include_sources=True,
            session_id="session_123",
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            rag_debug=mock_rag_debug
        ))

        # Assertions
        assert isinstance(result, dict)
        assert "answer" in result
        assert "session_id" in result
        assert "confidence_score" in result
        assert "cached" in result
        assert result["session_id"] == "session_123"

    def test_process_question_with_rag_no_sources(self):
        """Test RAG processing without sources."""
        # Mock dependencies
        mock_llm_service = AsyncMock()
        mock_vector_store = Mock()
        mock_document_repository = Mock()
        mock_rag_debug = Mock()

        # Mock log methods
        mock_rag_debug.log_user_request = Mock()
        mock_rag_debug.log_vector_search = Mock()
        mock_rag_debug.log_llm_generation = Mock()

        # Configure mocks - no sources found
        mock_vector_store.query.return_value = []
        mock_llm_service.embed.return_value = AsyncMock(embeddings=[[0.1] * 1024], usage_tokens=10)
        mock_llm_service.generate.return_value = AsyncMock(
            content="Je ne peux pas répondre car aucune information pertinente n'a été trouvée.",
            model="mistral",
            usage_tokens=50,
            finish_reason="stop"
        )

        # Call the function with all required parameters
        result = asyncio.run(_process_question_with_rag(
            question="Test question",
            context_limit=3,
            include_sources=False,
            session_id="session_123",
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            rag_debug=mock_rag_debug
        ))

        # Assertions
        assert isinstance(result, dict)
        assert "sources" in result
        assert isinstance(result["sources"], list)
