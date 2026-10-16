"""
Tests unitaires pour le service de debug RAG
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch

from src.monitoring.rag_debug_logger import RagDebugService, _make_json_serializable


class TestMakeJsonSerializable:
    """Tests pour la fonction de sérialisation JSON"""

    def test_dict_serialization(self):
        """Test de sérialisation d'un dictionnaire"""
        data = {"key": "value", "number": 42}
        result = _make_json_serializable(data)
        assert result == {"key": "value", "number": 42}

    def test_list_serialization(self):
        """Test de sérialisation d'une liste"""
        data = [1, 2, "test", True]
        result = _make_json_serializable(data)
        assert result == [1, 2, "test", True]

    def test_path_serialization(self):
        """Test de sérialisation d'un objet Path"""
        path = Path("/test/path")
        result = _make_json_serializable(path)
        assert result == "/test/path"

    def test_nested_serialization(self):
        """Test de sérialisation d'objets imbriqués"""
        data = {"list": [1, 2, Path("/test")], "nested": {"key": "value"}}
        result = _make_json_serializable(data)
        assert result == {"list": [1, 2, "/test"], "nested": {"key": "value"}}

    def test_primitive_types(self):
        """Test de sérialisation des types primitifs"""
        assert _make_json_serializable(42) == 42
        assert _make_json_serializable(3.14) == 3.14
        assert _make_json_serializable("test") == "test"
        assert _make_json_serializable(True) is True
        assert _make_json_serializable(None) is None


class TestRagDebugService:
    """Tests pour le service de debug RAG"""

    @pytest.fixture
    def debug_service(self):
        """Fixture pour créer un service de debug"""
        with patch("src.monitoring.rag_debug_logger.Path.mkdir"):
            service = RagDebugService()
            return service

    def test_initialization(self, debug_service):
        """Test d'initialisation du service"""
        assert debug_service.enabled is False
        assert debug_service.logger is not None
        assert debug_service.logger.name == "rag_debug"

    def test_configure_enabled(self, debug_service):
        """Test de configuration du service"""
        debug_service.configure(
            enabled=True, log_prompts=True, log_context=True, log_responses=True
        )

        assert debug_service.enabled is True
        assert debug_service.log_prompts is True
        assert debug_service.log_context is True
        assert debug_service.log_responses is True

    def test_configure_disabled(self, debug_service):
        """Test de configuration avec service désactivé"""
        debug_service.configure(enabled=False)
        assert debug_service.enabled is False

    def test_log_user_request_disabled(self, debug_service):
        """Test que les logs ne sont pas créés quand le service est désactivé"""
        debug_service.enabled = False

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_user_request(
                session_id="test_session", question="Test question?", context_limit=3
            )
            mock_debug.assert_not_called()

    def test_log_user_request_enabled(self, debug_service):
        """Test de logging d'une requête utilisateur"""
        debug_service.enabled = True

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_user_request(
                session_id="test_session",
                question="Test question?",
                user_context={"user_id": "123"},
                context_limit=3,
            )

            mock_debug.assert_called_once()
            log_data = json.loads(mock_debug.call_args[0][0])

            assert log_data["event_type"] == "user_request"
            assert log_data["session_id"] == "test_session"
            assert log_data["question"] == "Test question?"
            assert log_data["question_length"] == 14
            assert log_data["context_limit"] == 3

    def test_log_vector_search_disabled(self, debug_service):
        """Test que les logs de recherche ne sont pas créés quand désactivé"""
        debug_service.enabled = False

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_vector_search(
                session_id="test_session",
                search_results=[],
                embedding_tokens=50,
                search_time_ms=100.0,
            )
            mock_debug.assert_not_called()

    def test_log_vector_search_with_results(self, debug_service):
        """Test de logging des résultats de recherche vectorielle"""
        debug_service.enabled = True

        # Mock search results
        mock_result = Mock()
        mock_result.document_id = "doc_123"
        mock_result.source = "test.pdf"
        mock_result.chunk_index = 0
        mock_result.total_chunks = 5
        mock_result.similarity_score = 0.9234
        mock_result.text = "Test chunk content" * 20  # Long text

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_vector_search(
                session_id="test_session",
                search_results=[mock_result],
                embedding_tokens=50,
                search_time_ms=123.456,
            )

            mock_debug.assert_called_once()
            log_data = json.loads(mock_debug.call_args[0][0])

            assert log_data["event_type"] == "vector_search"
            assert log_data["session_id"] == "test_session"
            assert log_data["embedding_tokens"] == 50
            assert log_data["total_found"] == 1
            assert log_data["processing_time_ms"] == 123.46
            assert log_data["best_score"] == 0.9234

    def test_log_context_building_prompts_hidden(self, debug_service):
        """Test de logging du contexte avec prompts cachés"""
        debug_service.enabled = True
        debug_service.log_prompts = False
        debug_service.log_context = False

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_context_building(
                session_id="test_session",
                system_prompt="You are a helpful assistant",
                context_text="Context information here",
                context_chunks=3,
                filtered_sources=[{"doc": "test.pdf"}],
            )

            mock_debug.assert_called_once()
            log_data = json.loads(mock_debug.call_args[0][0])

            assert log_data["event_type"] == "context_building"
            assert "[PROMPT HIDDEN" in log_data["system_prompt"]
            assert "[CONTEXT HIDDEN" in log_data["context_text"]

    def test_log_context_building_prompts_visible(self, debug_service):
        """Test de logging du contexte avec prompts visibles"""
        debug_service.enabled = True
        debug_service.log_prompts = True
        debug_service.log_context = True

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_context_building(
                session_id="test_session",
                system_prompt="You are a helpful assistant",
                context_text="Context information here",
                context_chunks=3,
                filtered_sources=[],
            )

            mock_debug.assert_called_once()
            log_data = json.loads(mock_debug.call_args[0][0])

            assert log_data["system_prompt"] == "You are a helpful assistant"
            assert log_data["context_text"] == "Context information here"

    def test_log_llm_request_disabled(self, debug_service):
        """Test que les logs LLM ne sont pas créés quand désactivé"""
        debug_service.enabled = False

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_llm_request(
                session_id="test_session",
                model="mistral-small",
                full_prompt="Full prompt text",
                user_question="Question?",
                parameters={"temperature": 0.7},
            )
            mock_debug.assert_not_called()

    def test_log_llm_request_prompt_hidden(self, debug_service):
        """Test de logging de requête LLM avec prompt caché"""
        debug_service.enabled = True
        debug_service.log_prompts = False

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_llm_request(
                session_id="test_session",
                model="mistral-small",
                full_prompt="Full prompt text",
                user_question="Question?",
                parameters={"temperature": 0.7},
            )

            mock_debug.assert_called_once()
            log_data = json.loads(mock_debug.call_args[0][0])

            assert log_data["event_type"] == "llm_request"
            assert "[PROMPT HIDDEN" in log_data["full_prompt"]

    def test_log_llm_response_disabled(self, debug_service):
        """Test que les logs de réponse LLM ne sont pas créés quand désactivé"""
        debug_service.enabled = False

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_llm_response(
                session_id="test_session",
                response="Response text",
                tokens_used=150,
                duration_ms=500.0,
                finish_reason="stop",
            )
            mock_debug.assert_not_called()

    def test_log_llm_response_hidden(self, debug_service):
        """Test de logging de réponse LLM avec réponse cachée"""
        debug_service.enabled = True
        debug_service.log_responses = False

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_llm_response(
                session_id="test_session",
                response="Response text",
                tokens_used=150,
                duration_ms=500.123,
                finish_reason="stop",
            )

            mock_debug.assert_called_once()
            log_data = json.loads(mock_debug.call_args[0][0])

            assert log_data["event_type"] == "llm_response"
            assert log_data["tokens_used"] == 150
            assert log_data["duration_ms"] == 500.12
            assert log_data["finish_reason"] == "stop"
            assert "[RESPONSE HIDDEN" in log_data["response"]

    def test_log_final_response_disabled(self, debug_service):
        """Test que les logs finaux ne sont pas créés quand désactivé"""
        debug_service.enabled = False

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_final_response(
                session_id="test_session",
                confidence_score=0.85,
                sources_count=3,
                final_sources=[],
                total_processing_time_ms=1000.0,
            )
            mock_debug.assert_not_called()

    def test_log_final_response_with_cache(self, debug_service):
        """Test de logging de la réponse finale avec cache"""
        debug_service.enabled = True

        with patch.object(debug_service.logger, "debug") as mock_debug:
            debug_service.log_final_response(
                session_id="test_session",
                confidence_score=0.8567,
                sources_count=3,
                final_sources=[{"doc": "test.pdf"}],
                total_processing_time_ms=1234.567,
                cached=True,
            )

            mock_debug.assert_called_once()
            log_data = json.loads(mock_debug.call_args[0][0])

            assert log_data["event_type"] == "final_response"
            assert log_data["confidence_score"] == 0.857
            assert log_data["sources_count"] == 3
            assert log_data["total_processing_time_ms"] == 1234.57
            assert log_data["cached"] is True

    def test_log_error_disabled(self, debug_service):
        """Test que les logs d'erreur ne sont pas créés quand désactivé"""
        debug_service.enabled = False

        with patch.object(debug_service.logger, "error") as mock_error:
            debug_service.log_error(
                session_id="test_session",
                error_type="ValueError",
                error_message="Test error",
                stage="vector_search",
            )
            mock_error.assert_not_called()

    def test_log_error_with_traceback(self, debug_service):
        """Test de logging d'erreur avec traceback"""
        debug_service.enabled = True

        with patch.object(debug_service.logger, "error") as mock_error:
            debug_service.log_error(
                session_id="test_session",
                error_type="ValueError",
                error_message="Test error",
                stage="vector_search",
                traceback_info="Traceback line 1\nTraceback line 2",
            )

            mock_error.assert_called_once()
            log_data = json.loads(mock_error.call_args[0][0])

            assert log_data["event_type"] == "error"
            assert log_data["error_type"] == "ValueError"
            assert log_data["error_message"] == "Test error"
            assert log_data["stage"] == "vector_search"
            assert "traceback" in log_data

    def test_format_log(self, debug_service):
        """Test du formatage des logs en JSON"""
        data = {"key": "value", "number": 42, "path": Path("/test")}
        result = debug_service._format_log(data)

        # Vérifier que c'est du JSON valide
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["number"] == 42
        assert parsed["path"] == "/test"
