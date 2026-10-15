"""
Tests unitaires supplémentaires pour le module cache/lru_cache.py

Ces tests couvrent les cas d'edge et fonctionnalités avancées du cache.
"""

import threading
import time
from datetime import datetime, timedelta

from backend.src.cache.lru_cache import CacheService


class TestCacheServiceAdvanced:
    """Tests avancés pour CacheService."""

    def test_cache_service_custom_ttl(self):
        """Test avec TTL personnalisé."""
        cache = CacheService(max_size=10, ttl_seconds=1)  # TTL très court

        # Ajouter une entrée
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Attendre expiration
        time.sleep(1.1)

        # La valeur devrait avoir expiré
        assert cache.get("key1") is None
        assert cache._stats["misses"] == 1

    def test_cache_service_eviction(self):
        """Test d'éviction avec cache plein."""
        cache = CacheService(max_size=2)  # Cache très petit

        # Remplir le cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Vérifier que les deux sont présents
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

        # Ajouter une troisième entrée (devrait évincer la première)
        cache.set("key3", "value3")

        # key1 devrait être évincée
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_cache_service_stats_tracking(self):
        """Test du suivi des statistiques."""
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

        # Créer plusieurs threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Attendre que tous les threads se terminent
        for thread in threads:
            thread.join()

        # Vérifier que toutes les opérations ont réussi
        for _key, original_value, retrieved_value in results:
            assert original_value == retrieved_value

    def test_cache_service_update_existing_key(self):
        """Test de mise à jour d'une clé existante."""
        cache = CacheService(max_size=10)

        # Ajouter une entrée
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Mettre à jour la même clé
        cache.set("key1", "value2")
        assert cache.get("key1") == "value2"

        # La taille du cache ne devrait pas avoir augmenté
        assert len(cache._cache) == 1

    def test_cache_service_clear_functionality(self):
        """Test de la fonctionnalité de nettoyage."""
        cache = CacheService(max_size=10)

        # Ajouter plusieurs entrées
        for i in range(5):
            cache.set(f"key{i}", f"value{i}")

        assert len(cache._cache) == 5

        # Nettoyer le cache (utiliser invalidate_all au lieu de clear)
        cache.invalidate_all()

        assert len(cache._cache) == 0
        assert len(cache._expiry_times) == 0

        # Vérifier que les clés ne sont plus accessibles
        for i in range(5):
            assert cache.get(f"key{i}") is None

    def test_cache_service_contains_check(self):
        """Test de vérification d'existence de clé."""
        cache = CacheService(max_size=10)

        # Fonction helper pour contains (puisque cette méthode n'existe pas)
        def contains(cache, key):
            return cache.get(key) is not None

        # Clé inexistante
        assert not contains(cache, "nonexistent")

        # Ajouter une clé
        cache.set("existing_key", "value")
        assert contains(cache, "existing_key")

        # Clé expirée
        cache.set("expiring_key", "value")
        # Simuler expiration
        cache._expiry_times["expiring_key"] = datetime.now() - timedelta(seconds=3600)
        assert not contains(cache, "expiring_key")

    def test_cache_service_get_stats(self):
        """Test de récupération des statistiques."""
        cache = CacheService(max_size=10)

        # Opérations de test
        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("key2")  # miss

        stats = cache.get_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["total_requests"] == 2
        # Le nom réel du champ est hit_rate_percent, pas hit_rate
        assert "hit_rate_percent" in stats
        assert stats["hit_rate_percent"] == 50.0  # 1/2 * 100
        assert "size" in stats  # Le nom réel du champ est size, pas cache_size
        assert stats["size"] == 1

    def test_cache_service_cleanup_expired(self):
        """Test de nettoyage des entrées expirées."""
        cache = CacheService(max_size=10, ttl_seconds=1)

        # Ajouter des entrées
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Simuler expiration pour key1
        cache._expiry_times["key1"] = datetime.now() - timedelta(seconds=2)

        # Déclencher nettoyage (utiliser cleanup_expired au lieu de _cleanup_expired)
        expired_count = cache.cleanup_expired()

        # key1 devrait être supprimée, key2 devrait rester
        assert "key1" not in cache._cache
        assert "key2" in cache._cache
        assert "key1" not in cache._expiry_times
        assert "key2" in cache._expiry_times
        assert expired_count == 1

    def test_cache_service_memory_efficiency(self):
        """Test d'efficacité mémoire avec beaucoup d'entrées."""
        cache = CacheService(max_size=1000)

        # Ajouter beaucoup d'entrées
        for i in range(1500):  # Plus que max_size
            cache.set(f"key_{i:04d}", f"value_{i:04d}")

        # Le cache ne devrait jamais dépasser max_size
        assert len(cache._cache) <= 1000

        # Les entrées récentes devraient être présentes
        for i in range(1400, 1500):
            assert cache.get(f"key_{i:04d}") == f"value_{i:04d}"

    def test_cache_service_edge_cases(self):
        """Test des cas limites."""
        cache = CacheService(max_size=1)  # Cache de taille 1

        # Fonction helper pour contains
        def contains(cache, key):
            return cache.get(key) is not None

        # Ajouter None comme valeur
        cache.set("null_key", None)
        assert cache.get("null_key") is None
        # Problème: get() retourne None aussi pour les clés inexistantes
        # Donc on ne peut pas distinguer None stocké de clé inexistante
        # On teste plutôt en regardant directement dans le cache
        assert "null_key" in cache._cache

        # Clé vide
        cache.set("", "empty_key_value")
        assert cache.get("") == "empty_key_value"

        # Valeur vide
        cache.set("empty_value", "")
        assert cache.get("empty_value") == ""

    def test_cache_service_concurrent_access(self):
        """Test d'accès concurrent intensif."""
        cache = CacheService(max_size=50)
        errors = []

        # Fonction helper pour contains
        def contains(cache, key):
            return cache.get(key) is not None

        def intensive_worker(worker_id):
            try:
                for i in range(100):
                    key = f"worker_{worker_id}_item_{i}"
                    # Mélange d'opérations
                    cache.set(key, f"value_{i}")
                    if i % 2 == 0:
                        cache.get(key)
                    if i % 10 == 0:
                        contains(cache, key)
                    if i % 20 == 0:
                        cache.get_stats()
            except Exception as e:  # noqa: BLE001
                errors.append(f"Worker {worker_id}: {e}")

        # Lancer plusieurs workers
        threads = []
        for i in range(10):
            thread = threading.Thread(target=intensive_worker, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Aucune erreur ne devrait s'être produite
        assert len(errors) == 0, f"Errors occurred: {errors}"

    def test_cache_service_performance_characteristics(self):
        """Test des caractéristiques de performance."""
        cache = CacheService(max_size=1000)

        # Mesurer le temps pour de nombreuses opérations
        start_time = time.time()

        for i in range(1000):
            cache.set(f"perf_key_{i}", f"perf_value_{i}")

        set_time = time.time() - start_time

        start_time = time.time()

        for i in range(1000):
            cache.get(f"perf_key_{i}")

        get_time = time.time() - start_time

        # Les opérations devraient être rapides (< 1s pour 1000 opérations)
        assert set_time < 1.0, f"Set operations too slow: {set_time}s"
        assert get_time < 1.0, f"Get operations too slow: {get_time}s"


class TestCacheServiceIntegration:
    """Tests d'intégration pour CacheService."""

    def test_cache_service_realistic_usage(self):
        """Test d'usage réaliste du cache."""
        cache = CacheService(max_size=20, ttl_seconds=5)

        # Simuler des requêtes répétées
        questions = [
            "What is machine learning?",
            "How does neural network work?",
            "What is deep learning?",
            "Explain reinforcement learning",
            "What is machine learning?",  # Répétée
        ]

        # Première passe - cache misses
        for _i, question in enumerate(questions):
            key = cache._generate_key(question)
            result = cache.get(key)
            if result is None:
                # Simuler génération de réponse
                response = f"Generated response for: {question}"
                cache.set(key, response)

        # Deuxième passe - certaines devraient être des hits
        hit_count = 0
        for question in questions:
            key = cache._generate_key(question)
            result = cache.get(key)
            if result is not None:
                hit_count += 1

        # Au moins la question répétée devrait être un hit
        assert hit_count > 0

        stats = cache.get_stats()
        assert stats["hits"] > 0
        assert stats["total_requests"] > len(questions)

    def test_cache_service_with_context(self):
        """Test du cache avec contexte."""
        cache = CacheService(max_size=10)

        question = "What is AI?"
        context1 = "Machine learning context"
        context2 = "Computer vision context"

        # Même question avec contextes différents
        key1 = cache._generate_key(question, context1)
        key2 = cache._generate_key(question, context2)

        # Les clés devraient être différentes
        assert key1 != key2

        # Stocker des réponses différentes
        cache.set(key1, "AI in ML context")
        cache.set(key2, "AI in CV context")

        # Récupérer les bonnes réponses
        assert cache.get(key1) == "AI in ML context"
        assert cache.get(key2) == "AI in CV context"

    def test_cache_service_error_handling(self):
        """Test de gestion d'erreurs robuste."""
        cache = CacheService(max_size=10)

        # Tester avec des types de données variés
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
