"""
RAG Debug Logger - Detailed logging system for RAG interactions

This module provides comprehensive logging of the RAG pipeline for debugging and optimization.
Includes all details: user query, vector search, context, LLM calls, and final responses.
"""

import json
import logging
from datetime import datetime
from typing import Any
from pathlib import Path

from .logger import setup_logger  # noqa: F401


def _make_json_serializable(obj):
    """Recursively convert all objects to JSON-serializable types."""
    if isinstance(obj, datetime):
        # Convert datetime to ISO 8601 with UTC timezone
        return obj.isoformat() + 'Z'
    elif isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    elif isinstance(obj, Path):
        return str(obj)
    elif hasattr(obj, 'item') and callable(obj.item):  # numpy scalars
        return obj.item()
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        # For all other objects, try to convert them to string
        return str(obj)


class RagDebugService:
    """
    Debug service to fully trace RAG interactions.

    Logs all pipeline steps with detailed information for debugging and optimization.
    """

    def __init__(self):
        """Initialize RAG debug service with dedicated logger."""
        # Dedicated logger for RAG debug logs
        self.logger = self._setup_rag_debug_logger()
        self.enabled = False  # Will be set from config

    def _setup_rag_debug_logger(self) -> logging.Logger:
        """Setup dedicated logger for RAG debug logs."""
        logger = logging.getLogger("rag_debug")
        logger.setLevel(logging.DEBUG)

        # Prevent duplicate handlers
        if logger.handlers:
            return logger

        # Create logs directory if not exists
        log_dir = Path("./logs")
        log_dir.mkdir(exist_ok=True)

        # File handler for RAG debug logs
        handler = logging.FileHandler(
            log_dir / "rag_debug.log",
            encoding='utf-8'
        )
        handler.setLevel(logging.DEBUG)

        # JSON formatter for structured logs
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)

        logger.addHandler(handler)
        return logger

    def configure(self, enabled: bool, log_prompts: bool = True,
                  log_context: bool = True, log_responses: bool = True):
        """Configure debug service from settings."""
        self.enabled = enabled
        self.log_prompts = log_prompts
        self.log_context = log_context
        self.log_responses = log_responses

        if self.enabled:
            self.logger.info(self._format_log({
                "event_type": "debug_service_enabled",
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "config": {
                    "log_prompts": self.log_prompts,
                    "log_context": self.log_context,
                    "log_responses": self.log_responses
                }
            }))

    def _format_log(self, data: dict[str, Any]) -> str:
        """Format log data as JSON with proper serialization."""
        # Clean data for JSON serialization
        clean_data = _make_json_serializable(data)
        return json.dumps(clean_data, ensure_ascii=False, indent=None)

    def log_user_request(self, session_id: str, question: str,
                        user_context: dict[str, Any] | None = None,
                        context_limit: int | None = None):
        """Log incoming user request."""
        if not self.enabled:
            return

        log_data = {
            "event_type": "user_request",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "session_id": session_id,
            "question": question,
            "question_length": len(question),
            "context_limit": context_limit,
            "user_context": user_context or {}
        }

        self.logger.debug(self._format_log(log_data))

    def log_vector_search(self, session_id: str, search_results: list[Any],
                         embedding_tokens: int, search_time_ms: float):
        """Log vector search results with details."""
        if not self.enabled:
            return

        # Format search results for logging
        formatted_results = []
        for result in search_results:
            formatted_results.append({
                "document_id": str(result.document_id),
                "filename": getattr(result, 'source', 'unknown'),
                "chunk_index": getattr(result, 'chunk_index', 0),
                "total_chunks": getattr(result, 'total_chunks', 1),
                "similarity_score": round(result.similarity_score, 4),
                "chunk_text": result.text[:200] + "..." if len(result.text) > 200 else result.text,
                "chunk_length": len(result.text)
            })

        log_data = {
            "event_type": "vector_search",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "session_id": session_id,
            "embedding_tokens": embedding_tokens,
            "search_results": formatted_results,
            "total_found": len(search_results),
            "processing_time_ms": round(search_time_ms, 2),
            "best_score": round(search_results[0].similarity_score, 4) if search_results else 0.0,
            "worst_score": round(search_results[-1].similarity_score, 4) if search_results else 0.0
        }

        self.logger.debug(self._format_log(log_data))

    def log_context_building(self, session_id: str, system_prompt: str,
                           context_text: str, context_chunks: int,
                           filtered_sources: list[dict[str, Any]]):
        """Log context building with prompt and sources."""
        if not self.enabled:
            return

        log_data = {
            "event_type": "context_building",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "session_id": session_id,
            "context_chunks": context_chunks,
            "context_length": len(context_text),
            "filtered_sources": filtered_sources
        }

        # Log full prompts and context only if enabled
        if self.log_prompts:
            log_data["system_prompt"] = system_prompt
        else:
            log_data["system_prompt"] = f"[PROMPT HIDDEN - {len(system_prompt)} chars]"

        if self.log_context:
            log_data["context_text"] = context_text
        else:
            log_data["context_text"] = f"[CONTEXT HIDDEN - {len(context_text)} chars]"

        self.logger.debug(self._format_log(log_data))

    def log_llm_request(self, session_id: str, model: str, full_prompt: str,
                       user_question: str, parameters: dict[str, Any]):
        """Log LLM request with full prompt."""
        if not self.enabled:
            return

        log_data = {
            "event_type": "llm_request",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "session_id": session_id,
            "model": model,
            "user_question": user_question,
            "prompt_length": len(full_prompt),
            "parameters": parameters
        }

        # Log full prompt only if enabled
        if self.log_prompts:
            log_data["full_prompt"] = full_prompt
        else:
            log_data["full_prompt"] = f"[PROMPT HIDDEN - {len(full_prompt)} chars]"

        self.logger.debug(self._format_log(log_data))

    def log_llm_response(self, session_id: str, response: str, tokens_used: int,
                        duration_ms: float, finish_reason: str):
        """Log LLM response with metrics."""
        if not self.enabled:
            return

        log_data = {
            "event_type": "llm_response",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "session_id": session_id,
            "tokens_used": tokens_used,
            "duration_ms": round(duration_ms, 2),
            "finish_reason": finish_reason,
            "response_length": len(response)
        }

        # Log full response only if enabled
        if self.log_responses:
            log_data["response"] = response
        else:
            log_data["response"] = f"[RESPONSE HIDDEN - {len(response)} chars]"

        self.logger.debug(self._format_log(log_data))

    def log_final_response(self, session_id: str, confidence_score: float,
                          sources_count: int, final_sources: list[dict[str, Any]],
                          total_processing_time_ms: float, cached: bool = False):
        """Log final response with confidence and sources."""
        if not self.enabled:
            return

        log_data = {
            "event_type": "final_response",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "session_id": session_id,
            "confidence_score": round(confidence_score, 3),
            "sources_count": sources_count,
            "final_sources": final_sources,
            "total_processing_time_ms": round(total_processing_time_ms, 2),
            "cached": cached
        }

        self.logger.debug(self._format_log(log_data))

    def log_error(self, session_id: str, error_type: str, error_message: str,
                  stage: str, traceback_info: str | None = None):
        """Log errors in RAG pipeline."""
        if not self.enabled:
            return

        log_data = {
            "event_type": "error",
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "session_id": session_id,
            "error_type": error_type,
            "error_message": error_message,
            "stage": stage
        }

        if traceback_info:
            log_data["traceback"] = traceback_info

        self.logger.error(self._format_log(log_data))


# Global instance
rag_debug_service = RagDebugService()