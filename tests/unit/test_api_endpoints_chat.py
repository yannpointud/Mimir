"""
Unit tests for chat endpoints.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime
from fastapi import HTTPException, status
from pydantic import ValidationError

from backend.src.api.endpoints.chat import (
    router, chat, escalate_to_human, get_session_history, clear_session_history,
    ChatRequest, ChatResponse, SourceReference, EscalationRequest, EscalationResponse
)


class TestChatModels:
    """Tests for chat models."""

    def test_chat_request_model_valid(self):
        """Test valid chat request model."""
        request = ChatRequest(
            question="Qu'est-ce que l'intelligence artificielle ?",
            session_id="test_session_123",
            context_limit=5,
            include_sources=True
        )

        assert request.question == "Qu'est-ce que l'intelligence artificielle ?"
        assert request.session_id == "test_session_123"
        assert request.context_limit == 5
        assert request.include_sources is True

    def test_chat_request_model_defaults(self):
        """Test default values of request model."""
        request = ChatRequest(question="Test question")

        assert request.question == "Test question"
        assert request.session_id is None
        assert request.context_limit == 5
        assert request.include_sources is True

    def test_chat_request_model_validation_question_too_long(self):
        """Test validation with question too long."""
        long_question = "a" * 1001  # 1001 characters

        with pytest.raises(ValidationError):
            ChatRequest(question=long_question)

    def test_chat_request_model_validation_question_empty(self):
        """Test validation with empty question."""
        with pytest.raises(ValidationError):
            ChatRequest(question="")

    def test_chat_request_model_validation_context_limit_invalid(self):
        """Test validation with invalid context limit."""
        with pytest.raises(ValidationError):
            ChatRequest(question="Test", context_limit=0)  # Minimum 1

        with pytest.raises(ValidationError):
            ChatRequest(question="Test", context_limit=11)  # Maximum 10

    def test_source_reference_model(self):
        """Test source reference model."""
        source = SourceReference(
            document_id="doc_001",
            filename="test.pdf",
            chunk_text="Contenu du chunk",
            similarity_score=0.85,
            chunk_index=2,
            total_chunks=10
        )

        assert source.document_id == "doc_001"
        assert source.filename == "test.pdf"
        assert source.similarity_score == 0.85
        assert source.chunk_index == 2

    def test_chat_response_model(self):
        """Test chat response model."""
        response = ChatResponse(
            answer="Voici la réponse",
            sources=[],
            confidence_score=0.8,
            session_id="session_123",
            response_time_ms=150,
            cached=False
        )

        assert response.answer == "Voici la réponse"
        assert response.confidence_score == 0.8
        assert response.session_id == "session_123"
        assert response.response_time_ms == 150
        assert response.cached is False

    def test_escalation_request_model(self):
        """Test escalation request model."""
        request = EscalationRequest(
            question="Question complexe",
            session_id="session_123",
            chat_history=[{"role": "user", "message": "Hello"}],
            user_email="user@example.com",
            additional_context="Contexte supplémentaire"
        )

        assert request.question == "Question complexe"
        assert request.session_id == "session_123"
        assert len(request.chat_history) == 1
        assert request.user_email == "user@example.com"

    def test_escalation_response_model(self):
        """Test escalation response model."""
        response = EscalationResponse(
            success=True,
            message="Escalade réussie",
            escalation_id="ESC-20231201-ABC123"
        )

        assert response.success is True
        assert response.message == "Escalade réussie"
        assert response.escalation_id == "ESC-20231201-ABC123"


class TestChatEndpoint:
    """Tests for the main chat endpoint."""

    @pytest.fixture
    def mock_request(self):
        """Mock FastAPI request."""
        mock_req = Mock()
        mock_req.client.host = "127.0.0.1"
        mock_req.headers = {}
        return mock_req

    @pytest.fixture
    def mock_chat_cache(self):
        """Mock chat cache service."""
        return Mock()

    @pytest.fixture
    def mock_rag_debug(self):
        """Mock RAG debug service."""
        mock = Mock()
        mock.log_user_request = Mock()
        mock.log_response = Mock()
        return mock

    @pytest.fixture
    def mock_llm_service(self):
        """Mock LLM service."""
        return Mock()

    @pytest.fixture
    def mock_vector_store(self):
        """Mock vector store."""
        return Mock()

    @pytest.fixture
    def mock_document_repository(self):
        """Mock document repository."""
        return Mock()

    @patch('backend.src.api.endpoints.chat._process_question_with_rag')
    @patch('backend.src.api.endpoints.chat._generate_session_id')
    def test_chat_success_no_cache(
        self, mock_session_id, mock_process_rag, mock_request, mock_chat_cache,
        mock_rag_debug, mock_llm_service, mock_vector_store, mock_document_repository
    ):
        """Test successful chat without cache."""

        # Configure mocks
        mock_session_id.return_value = "session_123"
        mock_chat_cache.get_chat_response.return_value = None  # No cache
        mock_process_rag.return_value = {
            "answer": "Réponse générée",
            "sources": [],
            "confidence_score": 0.8,
            "session_id": "session_123",
            "cached": False,
            "timestamp": datetime.utcnow()
        }

        chat_request = ChatRequest(question="Test question")

        # Call the function
        result = asyncio.run(chat(
            request=mock_request,
            chat_request=chat_request,
            current_user=None,
            chat_cache=mock_chat_cache,
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            rag_debug=mock_rag_debug
        ))

        # Assertions
        assert result.answer == "Réponse générée"
        assert result.session_id == "session_123"
        assert result.cached is False
        assert result.confidence_score == 0.8
        mock_process_rag.assert_called_once()
        mock_chat_cache.set_chat_response.assert_called_once()

    @patch('backend.src.api.endpoints.chat._generate_session_id')
    def test_chat_success_with_cache(self, mock_session_id, mock_request, mock_chat_cache,
                                     mock_rag_debug, mock_llm_service, mock_vector_store, mock_document_repository):
        """Test successful chat with cache hit."""

        # Configure mocks
        mock_session_id.return_value = "session_123"
        cached_response = {
            "answer": "Réponse en cache",
            "sources": [],
            "confidence_score": 0.9,
            "response_time_ms": 50,
            "cached": False,  # Will be changed to True
            "timestamp": datetime.utcnow()
        }
        mock_chat_cache.get_chat_response.return_value = cached_response

        chat_request = ChatRequest(question="Test question")

        # Call the function
        result = asyncio.run(chat(
            request=mock_request,
            chat_request=chat_request,
            current_user=None,
            chat_cache=mock_chat_cache,
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            rag_debug=mock_rag_debug
        ))

        # Assertions
        assert result.answer == "Réponse en cache"
        assert result.session_id == "session_123"
        assert result.cached is True
        mock_chat_cache.get_chat_response.assert_called_once()

    @patch('backend.src.api.endpoints.chat._process_question_with_rag')
    def test_chat_with_user_context(self, mock_process_rag, mock_request, mock_chat_cache,
                                     mock_rag_debug, mock_llm_service, mock_vector_store, mock_document_repository):
        """Test chat with authenticated user."""

        # Configure mocks
        mock_chat_cache.get_chat_response.return_value = None
        mock_process_rag.return_value = {
            "answer": "Réponse avec contexte utilisateur",
            "sources": [],
            "confidence_score": 0.8,
            "session_id": "session_123",
            "cached": False,
            "timestamp": datetime.utcnow()
        }

        chat_request = ChatRequest(question="Test question")
        current_user = {"sub": "admin", "user_type": "admin"}

        # Call the function
        result = asyncio.run(chat(
            request=mock_request,
            chat_request=chat_request,
            current_user=current_user,
            chat_cache=mock_chat_cache,
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            rag_debug=mock_rag_debug
        ))

        # Assertions
        assert result.answer == "Réponse avec contexte utilisateur"

    @patch('backend.src.api.endpoints.chat._process_question_with_rag')
    def test_chat_exception_handling(self, mock_process_rag, mock_request, mock_chat_cache,
                                     mock_rag_debug, mock_llm_service, mock_vector_store, mock_document_repository):
        """Test exception handling in chat."""

        # Configure mocks
        mock_chat_cache.get_chat_response.return_value = None
        mock_process_rag.side_effect = Exception("Erreur RAG")

        chat_request = ChatRequest(question="Test question")

        # Call the function
        result = asyncio.run(chat(
            request=mock_request,
            chat_request=chat_request,
            current_user=None,
            chat_cache=mock_chat_cache,
            llm_service=mock_llm_service,
            vector_store=mock_vector_store,
            document_repository=mock_document_repository,
            rag_debug=mock_rag_debug
        ))

        # Assertions
        assert "erreur s'est produite" in result.answer
        assert result.confidence_score == 0.0
        assert result.cached is False

    def test_chat_custom_session_id(self, mock_request, mock_chat_cache,
                                     mock_rag_debug, mock_llm_service, mock_vector_store, mock_document_repository):
        """Test chat with custom session ID."""

        # Configure mocks
        mock_chat_cache.get_chat_response.return_value = None

        chat_request = ChatRequest(
            question="Test question",
            session_id="custom_session_456"
        )

        with patch('backend.src.api.endpoints.chat._process_question_with_rag') as mock_rag:
            mock_rag.return_value = {
                "answer": "Réponse",
                "sources": [],
                "confidence_score": 0.8,
                "session_id": "custom_session_456",
                "cached": False,
                "timestamp": datetime.utcnow()
            }

            # Call the function
            result = asyncio.run(chat(
                request=mock_request,
                chat_request=chat_request,
                current_user=None,
                chat_cache=mock_chat_cache,
                llm_service=mock_llm_service,
                vector_store=mock_vector_store,
                document_repository=mock_document_repository,
                rag_debug=mock_rag_debug
            ))

            # Assertions
            assert result.session_id == "custom_session_456"


class TestEscalationEndpoint:
    """Tests for the escalation endpoint."""

    @pytest.fixture
    def mock_request(self):
        """Mock FastAPI request."""
        mock_req = Mock()
        mock_req.client.host = "127.0.0.1"
        mock_req.headers = {}
        return mock_req

    @pytest.fixture
    def mock_email_service(self):
        """Mock email service."""
        return AsyncMock()

    @patch('backend.src.api.endpoints.chat._generate_escalation_id')
    @patch('backend.src.api.endpoints.chat._extract_sources_from_history')
    def test_escalate_to_human_success(
        self, mock_extract_sources, mock_escalation_id,
        mock_request, mock_email_service
    ):
        """Test successful escalation."""

        # Configure mocks
        mock_escalation_id.return_value = "ESC-20231201-ABC123"
        mock_extract_sources.return_value = ["doc1.pdf", "doc2.txt"]
        mock_email_service.send_escalation_email.return_value = True

        escalation_request = EscalationRequest(
            question="Question complexe nécessitant aide humaine",
            session_id="session_123",
            chat_history=[{"role": "user", "message": "Hello"}],
            user_email="user@example.com"
        )

        # Call the function
        result = asyncio.run(escalate_to_human(
            request=mock_request,
            escalation_request=escalation_request,
            current_user=None,
            email_service=mock_email_service
        ))

        # Assertions
        assert result.success is True
        assert result.escalation_id == "ESC-20231201-ABC123"
        assert "transmise à notre équipe" in result.message
        mock_email_service.send_escalation_email.assert_called_once()

    @patch('backend.src.api.endpoints.chat._generate_escalation_id')
    def test_escalate_to_human_email_failure(
        self, mock_escalation_id, mock_request, mock_email_service
    ):
        """Test escalation with email failure."""

        # Configure mocks
        mock_escalation_id.return_value = "ESC-20231201-ABC123"
        mock_email_service.send_escalation_email.return_value = False

        escalation_request = EscalationRequest(
            question="Question complexe",
            session_id="session_123"
        )

        # Call the function
        result = asyncio.run(escalate_to_human(
            request=mock_request,
            escalation_request=escalation_request,
            current_user=None,
            email_service=mock_email_service
        ))

        # Assertions
        assert result.success is False
        assert result.escalation_id is None
        assert "Impossible d'envoyer" in result.message

    def test_escalate_to_human_with_authenticated_user(self, mock_request, mock_email_service):
        """Test escalation with authenticated user."""

        # Configure mocks
        mock_email_service.send_escalation_email.return_value = True

        escalation_request = EscalationRequest(question="Question complexe")
        current_user = {"sub": "admin", "user_type": "admin"}

        with patch('backend.src.api.endpoints.chat._generate_escalation_id') as mock_id:
            mock_id.return_value = "ESC-20231201-ABC123"

            # Call the function
            result = asyncio.run(escalate_to_human(
                request=mock_request,
                escalation_request=escalation_request,
                current_user=current_user,
                email_service=mock_email_service
            ))

            # Assertions
            assert result.success is True

    def test_escalate_to_human_exception_handling(self, mock_request, mock_email_service):
        """Test exception handling in escalation."""

        # Configure mock to raise an exception
        mock_email_service.send_escalation_email.side_effect = Exception("Email service error")

        escalation_request = EscalationRequest(question="Question complexe")

        # Call the function
        result = asyncio.run(escalate_to_human(
            request=mock_request,
            escalation_request=escalation_request,
            current_user=None,
            email_service=mock_email_service
        ))

        # Assertions
        assert result.success is False
        assert result.escalation_id is None
        assert "erreur s'est produite" in result.message


class TestSessionHistoryEndpoints:
    """Tests for session history management endpoints."""

    def test_get_session_history_placeholder(self):
        """Test session history retrieval."""

        session_id = "test_session_123"
        current_user = None

        # Call the function
        result = asyncio.run(get_session_history(
            session_id=session_id,
            current_user=current_user
        ))

        # Assertions
        assert result["session_id"] == session_id
        assert result["messages"] == []
        assert "created_at" in result

    def test_get_session_history_with_user(self):
        """Test session history retrieval with authenticated user."""

        session_id = "test_session_123"
        current_user = {"sub": "admin", "user_type": "admin"}

        # Call the function
        result = asyncio.run(get_session_history(
            session_id=session_id,
            current_user=current_user
        ))

        # Assertions
        assert result["session_id"] == session_id

    def test_clear_session_history_placeholder(self):
        """Test session history clearing (placeholder)."""

        session_id = "test_session_123"
        current_user = None

        # Call the function
        result = asyncio.run(clear_session_history(
            session_id=session_id,
            current_user=current_user
        ))

        # Assertions
        assert result.success is True
        assert session_id in result.message
        assert "cleared" in result.message

    def test_clear_session_history_with_user(self):
        """Test session history clearing with authenticated user."""

        session_id = "test_session_123"
        current_user = {"sub": "admin", "user_type": "admin"}

        # Call the function
        result = asyncio.run(clear_session_history(
            session_id=session_id,
            current_user=current_user
        ))

        # Assertions
        assert result.success is True


class TestChatHelperFunctions:
    """Tests for chat utility functions."""

    def test_process_question_with_rag_placeholder(self):
        """Test RAG processing (placeholder)."""
        from backend.src.api.endpoints.chat import _process_question_with_rag

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
        from backend.src.api.endpoints.chat import _process_question_with_rag

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

    def test_get_client_ip_forwarded(self):
        """Test IP extraction with X-Forwarded-For header."""
        from backend.src.api.endpoints.chat import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {"X-Forwarded-For": "192.168.1.100, 10.0.0.1"}
        mock_request.client.host = "127.0.0.1"

        ip = _get_client_ip(mock_request)
        assert ip == "192.168.1.100"

    def test_get_client_ip_real_ip(self):
        """Test IP extraction with X-Real-IP header."""
        from backend.src.api.endpoints.chat import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {"X-Real-IP": "192.168.1.200"}
        mock_request.client.host = "127.0.0.1"

        ip = _get_client_ip(mock_request)
        assert ip == "192.168.1.200"

    def test_get_client_ip_direct(self):
        """Test direct IP extraction."""
        from backend.src.api.endpoints.chat import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {}
        mock_request.client.host = "192.168.1.50"

        ip = _get_client_ip(mock_request)
        assert ip == "192.168.1.50"

    def test_get_client_ip_no_client(self):
        """Test IP extraction without client."""
        from backend.src.api.endpoints.chat import _get_client_ip

        mock_request = Mock()
        mock_request.headers = {}
        mock_request.client = None

        ip = _get_client_ip(mock_request)
        assert ip == "unknown"

    def test_generate_session_id(self):
        """Test session ID generation."""
        from backend.src.api.endpoints.chat import _generate_session_id

        session_id = _generate_session_id("Test question", "127.0.0.1")

        assert isinstance(session_id, str)
        assert len(session_id) == 16  # Truncated MD5 hash

    def test_generate_cache_key(self):
        """Test cache key generation."""
        from backend.src.api.endpoints.chat import _generate_cache_key

        cache_key = _generate_cache_key("Test Question")

        assert isinstance(cache_key, str)
        assert len(cache_key) == 32  # Full MD5 hash

        # Test normalization
        key1 = _generate_cache_key("Test Question")
        key2 = _generate_cache_key("test question")
        key3 = _generate_cache_key("  TEST QUESTION  ")

        assert key1 == key2 == key3  # Case-insensitive normalization and trim

    def test_generate_escalation_id(self):
        """Test escalation ID generation."""
        from backend.src.api.endpoints.chat import _generate_escalation_id

        escalation_id = _generate_escalation_id()

        assert isinstance(escalation_id, str)
        assert escalation_id.startswith("ESC-")
        assert len(escalation_id.split("-")) == 3  # ESC-timestamp-hash

    def test_extract_sources_from_history_with_sources(self):
        """Test source extraction from history with sources."""
        from backend.src.api.endpoints.chat import _extract_sources_from_history

        chat_history = [
            {"type": "user", "message": "Question"},
            {
                "type": "assistant",
                "message": "Réponse",
                "sources": [
                    {"filename": "doc1.pdf", "chunk_text": "Contenu 1"},
                    {"filename": "doc2.txt", "chunk_text": "Contenu 2"}
                ]
            },
            {
                "type": "assistant",
                "message": "Autre réponse",
                "sources": ["doc3.md"]
            }
        ]

        sources = _extract_sources_from_history(chat_history)

        assert "doc1.pdf" in sources
        assert "doc2.txt" in sources
        assert "doc3.md" in sources
        assert len(sources) == 3

    def test_extract_sources_from_history_no_sources(self):
        """Test source extraction from history without sources."""
        from backend.src.api.endpoints.chat import _extract_sources_from_history

        chat_history = [
            {"type": "user", "message": "Question"},
            {"type": "assistant", "message": "Réponse sans sources"}
        ]

        sources = _extract_sources_from_history(chat_history)
        assert sources == []

    def test_extract_sources_from_history_empty(self):
        """Test source extraction from empty history."""
        from backend.src.api.endpoints.chat import _extract_sources_from_history

        sources = _extract_sources_from_history([])
        assert sources == []


class TestChatIntegration:
    """Integration tests for chat endpoints."""

    @patch('backend.src.api.endpoints.chat._process_question_with_rag')
    @patch('backend.src.api.endpoints.chat._generate_session_id')
    def test_full_chat_workflow(self, mock_session_id, mock_process_rag):
        """Test full chat workflow."""

        # Configure mocks
        mock_session_id.return_value = "session_123"
        mock_process_rag.return_value = {
            "answer": "Réponse complète avec sources",
            "sources": [
                {
                    "document_id": "doc_001",
                    "filename": "guide.pdf",
                    "chunk_text": "Contenu pertinent",
                    "similarity_score": 0.9,
                    "chunk_index": 1,
                    "total_chunks": 5
                }
            ],
            "confidence_score": 0.9,
            "session_id": "session_123",
            "cached": False,
            "timestamp": datetime.utcnow()
        }

        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        mock_cache = Mock()
        mock_cache.get_chat_response.return_value = None

        # Additional required mocks
        mock_llm = Mock()
        mock_vector = Mock()
        mock_repo = Mock()
        mock_rag_debug = Mock()
        mock_rag_debug.log_user_request = Mock()
        mock_rag_debug.log_response = Mock()

        chat_request = ChatRequest(
            question="Question détaillée nécessitant sources",
            context_limit=5,
            include_sources=True
        )

        # Call the function
        result = asyncio.run(chat(
            request=mock_request,
            chat_request=chat_request,
            current_user=None,
            chat_cache=mock_cache,
            llm_service=mock_llm,
            vector_store=mock_vector,
            document_repository=mock_repo,
            rag_debug=mock_rag_debug
        ))

        # Full assertions
        assert result.answer == "Réponse complète avec sources"
        assert len(result.sources) == 1
        assert result.sources[0].filename == "guide.pdf"
        assert result.confidence_score == 0.9
        assert result.session_id == "session_123"
        assert result.cached is False

    @patch('backend.src.api.endpoints.chat._generate_escalation_id')
    def test_full_escalation_workflow(self, mock_escalation_id):
        """Test full escalation workflow."""

        # Configure mocks
        mock_escalation_id.return_value = "ESC-20231201-ABC123"

        mock_request = Mock()
        mock_request.client.host = "192.168.1.100"
        mock_request.headers = {"X-Forwarded-For": "203.0.113.1"}

        mock_email_service = AsyncMock()
        mock_email_service.send_escalation_email.return_value = True

        escalation_request = EscalationRequest(
            question="Question très complexe nécessitant expertise humaine",
            session_id="session_123",
            chat_history=[
                {"type": "user", "message": "Question initiale"},
                {"type": "assistant", "message": "Réponse partielle", "sources": ["doc1.pdf"]}
            ],
            user_email="user@company.com",
            additional_context="Contexte métier spécifique"
        )

        current_user = {"sub": "john.doe", "user_type": "user"}

        # Call the function
        result = asyncio.run(escalate_to_human(
            request=mock_request,
            escalation_request=escalation_request,
            current_user=current_user,
            email_service=mock_email_service
        ))

        # Full assertions
        assert result.success is True
        assert result.escalation_id == "ESC-20231201-ABC123"
        assert "transmise à notre équipe" in result.message

        # Verify email service call
        call_args = mock_email_service.send_escalation_email.call_args
        assert call_args[1]["user_question"] == escalation_request.question
        assert call_args[1]["chat_history"] == escalation_request.chat_history
        assert call_args[1]["user_info"]["user_email"] == "user@company.com"
        assert call_args[1]["user_info"]["ip_address"] == "203.0.113.1"
