"""
Unit tests for Mistral gateway token usage extraction.

Covers usage extraction for cost accounting: non-stream prompt/completion split on
generate()/embed(), and streaming usage extraction via
stream_options.include_usage + usage_out sink. All aiohttp calls are mocked;
zero real Mistral network calls.
"""

import json

import pytest
from unittest.mock import AsyncMock, Mock, patch

from src.llm_interface.implementations.mistral_api import MistralAPIService


@pytest.fixture
def mistral_service():
    """Instance MistralAPIService pour les tests"""
    return MistralAPIService(
        api_key="test_api_key",
        model="mistral-small-latest",
        embedding_model="mistral-embed",
    )


class TestNonStreamUsageSplit:
    """generate() and embed() split prompt/completion tokens"""

    @pytest.mark.asyncio
    async def test_generate_splits_prompt_and_completion_tokens(self, mistral_service):
        """generate() returns prompt_tokens/completion_tokens from the usage object"""
        mock_response_data = {
            "choices": [{
                "message": {"content": "Hello, how can I help you?"},
                "finish_reason": "stop"
            }],
            "model": "mistral-small-latest",
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 70,
                "total_tokens": 100
            }
        }

        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)
            mock_response.raise_for_status = Mock()
            mock_post.return_value.__aenter__.return_value = mock_response

            response = await mistral_service.generate("Hello")

            assert response.prompt_tokens == 30
            assert response.completion_tokens == 70
            assert response.usage_tokens == 100

    @pytest.mark.asyncio
    async def test_embed_splits_prompt_tokens_zero_completion(self, mistral_service):
        """embed() returns prompt_tokens from usage, completion_tokens stays 0"""
        mock_response_data = {
            "data": [{"embedding": [0.1, 0.2, 0.3]}],
            "model": "mistral-embed",
            "usage": {"prompt_tokens": 50, "total_tokens": 50}
        }

        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)
            mock_response.raise_for_status = Mock()
            mock_post.return_value.__aenter__.return_value = mock_response

            response = await mistral_service.embed(["Hello"])

            assert response.prompt_tokens == 50
            assert response.completion_tokens == 0
            assert response.usage_tokens == 50


def _sse_lines(*chunks):
    """Build an async iterator of raw SSE byte lines from a list of chunk dicts."""
    lines = []
    for chunk in chunks:
        lines.append(f"data: {json.dumps(chunk)}".encode())
    lines.append(b"data: [DONE]")

    async def _aiter():
        for line in lines:
            yield line

    return _aiter()


class TestStreamingUsageExtraction:
    """generate_stream() sends stream_options.include_usage and
    populates usage_out from the final SSE chunk."""

    @pytest.mark.asyncio
    async def test_stream_populates_usage_out_on_complete_stream(self, mistral_service):
        """A complete stream (content chunks + final usage chunk) fills usage_out"""
        chunks = [
            {"choices": [{"delta": {"content": "Hel"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}
            },
        ]

        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.content = _sse_lines(*chunks)
            mock_post.return_value.__aenter__.return_value = mock_response

            usage_out = {}
            full_content = ""
            async for piece in mistral_service.generate_stream("Hello", usage_out=usage_out):
                full_content += piece

            assert full_content == "Hello"
            assert usage_out == {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}

            # Payload sent must request stream usage explicitly.
            call_args = mock_post.call_args
            json_data = call_args[1]['json']
            assert json_data["stream_options"] == {"include_usage": True}
            assert json_data["stream"] is True

    @pytest.mark.asyncio
    async def test_stream_leaves_usage_out_empty_when_final_usage_missing(self, mistral_service):
        """Interrupted/incomplete stream (no final usage chunk) leaves usage_out
        empty and never raises — caller falls back to estimation."""
        chunks = [
            {"choices": [{"delta": {"content": "Hi"}, "finish_reason": "stop"}]},
        ]

        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.content = _sse_lines(*chunks)
            mock_post.return_value.__aenter__.return_value = mock_response

            usage_out = {}
            full_content = ""
            async for piece in mistral_service.generate_stream("Hello", usage_out=usage_out):
                full_content += piece

            assert full_content == "Hi"
            assert usage_out == {}
