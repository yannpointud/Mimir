"""
Oracle (b): JSON responses of the main endpoints (health, auth, documents,
admin, chat side routes), status codes included.

Each test drives a fresh isolated instance through a fixed scenario and
compares the normalised responses with a frozen snapshot. Machine-dependent
payloads (system metrics, disk usage, log files, cache counters) are pinned by
their structure only.
"""

import hashlib
from typing import Any, Dict, Optional

from tests.oracle.harness import (
    FIXTURES_DIR,
    ORACLE_ADMIN_PASSWORD,
    assert_snapshot,
    normalize,
    shape,
)


def _record(env, response, mode: str = "json", keep: Optional[callable] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"status": response.status_code}
    if mode == "keys":
        # Content read from log files: only the top-level keys are stable.
        entry["keys"] = {key: type(value).__name__ for key, value in sorted(response.json().items())}
    elif mode == "json":
        body = response.json()
        if keep is not None:
            body = keep(body)
        entry["body"] = normalize(body, env.tmp_root)
    elif mode == "shape":
        entry["shape"] = shape(response.json())
    elif mode == "bytes":
        entry["sha256"] = hashlib.sha256(response.content).hexdigest()
        entry["content_type"] = response.headers.get("content-type")
        entry["content_disposition"] = response.headers.get("content-disposition")
    return entry


def _sorted_list(body: Dict[str, Any], *path: str) -> Dict[str, Any]:
    """Sort a list built from a Python set (iteration order is hash-seeded)."""
    node = body
    for key in path[:-1]:
        node = node[key]
    if isinstance(node.get(path[-1]), list):
        node[path[-1]] = sorted(node[path[-1]])
    return body


# --------------------------------------------------------------------------
# Health and root
# --------------------------------------------------------------------------

def _full_health(body: Dict[str, Any]) -> Dict[str, Any]:
    cache = body.get("checks", {}).get("cache", {})
    for key in ("main_cache", "chat_cache"):
        if key in cache:
            cache[key] = shape(cache[key])
    return body


def test_health_and_root_responses(oracle_env):
    env = oracle_env
    client = env.client
    results = {
        "GET /": _record(env, client.get("/")),
        "GET /api/v1/health/live": _record(env, client.get("/api/v1/health/live")),
        "GET /api/v1/health/ready": _record(env, client.get("/api/v1/health/ready")),
        "GET /api/v1/health/database": _record(env, client.get("/api/v1/health/database")),
        "GET /api/v1/health/": _record(env, client.get("/api/v1/health/"), keep=_full_health),
        "GET /health": _record(env, client.get("/health"), keep=_full_health),
        "GET /api/v1/health/cache": _record(env, client.get("/api/v1/health/cache"), mode="shape"),
        "GET /api/v1/health/disk-usage": _record(
            env, client.get("/api/v1/health/disk-usage"), mode="shape"
        ),
        "GET /api/v1/logs/frontend/health": _record(
            env, client.get("/api/v1/logs/frontend/health"), mode="shape"
        ),
        "POST /api/v1/logs/frontend": _record(
            env,
            client.post(
                "/api/v1/logs/frontend",
                json={
                    "timestamp": "2026-01-01T00:00:00Z",
                    "level": "INFO",
                    "module": "oracle",
                    "message": "oracle frontend log",
                },
            ),
        ),
        "POST /api/v1/logs/frontend (invalid)": _record(
            env, client.post("/api/v1/logs/frontend", json={"level": "INFO"})
        ),
    }
    assert_snapshot("api_health_root", results)


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

def test_auth_responses(oracle_env):
    env = oracle_env
    client = env.client
    results = {}

    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": ORACLE_ADMIN_PASSWORD}
    )
    results["login ok"] = _record(env, login)
    fresh_token = login.json()["access_token"]
    fresh_headers = {"Authorization": f"Bearer {fresh_token}"}

    results["login wrong password"] = _record(
        env, client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
    )
    results["login unknown user"] = _record(
        env,
        client.post(
            "/api/v1/auth/login", json={"username": "root", "password": ORACLE_ADMIN_PASSWORD}
        ),
    )
    results["login missing field"] = _record(
        env, client.post("/api/v1/auth/login", json={"username": "admin"})
    )
    results["me admin"] = _record(env, client.get("/api/v1/auth/me", headers=fresh_headers))
    results["me reader"] = _record(env, client.get("/api/v1/auth/me", headers=env.user_headers))
    results["me no token"] = _record(env, client.get("/api/v1/auth/me"))
    results["me invalid token"] = _record(
        env, client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid-token"})
    )
    results["me basic scheme"] = _record(
        env, client.get("/api/v1/auth/me", headers={"Authorization": "Basic YWRtaW46eA=="})
    )
    results["verify-admin admin"] = _record(
        env, client.post("/api/v1/auth/verify-admin", headers=env.admin_headers)
    )
    results["verify-admin reader"] = _record(
        env, client.post("/api/v1/auth/verify-admin", headers=env.user_headers)
    )
    results["refresh"] = _record(
        env, client.post("/api/v1/auth/refresh", headers=env.admin_headers)
    )
    results["logout"] = _record(env, client.post("/api/v1/auth/logout", headers=env.admin_headers))
    results["logout no token"] = _record(env, client.post("/api/v1/auth/logout"))
    results["change-password wrong current"] = _record(
        env,
        client.post(
            "/api/v1/auth/change-password",
            headers=env.admin_headers,
            json={"current_password": "wrong", "new_password": "N3w-Passw0rd!"},
        ),
    )
    results["change-password weak new"] = _record(
        env,
        client.post(
            "/api/v1/auth/change-password",
            headers=env.admin_headers,
            json={"current_password": ORACLE_ADMIN_PASSWORD, "new_password": "abc"},
        ),
    )
    results["change-password reader"] = _record(
        env,
        client.post(
            "/api/v1/auth/change-password",
            headers=env.user_headers,
            json={"current_password": "x", "new_password": "y"},
        ),
    )
    assert_snapshot("api_auth", results)


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

def _stats_overview(body: Dict[str, Any]) -> Dict[str, Any]:
    return _sorted_list(body, "storage_info", "supported_extensions")


def test_document_responses(oracle_env):
    env = oracle_env
    client = env.client
    admin = env.admin_headers
    results = {}

    txt = FIXTURES_DIR / "sample.txt"
    md = FIXTURES_DIR / "sample.md"
    results["upload txt"] = _record(env, env.upload(txt))
    results["upload md preserved"] = _record(env, env.upload(md, preserve=True))
    results["upload duplicate"] = _record(env, env.upload(txt))
    results["upload empty"] = _record(env, env.upload(FIXTURES_DIR / "empty.txt", content=b""))
    results["upload unsupported"] = _record(
        env, env.upload(FIXTURES_DIR / "notes.csv", content=b"a,b\n1,2\n")
    )
    results["upload invalid name"] = _record(
        env, env.upload(FIXTURES_DIR / "..%2f..%2fpasswd.txt", content=b"x")
    )
    results["upload no token"] = _record(
        env,
        client.post(
            "/api/v1/documents/upload",
            files={"file": ("x.txt", b"hello", "text/plain")},
        ),
    )
    results["upload reader"] = _record(
        env,
        client.post(
            "/api/v1/documents/upload",
            headers=env.user_headers,
            files={"file": ("x.txt", b"hello", "text/plain")},
        ),
    )
    env.drain_ingestion()

    results["list"] = _record(env, client.get("/api/v1/documents/", headers=admin))
    results["list paginated"] = _record(
        env, client.get("/api/v1/documents/?limit=1&offset=1", headers=admin)
    )
    results["list filtered"] = _record(
        env, client.get("/api/v1/documents/?status_filter=indexed&search=sample", headers=admin)
    )
    results["list no token"] = _record(env, client.get("/api/v1/documents/"))
    results["get 1"] = _record(env, client.get("/api/v1/documents/1", headers=admin))
    results["get 999"] = _record(env, client.get("/api/v1/documents/999", headers=admin))
    results["full 1 (anonymous reader)"] = _record(env, client.get("/api/v1/documents/1/full"))
    results["full 999"] = _record(env, client.get("/api/v1/documents/999/full"))
    results["download 2"] = _record(env, client.get("/api/v1/documents/2/download"), mode="bytes")
    results["download 999"] = _record(env, client.get("/api/v1/documents/999/download"))
    results["stats overview"] = _record(
        env, client.get("/api/v1/documents/stats/overview", headers=admin), keep=_stats_overview
    )
    results["preserve on 1"] = _record(
        env, client.patch("/api/v1/documents/1/preserve?preserve=true", headers=admin)
    )
    results["preserve off 1"] = _record(
        env, client.patch("/api/v1/documents/1/preserve?preserve=false", headers=admin)
    )
    results["preserve 999"] = _record(
        env, client.patch("/api/v1/documents/999/preserve?preserve=true", headers=admin)
    )
    results["delete protected 2"] = _record(
        env, client.delete("/api/v1/documents/2", headers=admin)
    )
    results["reprocess 1"] = _record(
        env, client.post("/api/v1/documents/1/reprocess", headers=admin)
    )
    results["reprocess 999"] = _record(
        env, client.post("/api/v1/documents/999/reprocess", headers=admin)
    )
    env.drain_ingestion()
    results["get 1 after reprocess"] = _record(env, client.get("/api/v1/documents/1", headers=admin))
    results["validate consistency"] = _record(
        env,
        client.post(
            "/api/v1/documents/maintenance/validate-consistency?save_report=false",
            headers=admin,
        ),
    )
    results["delete force 2"] = _record(
        env, client.delete("/api/v1/documents/2?force=true", headers=admin)
    )
    results["delete 1"] = _record(env, client.delete("/api/v1/documents/1", headers=admin))
    results["delete 999"] = _record(env, client.delete("/api/v1/documents/999", headers=admin))
    results["list after delete"] = _record(env, client.get("/api/v1/documents/", headers=admin))
    results["stats overview after delete"] = _record(
        env, client.get("/api/v1/documents/stats/overview", headers=admin), keep=_stats_overview
    )
    assert_snapshot("api_documents", results)


# --------------------------------------------------------------------------
# Administration
# --------------------------------------------------------------------------

def _configuration(body: Dict[str, Any]) -> Dict[str, Any]:
    return _sorted_list(body, "application_config", "supported_file_extensions")


def test_admin_responses(oracle_env):
    env = oracle_env
    client = env.client
    admin = env.admin_headers
    results = {}

    from src.cache.lru_cache import cache_service, chat_cache_service

    cache_service.invalidate_all()
    chat_cache_service.invalidate_all()

    results["system-info"] = _record(env, client.get("/api/v1/admin/system-info", headers=admin), mode="shape")
    results["system-info reader"] = _record(
        env, client.get("/api/v1/admin/system-info", headers=env.user_headers)
    )
    results["system-info no token"] = _record(env, client.get("/api/v1/admin/system-info"))
    results["cache stats"] = _record(env, client.get("/api/v1/admin/cache/stats", headers=admin), mode="shape")
    results["cache clear all"] = _record(env, client.post("/api/v1/admin/cache/clear", headers=admin))
    results["cache clear chat"] = _record(
        env, client.post("/api/v1/admin/cache/clear?cache_type=chat", headers=admin)
    )
    results["configuration"] = _record(
        env, client.get("/api/v1/admin/configuration", headers=admin), keep=_configuration
    )
    results["configuration update"] = _record(
        env,
        client.put(
            "/api/v1/admin/configuration",
            headers=admin,
            json={"maintenance_mode": "false", "daily_budget_eur": "12.5"},
        ),
    )
    results["configuration update masked"] = _record(
        env,
        client.put("/api/v1/admin/configuration", headers=admin, json={"mistral_api_key": "********"}),
    )
    results["configuration update invalid key"] = _record(
        env, client.put("/api/v1/admin/configuration", headers=admin, json={"secret": "x"})
    )
    results["configuration update bad body"] = _record(
        env, client.put("/api/v1/admin/configuration", headers=admin, json={"maintenance_mode": 1})
    )
    results["config alias"] = _record(
        env, client.get("/api/v1/admin/config", headers=admin), keep=_configuration
    )
    results["config alias update"] = _record(
        env,
        client.put("/api/v1/admin/config", headers=admin, json={"vector_search_threshold": "0.4"}),
    )
    results["configuration after update"] = _record(
        env, client.get("/api/v1/admin/configuration", headers=admin), keep=_configuration
    )
    results["usage"] = _record(env, client.get("/api/v1/admin/usage", headers=admin))
    results["usage bad days"] = _record(
        env, client.get("/api/v1/admin/usage?days_back=0", headers=admin)
    )
    results["maintenance on"] = _record(
        env,
        client.post("/api/v1/admin/maintenance?enabled=true&message=Oracle", headers=admin),
    )
    results["maintenance off"] = _record(
        env, client.post("/api/v1/admin/maintenance?enabled=false", headers=admin)
    )
    results["test-email"] = _record(
        env, client.post("/api/v1/admin/test-email?test_email=oracle@example.com", headers=admin)
    )
    results["audit-log config_update"] = _record(
        env, client.get("/api/v1/admin/audit-log?action_filter=config_update", headers=admin)
    )
    results["audit-log maintenance"] = _record(
        env,
        client.get(
            "/api/v1/admin/audit-log?action_filter=maintenance_mode_toggle&limit=1", headers=admin
        ),
    )

    txt = FIXTURES_DIR / "sample.txt"
    results["admin upload"] = _record(env, env.upload(txt, route="/api/v1/admin/documents/upload"))
    results["admin upload duplicate"] = _record(
        env, env.upload(txt, route="/api/v1/admin/documents/upload")
    )
    results["admin upload empty"] = _record(
        env, env.upload(FIXTURES_DIR / "empty.txt", route="/api/v1/admin/documents/upload", content=b"")
    )
    results["admin upload invalid name"] = _record(
        env,
        env.upload(FIXTURES_DIR / "script.exe", route="/api/v1/admin/documents/upload", content=b"x"),
    )
    results["admin upload via documents route duplicate"] = _record(env, env.upload(txt))
    env.drain_ingestion()
    results["admin documents"] = _record(env, client.get("/api/v1/admin/documents", headers=admin))
    results["admin documents page 2"] = _record(
        env, client.get("/api/v1/admin/documents?page=2&limit=1", headers=admin)
    )
    results["admin documents stats"] = _record(
        env, client.get("/api/v1/admin/documents/stats", headers=admin)
    )
    results["metrics chat"] = _record(env, client.get("/api/v1/admin/metrics/chat", headers=admin), mode="keys")
    results["analytics usage"] = _record(
        env, client.get("/api/v1/admin/analytics/usage", headers=admin), mode="keys"
    )
    results["logs"] = _record(env, client.get("/api/v1/admin/logs?limit=5", headers=admin), mode="keys")
    results["logs bad limit"] = _record(env, client.get("/api/v1/admin/logs?limit=0", headers=admin))
    results["vector-store rebuild"] = _record(
        env, client.post("/api/v1/admin/vector-store/rebuild", headers=admin)
    )
    results["vector-store rebuild reader"] = _record(
        env, client.post("/api/v1/admin/vector-store/rebuild", headers=env.user_headers)
    )
    assert_snapshot("api_admin", results)


# --------------------------------------------------------------------------
# Chat side routes
# --------------------------------------------------------------------------

def test_chat_side_responses(oracle_env):
    env = oracle_env
    client = env.client
    results = {
        "history": _record(env, client.get("/api/v1/chat/sessions/oracle-session/history")),
        "clear": _record(env, client.delete("/api/v1/chat/sessions/oracle-session")),
        "escalate": _record(
            env,
            client.post(
                "/api/v1/chat/escalate",
                json={
                    "question": "Question sans réponse",
                    "session_id": "oracle-session",
                    "chat_history": [
                        {"type": "user", "content": "Bonjour"},
                        {"type": "assistant", "content": "Réponse", "sources": [{"filename": "a.md"}]},
                    ],
                    "user_email": "user@example.com",
                },
            ),
        ),
        "escalate invalid": _record(env, client.post("/api/v1/chat/escalate", json={})),
        "stream empty question": _record(
            env, client.post("/api/v1/chat/stream", json={"question": ""})
        ),
        "stream question too long": _record(
            env, client.post("/api/v1/chat/stream", json={"question": "x" * 1001})
        ),
        "stream bad context_limit": _record(
            env, client.post("/api/v1/chat/stream", json={"question": "ok", "context_limit": 11})
        ),
    }

    env.budget_guard.exhausted = True
    try:
        results["stream budget exceeded"] = _record(
            env, client.post("/api/v1/chat/stream", json={"question": "Budget ?"})
        )
    finally:
        env.budget_guard.exhausted = False
    results["budget guard calls"] = {"calls": list(env.budget_guard.calls)}
    assert_snapshot("api_chat_side", results)
