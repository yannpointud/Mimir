"""
More unit tests of cache/lru_cache.py

Edge cases and advanced features of the cache.
"""

import threading
import time
from datetime import datetime, timedelta

from mimir.cache.lru_cache import CacheService


class TestCacheServiceAdvanced:
    """Advanced tests of CacheService."""

    def test_cache_service_custom_ttl(self):
        cache = CacheService(max_size=10, ttl_seconds=1)  # Very short TTL

        # Add an entry
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Wait for the expiration
        time.sleep(1.1)

        # The value should have expired
        assert cache.get("key1") is None
        assert cache._stats["misses"] == 1

    def test_cache_service_eviction(self):
        cache = CacheService(max_size=2)  # Very small cache

        # Fill the cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Check that both are present
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

        # Add a third entry (should evict the first one)
        cache.set("key3", "value3")

        # key1 should be evicted
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_cache_service_stats_tracking(self):
        cache = CacheService(max_size=5)

        # Test hits et misses
        cache.set("key1", "value1")

        # Hit
        result = cache.get("key1")
        assert result == "value1"
        assert cache._stats["hits"] == 1
        assert cache._stats["total_requests"] == 1

        # Miss
        result = cache.get("nonexistent")
        assert result is None
        assert cache._stats["misses"] == 1
        assert cache._stats["total_requests"] == 2

    def test_cache_service_thread_safety(self):
        """Test de thread safety."""
        cache = CacheService(max_size=100)
        results = []

        def worker(thread_id):
            for i in range(10):
                key = f"thread_{thread_id}_key_{i}"
                value = f"thread_{thread_id}_value_{i}"
                cache.set(key, value)
                retrieved = cache.get(key)
                results.append((key, value, retrieved))

        # Create several threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for every thread to finish
        for thread in threads:
            thread.join()

        # Check that every operation succeeded
        for _key, original_value, retrieved_value in results:
            assert original_value == retrieved_value

    def test_cache_service_update_existing_key(self):
        cache = CacheService(max_size=10)

        # Add an entry
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Update the same key
        cache.set("key1", "value2")
        assert cache.get("key1") == "value2"

        # The cache size should not have grown
        assert len(cache._cache) == 1

    def test_cache_service_clear_functionality(self):
        cache = CacheService(max_size=10)

        # Add several entries
        for i in range(5):
            cache.set(f"key{i}", f"value{i}")

        assert len(cache._cache) == 5

        # Clear the cache
        cache.invalidate_all()

        assert len(cache._cache) == 0
        assert len(cache._expiry_times) == 0

        # Check that the keys are no longer reachable
        for i in range(5):
            assert cache.get(f"key{i}") is None

    def test_cache_service_contains_check(self):
        cache = CacheService(max_size=10)

        # contains() helper (the method does not exist)
        def contains(cache, key):
            return cache.get(key) is not None

        # Missing key
        assert not contains(cache, "nonexistent")

        # Add a key
        cache.set("existing_key", "value")
        assert contains(cache, "existing_key")

        # Expired key
        cache.set("expiring_key", "value")
        # Simulate the expiration
        cache._expiry_times["expiring_key"] = datetime.now() - timedelta(seconds=3600)
        assert not contains(cache, "expiring_key")

    def test_cache_service_get_stats(self):
        cache = CacheService(max_size=10)

        # Test operations
        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("key2")  # miss

        stats = cache.get_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["total_requests"] == 2
        # The actual field name is hit_rate_percent, not hit_rate
        assert "hit_rate_percent" in stats
        assert stats["hit_rate_percent"] == 50.0  # 1/2 * 100
        assert "size" in stats  # The actual field name is size, not cache_size
        assert stats["size"] == 1

    def test_cache_service_cleanup_expired(self):
        cache = CacheService(max_size=10, ttl_seconds=1)

        # Add entries
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Simulate the expiration of key1
        cache._expiry_times["key1"] = datetime.now() - timedelta(seconds=2)

        # Trigger the cleanup
        expired_count = cache.cleanup_expired()

        # key1 should be removed, key2 should stay
        assert "key1" not in cache._cache
        assert "key2" in cache._cache
        assert "key1" not in cache._expiry_times
        assert "key2" in cache._expiry_times
        assert expired_count == 1

    def test_cache_service_memory_efficiency(self):
        cache = CacheService(max_size=1000)

        # Add many entries
        for i in range(1500):  # Plus que max_size
            cache.set(f"key_{i:04d}", f"value_{i:04d}")

        # The cache must never exceed max_size
        assert len(cache._cache) <= 1000

        # The recent entries should be present
        for i in range(1400, 1500):
            assert cache.get(f"key_{i:04d}") == f"value_{i:04d}"

    def test_cache_service_edge_cases(self):
        cache = CacheService(max_size=1)  # Cache de taille 1

        # contains() helper
        def contains(cache, key):
            return cache.get(key) is not None

        # Add None as a value
        cache.set("null_key", None)
        assert cache.get("null_key") is None
        # get() also returns None for missing keys
        # So a stored None cannot be told apart from a missing key
        # Check the cache directly instead
        assert "null_key" in cache._cache

        # Empty key
        cache.set("", "empty_key_value")
        assert cache.get("") == "empty_key_value"

        # Valeur vide
        cache.set("empty_value", "")
        assert cache.get("empty_value") == ""

    def test_cache_service_concurrent_access(self):
        cache = CacheService(max_size=50)
        errors = []

        # contains() helper
        def contains(cache, key):
            return cache.get(key) is not None

        def intensive_worker(worker_id):
            try:
                for i in range(100):
                    key = f"worker_{worker_id}_item_{i}"
                    # Mixed operations
                    cache.set(key, f"value_{i}")
                    if i % 2 == 0:
                        cache.get(key)
                    if i % 10 == 0:
                        contains(cache, key)
                    if i % 20 == 0:
                        cache.get_stats()
            except Exception as e:  # noqa: BLE001 - thread harness: collect any error for the assertion
                errors.append(f"Worker {worker_id}: {e}")

        # Lancer plusieurs workers
        threads = []
        for i in range(10):
            thread = threading.Thread(target=intensive_worker, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # No error should have occurred
        assert len(errors) == 0, f"Errors occurred: {errors}"

    def test_cache_service_performance_characteristics(self):
        cache = CacheService(max_size=1000)

        # Measure the time of many operations
        start_time = time.time()

        for i in range(1000):
            cache.set(f"perf_key_{i}", f"perf_value_{i}")

        set_time = time.time() - start_time

        start_time = time.time()

        for i in range(1000):
            cache.get(f"perf_key_{i}")

        get_time = time.time() - start_time

        # The operations should be fast (< 1s for 1000 operations)
        assert set_time < 1.0, f"Set operations too slow: {set_time}s"
        assert get_time < 1.0, f"Get operations too slow: {get_time}s"


class TestCacheServiceIntegration:
    """Integration tests of CacheService."""

    def test_cache_service_realistic_usage(self):
        cache = CacheService(max_size=20, ttl_seconds=5)

        # Simulate repeated requests
        questions = [
            "What is machine learning?",
            "How does neural network work?",
            "What is deep learning?",
            "Explain reinforcement learning",
            "What is machine learning?",  # Repeated
        ]

        # First pass - cache misses
        for _i, question in enumerate(questions):
            key = cache._generate_key(question)
            result = cache.get(key)
            if result is None:
                # Simulate an answer
                response = f"Generated response for: {question}"
                cache.set(key, response)

        # Second pass - some should be hits
        hit_count = 0
        for question in questions:
            key = cache._generate_key(question)
            result = cache.get(key)
            if result is not None:
                hit_count += 1

        # At least the repeated question should be a hit
        assert hit_count > 0

        stats = cache.get_stats()
        assert stats["hits"] > 0
        assert stats["total_requests"] > len(questions)

    def test_cache_service_with_context(self):
        cache = CacheService(max_size=10)

        question = "What is AI?"
        context1 = "Machine learning context"
        context2 = "Computer vision context"

        # Same question with different contexts
        key1 = cache._generate_key(question, context1)
        key2 = cache._generate_key(question, context2)

        # The keys should differ
        assert key1 != key2

        # Store different answers
        cache.set(key1, "AI in ML context")
        cache.set(key2, "AI in CV context")

        # Get the expected answers
        assert cache.get(key1) == "AI in ML context"
        assert cache.get(key2) == "AI in CV context"

    def test_cache_service_error_handling(self):
        """Test de gestion d'erreurs robuste."""
        cache = CacheService(max_size=10)

        # Various data types
        test_data = [
            ("string_key", "string_value"),
            ("int_key", 42),
            ("list_key", [1, 2, 3]),
            ("dict_key", {"nested": "value"}),
            ("bool_key", True),
            ("none_key", None),
        ]

        for key, value in test_data:
            cache.set(key, value)
            retrieved = cache.get(key)
            assert retrieved == value, f"Failed for {key}: {value} != {retrieved}"
