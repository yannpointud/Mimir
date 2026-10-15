"""
Unit tests for the corpus-aware SSE cache primitives.

Covers the ChatCacheService stream methods added on top of the existing md5
non-stream methods:
  - get_stream_response / set_stream_response use a SHA-256 key derived from
    the normalised question plus the corpus version.
  - A different corpus version for the same question yields a different key,
    so a set with an old version is a miss after the corpus mutates (implicit
    invalidation).
  - Key derivation normalises case/whitespace.
  - The key is a 64-char SHA-256 hex digest.

The existing md5 non-stream methods (get_chat_response/set_chat_response) are
left untouched and are not re-tested here.
"""

import pytest

from backend.src.cache.lru_cache import ChatCacheService


@pytest.fixture
def chat_cache():
    """A small ChatCacheService with a long TTL for deterministic tests."""
    return ChatCacheService(max_size=50, ttl_seconds=3600)


class TestStreamCacheKeyDerivation:
    """The SHA-256 stream key is corpus-version-sensitive and normalised."""

    def test_stream_key_is_64_char_sha256_hex(self, chat_cache):
        """The derived stream key is a 64-char lowercase hex SHA-256 digest."""
        key = chat_cache._generate_stream_key("What is Mimir?", "v1")

        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_stream_key_normalises_case_and_whitespace(self, chat_cache):
        """Case and surrounding whitespace do not change the key."""
        base = chat_cache._generate_stream_key("What is Mimir?", "v1")
        upper = chat_cache._generate_stream_key("WHAT IS MIMIR?", "v1")
        padded = chat_cache._generate_stream_key("   What is Mimir?   ", "v1")

        assert base == upper == padded

    def test_stream_key_changes_with_corpus_version(self, chat_cache):
        """Same question, different corpus version -> different key."""
        key_v1 = chat_cache._generate_stream_key("What is Mimir?", "v1")
        key_v2 = chat_cache._generate_stream_key("What is Mimir?", "v2")

        assert key_v1 != key_v2

    def test_stream_key_changes_with_question(self, chat_cache):
        """Different question, same corpus version -> different key."""
        key_a = chat_cache._generate_stream_key("Question A", "v1")
        key_b = chat_cache._generate_stream_key("Question B", "v1")

        assert key_a != key_b


class TestStreamCacheGetSet:
    """get_stream_response / set_stream_response round-trip and invalidation."""

    def test_set_then_get_same_version_returns_payload(self, chat_cache):
        """A payload stored for a version is retrievable at that version."""
        payload = {
            "answer": "Mimir is a RAG assistant.",
            "sources": [{"document_id": 1, "filename": "doc.pdf"}],
            "confidence_score": 0.87,
        }
        chat_cache.set_stream_response("What is Mimir?", "v1", payload)

        result = chat_cache.get_stream_response("What is Mimir?", "v1")

        assert result == payload

    def test_old_version_is_a_miss_after_corpus_change(self, chat_cache):
        """After the corpus version changes, the same question misses -- the
        old entry is not served (implicit invalidation)."""
        payload = {"answer": "stale answer", "sources": [], "confidence_score": 0.5}
        chat_cache.set_stream_response("What is Mimir?", "v1", payload)

        # Corpus mutated -> version token now "v2".
        result = chat_cache.get_stream_response("What is Mimir?", "v2")

        assert result is None

    def test_get_stream_response_normalises_question(self, chat_cache):
        """A case/whitespace variant of the same question hits the entry."""
        payload = {"answer": "answer", "sources": [], "confidence_score": 0.9}
        chat_cache.set_stream_response("What is Mimir?", "v1", payload)

        result = chat_cache.get_stream_response("  WHAT IS MIMIR?  ", "v1")

        assert result == payload

    def test_stream_and_md5_methods_use_distinct_keyspaces(self, chat_cache):
        """The SHA-256 stream methods and the md5 non-stream methods do not
        collide: a stream set is not visible to the non-stream getter."""
        chat_cache.set_stream_response(
            "shared question",
            "v1",
            {"answer": "stream", "sources": [], "confidence_score": 0.5},
        )

        # The non-stream md5 getter (context_hash="") must not see it.
        assert chat_cache.get_chat_response("shared question", "") is None
