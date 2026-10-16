"""
LRU Cache implementation for Mimir.

This module provides a thread-safe LRU cache service using cachetools
for efficient storage and retrieval of frequently accessed data.
"""

from cachetools import LRUCache
from typing import Any
from collections.abc import Callable
import hashlib
import threading
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class CacheService:
    """
    Cache service using cachetools for robustness.

    Pragmatic choice: use a proven library rather than reinventing the wheel.
    Thread-safe and optimized for RAG use cases.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600) -> None:
        # Using cachetools.LRUCache instead of a custom implementation
        self._cache: LRUCache[str, Any] = LRUCache(maxsize=max_size)
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._ttl_seconds = ttl_seconds
        self._expiry_times: dict[str, datetime] = {}
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "total_requests": 0}
        logger.info(f"CacheService initialized - max_size: {max_size}, ttl: {ttl_seconds}s")

    def _generate_key(self, question: str, context: str = "") -> str:
        key_data = f"{question}|{context}"
        return hashlib.md5(key_data.encode("utf-8")).hexdigest()

    def _is_expired(self, key: str) -> bool:
        if key not in self._expiry_times:
            return True

        return datetime.now() > self._expiry_times[key]

    def get(self, key: str) -> Any | None:
        """Get value from cache with TTL check."""
        with self._lock:
            self._stats["total_requests"] += 1

            # Check if key exists and not expired
            if key in self._cache:
                if self._is_expired(key):
                    # Expired, remove it
                    del self._cache[key]
                    if key in self._expiry_times:
                        del self._expiry_times[key]
                    self._stats["misses"] += 1
                    logger.debug(f"Cache miss (expired): {key}")
                    return None

                self._stats["hits"] += 1
                logger.debug(f"Cache hit: {key}")
                return self._cache[key]

            self._stats["misses"] += 1
            logger.debug(f"Cache miss: {key}")
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set value in cache with TTL."""
        with self._lock:
            # Check if we're evicting an old entry
            if key not in self._cache and len(self._cache) >= self._cache.maxsize:
                self._stats["evictions"] += 1

            self._cache[key] = value

            # Set expiry time
            ttl_to_use = ttl if ttl is not None else self._ttl_seconds
            self._expiry_times[key] = datetime.now() + timedelta(seconds=ttl_to_use)

            logger.debug(f"Cache set: {key}, TTL: {ttl_to_use}s")

    def get_or_set(self, key: str, factory: Callable[[], Any], ttl: int | None = None) -> Any:
        """Get value from cache or compute and set it."""
        value = self.get(key)
        if value is not None:
            return value

        # Compute and cache the value
        value = factory()
        if value is not None:
            self.set(key, value, ttl)

        return value

    def delete(self, key: str) -> bool:
        """Delete a specific key from cache.

        Returns:
            bool: True if key was found and deleted
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                if key in self._expiry_times:
                    del self._expiry_times[key]
                logger.debug(f"Cache delete: {key}")
                return True
            return False

    def invalidate_pattern(self, pattern: str) -> None:
        """Invalidate all keys containing ``pattern`` (simple substring match)."""
        with self._lock:
            keys_to_delete = [key for key in self._cache if pattern in key]
            for key in keys_to_delete:
                del self._cache[key]
                if key in self._expiry_times:
                    del self._expiry_times[key]

            if keys_to_delete:
                logger.info(f"Invalidated {len(keys_to_delete)} keys matching pattern: {pattern}")

    def invalidate_all(self) -> None:
        """Clear entire cache - called when documents are updated."""
        with self._lock:
            cache_size = len(self._cache)
            self._cache.clear()
            self._expiry_times.clear()
            logger.info(f"Cache invalidated - {cache_size} entries cleared")

    def cleanup_expired(self) -> int:
        """Remove expired entries from cache and return how many were removed."""
        with self._lock:
            expired_keys = [key for key in self._cache if self._is_expired(key)]

            for key in expired_keys:
                del self._cache[key]
                if key in self._expiry_times:
                    del self._expiry_times[key]

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring."""
        with self._lock:
            hit_rate = 0.0
            if self._stats["total_requests"] > 0:
                hit_rate = self._stats["hits"] / self._stats["total_requests"] * 100

            return {
                "size": len(self._cache),
                "max_size": self._cache.maxsize,
                "utilization_percent": len(self._cache) / self._cache.maxsize * 100,
                "hit_rate_percent": hit_rate,
                "total_requests": self._stats["total_requests"],
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "evictions": self._stats["evictions"],
                "expired_entries": len([k for k in self._expiry_times if self._is_expired(k)]),
            }

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        with self._lock:
            self._stats = {"hits": 0, "misses": 0, "evictions": 0, "total_requests": 0}
            logger.debug("Cache statistics reset")


class ChatCacheService(CacheService):
    """
    Specialized cache service for chat responses.

    Extends CacheService with chat-specific functionality.
    """

    def __init__(self, max_size: int = 50, ttl_seconds: int = 1800) -> None:
        super().__init__(max_size, ttl_seconds)
        logger.info("ChatCacheService initialized for chat response caching")

    def get_chat_response(self, question: str, context_hash: str = "") -> dict[str, Any] | None:
        """Get cached chat response."""
        cache_key = self._generate_key(question, context_hash)
        return self.get(cache_key)

    def set_chat_response(
        self,
        question: str,
        response: dict[str, Any],
        context_hash: str = "",
        ttl: int | None = None,
    ) -> None:
        """Cache a chat response."""
        cache_key = self._generate_key(question, context_hash)
        self.set(cache_key, response, ttl)

    def _generate_stream_key(self, question: str, corpus_version: str) -> str:
        """Generate a corpus-aware SSE cache key.

        Uses SHA-256 (not md5) over the normalised question plus the corpus
        version so a collision that would serve a wrong answer is
        cryptographically improbable, and so any corpus mutation
        (which changes corpus_version) yields a different key -- an implicit
        cache invalidation. The question is normalised (stripped +
        lower-cased) so trivial whitespace/case variants share one entry.
        """
        key_data = f"{question.strip().lower()}|{corpus_version}"
        return hashlib.sha256(key_data.encode("utf-8")).hexdigest()

    def get_stream_response(self, question: str, corpus_version: str) -> dict[str, Any] | None:
        """Get a cached streamed chat response for the current corpus version."""
        cache_key = self._generate_stream_key(question, corpus_version)
        return self.get(cache_key)

    def set_stream_response(
        self, question: str, corpus_version: str, payload: dict[str, Any], ttl: int | None = None
    ) -> None:
        """Cache a streamed chat response scoped to the current corpus version.

        Callers MUST invoke this only after a fully successful stream
        completion (never on an error or a mid-stream disconnect), so no
        partial entry is ever stored.
        """
        cache_key = self._generate_stream_key(question, corpus_version)
        self.set(cache_key, payload, ttl)

    def invalidate_on_document_change(self, document_ids: list[Any] | None = None) -> None:
        """Invalidate cache entries when documents change.

        ``document_ids`` is not used yet: every chat response is invalidated.
        """
        # For now, invalidate all chat responses when any document changes
        self.invalidate_all()
        logger.info("Chat cache invalidated due to document changes")


# Global cache instances
cache_service = CacheService()
chat_cache_service = ChatCacheService()
