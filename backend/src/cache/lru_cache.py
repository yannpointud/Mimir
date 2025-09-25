"""
LRU Cache implementation for Mimir.

This module provides a thread-safe LRU cache service using cachetools
for efficient storage and retrieval of frequently accessed data.
"""

from cachetools import LRUCache
from typing import Any, Optional, Dict, Callable
import hashlib
import json
import threading
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class CacheService:
    """
    Service de cache utilisant cachetools pour la robustesse.

    Choix pragmatique : utiliser une lib éprouvée plutôt que réinventer.
    Thread-safe et optimisé pour les cas d'usage RAG.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600):
        """
        Initialize the cache service.

        Args:
            max_size: Maximum number of entries in cache
            ttl_seconds: Time to live for cache entries in seconds
        """
        # Utilisation de cachetools.LRUCache au lieu d'une implémentation custom
        self._cache = LRUCache(maxsize=max_size)
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._ttl_seconds = ttl_seconds
        self._expiry_times = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "total_requests": 0
        }
        logger.info(f"CacheService initialized - max_size: {max_size}, ttl: {ttl_seconds}s")

    def _generate_key(self, question: str, context: str = "") -> str:
        """
        Generate cache key from question and context.

        Args:
            question: The user question
            context: Optional context information

        Returns:
            str: The generated cache key
        """
        key_data = f"{question}|{context}"
        return hashlib.md5(key_data.encode('utf-8')).hexdigest()

    def _is_expired(self, key: str) -> bool:
        """
        Check if a cache entry has expired.

        Args:
            key: The cache key

        Returns:
            bool: True if expired
        """
        if key not in self._expiry_times:
            return True

        return datetime.now() > self._expiry_times[key]

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache with TTL check.

        Args:
            key: The cache key

        Returns:
            The cached value if found and not expired, None otherwise
        """
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

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        Set value in cache with TTL.

        Args:
            key: The cache key
            value: The value to cache
            ttl: Optional TTL override in seconds
        """
        with self._lock:
            # Check if we're evicting an old entry
            if key not in self._cache and len(self._cache) >= self._cache.maxsize:
                self._stats["evictions"] += 1

            self._cache[key] = value

            # Set expiry time
            ttl_to_use = ttl if ttl is not None else self._ttl_seconds
            self._expiry_times[key] = datetime.now() + timedelta(seconds=ttl_to_use)

            logger.debug(f"Cache set: {key}, TTL: {ttl_to_use}s")

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: Optional[int] = None
    ) -> Any:
        """
        Get value from cache or compute and set it.

        Args:
            key: The cache key
            factory: Function to compute value if not cached
            ttl: Optional TTL override in seconds

        Returns:
            The cached or computed value
        """
        value = self.get(key)
        if value is not None:
            return value

        # Compute and cache the value
        value = factory()
        if value is not None:
            self.set(key, value, ttl)

        return value

    def delete(self, key: str) -> bool:
        """
        Delete a specific key from cache.

        Args:
            key: The cache key to delete

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

    def invalidate_pattern(self, pattern: str):
        """
        Invalidate all keys matching a pattern.

        Args:
            pattern: Pattern to match (simple string contains)
        """
        with self._lock:
            keys_to_delete = [key for key in self._cache.keys() if pattern in key]
            for key in keys_to_delete:
                del self._cache[key]
                if key in self._expiry_times:
                    del self._expiry_times[key]

            if keys_to_delete:
                logger.info(f"Invalidated {len(keys_to_delete)} keys matching pattern: {pattern}")

    def invalidate_all(self):
        """Clear entire cache - called when documents are updated."""
        with self._lock:
            cache_size = len(self._cache)
            self._cache.clear()
            self._expiry_times.clear()
            logger.info(f"Cache invalidated - {cache_size} entries cleared")

    def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache.

        Returns:
            int: Number of entries removed
        """
        with self._lock:
            expired_keys = [
                key for key in self._cache.keys()
                if self._is_expired(key)
            ]

            for key in expired_keys:
                del self._cache[key]
                if key in self._expiry_times:
                    del self._expiry_times[key]

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.

        Returns:
            dict: Cache statistics
        """
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
                "expired_entries": len([k for k in self._expiry_times.keys() if self._is_expired(k)])
            }

    def reset_stats(self):
        """Reset cache statistics."""
        with self._lock:
            self._stats = {
                "hits": 0,
                "misses": 0,
                "evictions": 0,
                "total_requests": 0
            }
            logger.debug("Cache statistics reset")


class ChatCacheService(CacheService):
    """
    Specialized cache service for chat responses.

    Extends CacheService with chat-specific functionality.
    """

    def __init__(self, max_size: int = 50, ttl_seconds: int = 1800):
        """
        Initialize chat cache service.

        Args:
            max_size: Maximum chat responses to cache
            ttl_seconds: TTL for chat responses (default 30 minutes)
        """
        super().__init__(max_size, ttl_seconds)
        logger.info("ChatCacheService initialized for chat response caching")

    def get_chat_response(self, question: str, context_hash: str = "") -> Optional[Dict[str, Any]]:
        """
        Get cached chat response.

        Args:
            question: The user question
            context_hash: Hash of the context used

        Returns:
            Cached response if found, None otherwise
        """
        cache_key = self._generate_key(question, context_hash)
        return self.get(cache_key)

    def set_chat_response(
        self,
        question: str,
        response: Dict[str, Any],
        context_hash: str = "",
        ttl: Optional[int] = None
    ):
        """
        Cache a chat response.

        Args:
            question: The user question
            response: The response to cache
            context_hash: Hash of the context used
            ttl: Optional TTL override
        """
        cache_key = self._generate_key(question, context_hash)
        self.set(cache_key, response, ttl)

    def invalidate_on_document_change(self, document_ids: list = None):
        """
        Invalidate cache entries when documents change.

        Args:
            document_ids: Specific document IDs that changed (future enhancement)
        """
        # For now, invalidate all chat responses when any document changes
        self.invalidate_all()
        logger.info("Chat cache invalidated due to document changes")


# Global cache instances
cache_service = CacheService()
chat_cache_service = ChatCacheService()