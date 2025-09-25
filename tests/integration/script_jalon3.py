#!/usr/bin/env python3
"""
Script de test basique pour valider l'implémentation du Jalon 3
Tests des fonctionnalités API & Services
"""

import requests
import json
import sys
import time
from pathlib import Path

# Configuration du test
BASE_URL = "http://localhost:8000"
TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_PASSWORD = "admin123"

def test_api_health():
    """Test du health check de base"""
    print("🔍 Test du health check...")
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Health check: OK")
            return True
        else:
            print(f"❌ Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False

def test_root_endpoint():
    """Test de l'endpoint racine"""
    print("🔍 Test de l'endpoint racine...")
    try:
        response = requests.get(f"{BASE_URL}/", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if "name" in data and data["name"] == "Mimir":
                print("✅ Endpoint racine: OK")
                return True
        print(f"❌ Endpoint racine failed: {response.status_code}")
        return False
    except Exception as e:
        print(f"❌ Endpoint racine error: {e}")
        return False

def test_detailed_health():
    """Test du health check détaillé"""
    print("🔍 Test du health check détaillé...")
    try:
        response = requests.get(f"{BASE_URL}/api/v1/health/", timeout=5)
        if response.status_code in [200, 503]:  # 503 acceptable si services non configurés
            data = response.json()
            print(f"✅ Health check détaillé: {data.get('status', 'unknown')}")
            return True
        else:
            print(f"❌ Health check détaillé failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health check détaillé error: {e}")
        return False

def test_admin_auth():
    """Test de l'authentification admin"""
    print("🔍 Test de l'authentification admin...")
    try:
        # Tentative de login
        login_data = {
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD
        }
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json=login_data,
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            if "access_token" in data:
                print("✅ Authentification admin: OK")
                return data["access_token"]

        print(f"❌ Authentification admin failed: {response.status_code}")
        if response.status_code == 401:
            print("   Vérifiez que le mot de passe admin est configuré correctement")
        return None

    except Exception as e:
        print(f"❌ Authentification admin error: {e}")
        return None

def test_chat_endpoint():
    """Test de l'endpoint de chat (sans authentification)"""
    print("🔍 Test de l'endpoint de chat...")
    try:
        chat_data = {
            "question": "Bonjour, pouvez-vous m'aider ?",
            "session_id": "test-session-123"
        }
        response = requests.post(
            f"{BASE_URL}/api/v1/chat/",
            json=chat_data,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if "answer" in data:
                print("✅ Endpoint de chat: OK")
                print(f"   Réponse: {data['answer'][:100]}...")
                return True

        print(f"❌ Endpoint de chat failed: {response.status_code}")
        return False

    except Exception as e:
        print(f"❌ Endpoint de chat error: {e}")
        return False

def test_admin_endpoints(token):
    """Test des endpoints d'administration avec authentification"""
    if not token:
        print("❌ Skip admin endpoints (pas de token)")
        return False

    print("🔍 Test des endpoints d'administration...")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Test system info
        response = requests.get(
            f"{BASE_URL}/api/v1/admin/system-info",
            headers=headers,
            timeout=5
        )

        if response.status_code == 200:
            print("✅ Admin system-info: OK")
        else:
            print(f"❌ Admin system-info failed: {response.status_code}")
            return False

        # Test cache stats
        response = requests.get(
            f"{BASE_URL}/api/v1/admin/cache/stats",
            headers=headers,
            timeout=5
        )

        if response.status_code == 200:
            print("✅ Admin cache stats: OK")
            return True
        else:
            print(f"❌ Admin cache stats failed: {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Admin endpoints error: {e}")
        return False

def test_document_endpoints(token):
    """Test des endpoints de gestion de documents"""
    if not token:
        print("❌ Skip document endpoints (pas de token)")
        return False

    print("🔍 Test des endpoints de documents...")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Test liste des documents
        response = requests.get(
            f"{BASE_URL}/api/v1/documents/",
            headers=headers,
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            print(f"✅ Liste documents: OK ({data.get('total', 0)} documents)")
            return True
        else:
            print(f"❌ Liste documents failed: {response.status_code}")
            return False

    except Exception as e:
        print(f"❌ Document endpoints error: {e}")
        return False

def test_escalation_endpoint():
    """Test de l'endpoint d'escalade"""
    print("🔍 Test de l'endpoint d'escalade...")
    try:
        escalation_data = {
            "question": "J'ai besoin d'aide humaine",
            "session_id": "test-session-123",
            "chat_history": [
                {"type": "user", "content": "Question précédente"},
                {"type": "assistant", "content": "Réponse précédente"}
            ]
        }
        response = requests.post(
            f"{BASE_URL}/api/v1/chat/escalate",
            json=escalation_data,
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            if "success" in data:
                print(f"✅ Escalade endpoint: OK (success={data['success']})")
                if not data["success"]:
                    print(f"   Note: {data.get('message', 'Email service non configuré')}")
                return True

        print(f"❌ Escalade endpoint failed: {response.status_code}")
        return False

    except Exception as e:
        print(f"❌ Escalade endpoint error: {e}")
        return False

def run_all_tests():
    """Exécute tous les tests"""
    print("🚀 Démarrage des tests du Jalon 3: API & Services")
    print("=" * 60)

    tests_passed = 0
    total_tests = 0

    # Tests de base (sans authentification)
    basic_tests = [
        ("Health Check", test_api_health),
        ("Endpoint Racine", test_root_endpoint),
        ("Health Check Détaillé", test_detailed_health),
        ("Chat Endpoint", test_chat_endpoint),
        ("Escalade Endpoint", test_escalation_endpoint),
    ]

    for test_name, test_func in basic_tests:
        total_tests += 1
        if test_func():
            tests_passed += 1
        time.sleep(0.5)  # Pause entre les tests

    # Tests d'authentification
    print("\n" + "=" * 40)
    total_tests += 1
    admin_token = test_admin_auth()
    if admin_token:
        tests_passed += 1

    # Tests avec authentification
    if admin_token:
        auth_tests = [
            ("Admin Endpoints", lambda: test_admin_endpoints(admin_token)),
            ("Document Endpoints", lambda: test_document_endpoints(admin_token)),
        ]

        for test_name, test_func in auth_tests:
            total_tests += 1
            if test_func():
                tests_passed += 1
            time.sleep(0.5)

    # Résumé
    print("\n" + "=" * 60)
    print(f"📊 Résultats: {tests_passed}/{total_tests} tests réussis")

    if tests_passed == total_tests:
        print("🎉 Tous les tests sont passés ! Jalon 3 implémenté avec succès.")
        return True
    else:
        print(f"⚠️  {total_tests - tests_passed} test(s) ont échoué.")
        print("\nConsignes de dépannage:")
        print("1. Vérifiez que le serveur FastAPI est démarré sur localhost:8000")
        print("2. Vérifiez la configuration dans .env")
        print("3. Consultez les logs du serveur pour plus de détails")
        return False

def main():
    """Point d'entrée principal"""
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Usage: python test_jalon3.py")
        print("Tests les fonctionnalités du Jalon 3: API & Services")
        print("\nAssurez-vous que:")
        print("- Le serveur FastAPI est démarré (python main.py)")
        print("- Le fichier .env est configuré")
        return

    success = run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()