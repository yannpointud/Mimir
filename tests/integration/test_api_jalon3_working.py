"""
Tests d'intégration pour l'API Jalon 3 - Version fonctionnelle
Stratégie "light" : tests du chemin heureux pour les endpoints principaux
"""

import pytest  # noqa: F401
import tempfile  # noqa: F401
import io  # noqa: F401
from pathlib import Path  # noqa: F401
from fastapi.testclient import TestClient
import json


def _sse_events(body):
    """Parse an SSE response body into the list of decoded `data:` events."""
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


class TestJalon3APIIntegrationWorking:
    """Tests d'intégration fonctionnels pour les endpoints principaux de l'API Jalon 3"""

    def test_health_endpoint_integration(self, test_app):
        """
        Test d'intégration : GET /health (route racine)
        Vérifie que l'endpoint de santé répond avec les champs requis
        """
        client = TestClient(test_app)
        response = client.get("/health")

        # 200 (healthy) ou 503 (unhealthy : services non configurés en test)
        # -- les deux prouvent que l'endpoint répond avec le bon contrat.
        assert response.status_code in (200, 503)
        data = response.json()

        # Champs obligatoires dans la réponse health
        required_fields = {"status", "timestamp", "success"}
        assert all(field in data for field in required_fields)

        # Types et valeurs valides
        assert isinstance(data["success"], bool)
        assert data["status"] in ["healthy", "unhealthy"]
        assert isinstance(data["timestamp"], str)

        print(f"✅ Health endpoint OK : status={data['status']}")

    def test_chat_endpoint_integration(self, test_app):
        """
        Test d'intégration : POST /chat
        Vérifie la réponse RAG avec structure correcte (sans authentification)
        """
        client = TestClient(test_app)

        chat_request = {
            "question": "Quelle est la fonction principale du système ?",
            "context_limit": 3,
            "include_sources": True
        }

        response = client.post("/api/v1/chat/stream", json=chat_request)

        # StreamingResponse returns 200; verify a well-formed SSE stream that
        # opens with a start event carrying a session id and closes with a done
        # or error event.
        assert response.status_code == 200
        events = _sse_events(response.text)
        assert events, "no SSE events received"
        assert events[0]["type"] == "start"
        assert isinstance(events[0]["session_id"], str)
        assert len(events[0]["session_id"]) > 0
        assert events[-1]["type"] in {"done", "error"}

        print(f"✅ Chat stream endpoint OK : events={len(events)}")

    def test_documents_list_without_auth(self, test_app):
        """
        Test d'intégration : GET /documents/ sans authentification
        Vérifie que l'authentification est requise (doit retourner 401/403)
        """
        client = TestClient(test_app)
        response = client.get("/api/v1/documents/")

        # Doit retourner une erreur d'authentification
        assert response.status_code in [401, 403]
        print(f"✅ Documents endpoint protégé correctement : status={response.status_code}")

    def test_admin_system_info_without_auth(self, test_app):
        """
        Test d'intégration : GET /admin/system-info sans authentification
        Vérifie la protection par authentification
        """
        client = TestClient(test_app)
        response = client.get("/api/v1/admin/system-info")

        # Doit retourner une erreur d'authentification
        assert response.status_code in [401, 403]
        print(f"✅ Admin endpoint protégé correctement : status={response.status_code}")

    def test_api_root_endpoint_integration(self, test_app):
        """
        Test d'intégration : GET / (point d'entrée de l'API)
        Vérifie les informations de base de l'API
        """
        client = TestClient(test_app)
        response = client.get("/")

        # Vérifications du chemin heureux
        assert response.status_code == 200
        data = response.json()

        # Champs attendus dans la réponse racine
        expected_fields = {"name", "description", "version", "status"}
        assert all(field in data for field in expected_fields)

        assert data["name"] == "Mimir"
        assert data["status"] == "running"
        assert isinstance(data["version"], str)

        print(f"✅ API root endpoint OK : name={data['name']}, version={data['version']}")


class TestJalon3ErrorHandlingWorking:
    """Tests d'intégration pour la gestion d'erreurs critiques"""

    def test_chat_invalid_data_integration(self, test_app):
        """
        Test d'intégration : POST /chat avec données invalides
        Vérifie la validation Pydantic
        """
        client = TestClient(test_app)

        # Question vide (doit échouer selon le modèle Pydantic)
        invalid_request = {
            "question": "",  # Invalide : trop courte (min_length=1)
            "context_limit": 5
        }

        response = client.post("/api/v1/chat/stream", json=invalid_request)

        # Doit retourner une erreur de validation
        assert response.status_code == 422  # Unprocessable Entity
        error_data = response.json()
        assert "detail" in error_data

        print(f"✅ Validation chat OK : error_type=validation, status={response.status_code}")

    def test_chat_missing_data_integration(self, test_app):
        """
        Test d'intégration : POST /chat sans question
        Vérifie la validation des champs requis
        """
        client = TestClient(test_app)

        # Requête sans le champ question requis
        invalid_request = {
            "context_limit": 5
            # question manquante
        }

        response = client.post("/api/v1/chat/stream", json=invalid_request)

        # Doit retourner une erreur de validation
        assert response.status_code == 422  # Unprocessable Entity
        error_data = response.json()
        assert "detail" in error_data

        print(f"✅ Validation champs requis OK : status={response.status_code}")

    def test_nonexistent_endpoint_integration(self, test_app):
        """
        Test d'intégration : requête vers un endpoint inexistant
        Vérifie la gestion des 404
        """
        client = TestClient(test_app)

        response = client.get("/api/v1/nonexistent")

        assert response.status_code == 404
        print(f"✅ Route inexistante gérée correctement : status={response.status_code}")


class TestJalon3SystemHealthWorking:
    """Tests d'intégration pour vérifier la santé globale du système"""

    def test_api_endpoints_accessibility(self, test_app):
        """
        Test d'intégration : accessibilité de tous les endpoints principaux
        Vérifie que les routes sont montées correctement
        """
        client = TestClient(test_app)

        endpoints_to_test = [
            ("GET", "/", (200,)),  # Root endpoint
            # Health: 200 (healthy) or 503 (unhealthy in test env) -- both
            # prove the route is mounted and responding
            ("GET", "/health", (200, 503)),
            ("POST", "/api/v1/chat/stream", (422,)),  # Chat (422 car pas de données)
            ("GET", "/api/v1/documents/", (403,)),  # Documents (403 car pas d'auth)
            ("GET", "/api/v1/admin/system-info", (403,)),  # Admin (403 car pas d'auth)
        ]

        results = []
        for method, path, expected_statuses in endpoints_to_test:
            if method == "GET":
                response = client.get(path)
            elif method == "POST":
                response = client.post(path, json={})

            results.append((path, response.status_code, expected_statuses))

            # Vérifie que le statut est celui attendu
            assert response.status_code in expected_statuses, \
                f"Endpoint {method} {path} : attendu {expected_statuses}, obtenu {response.status_code}"

        # Résumé des tests
        print("✅ Accessibilité des endpoints :")
        for path, actual, expected in results:
            print(f"  {path}: {actual} (attendu: {expected}) ✓")

    def test_api_response_consistency(self, test_app):
        """
        Test d'intégration : cohérence des réponses d'erreur
        Vérifie que les erreurs suivent un format standardisé
        """
        client = TestClient(test_app)

        # Test d'erreur de validation (422)
        response_422 = client.post("/api/v1/chat/stream", json={})
        assert response_422.status_code == 422
        error_422 = response_422.json()
        assert "detail" in error_422

        # Test d'erreur d'authentification (403)
        response_403 = client.get("/api/v1/documents/")
        assert response_403.status_code == 403

        # Test d'erreur 404
        response_404 = client.get("/api/v1/nonexistent")
        assert response_404.status_code == 404

        print("✅ Cohérence des formats d'erreur vérifiée")

    def test_performance_basic_integration(self, test_app):
        """
        Test d'intégration : performance basique des endpoints
        Vérifie que les réponses sont raisonnablement rapides
        """
        import time

        client = TestClient(test_app)

        start_time = time.time()
        response = client.get("/health")
        health_time = time.time() - start_time

        start_time = time.time()
        response = client.post("/api/v1/chat/stream", json={  # noqa: F841
            "question": "Test de performance"
        })
        chat_time = time.time() - start_time

        # Vérifications de performance (très basiques)
        assert health_time < 2.0  # Health check < 2s
        assert chat_time < 5.0    # Chat response < 5s

        print(f"✅ Performance basique OK : health={health_time:.3f}s, chat={chat_time:.3f}s")