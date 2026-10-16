"""
Oracle (b, failure paths): status codes and client-facing messages when a
collaborator fails.

Failing repositories, vector stores and ingestion processors are injected
through ``app.dependency_overrides``; the snapshot pins the HTTP status and
the JSON body (or the SSE events) returned to the client in each case.
"""

from contextlib import contextmanager
from typing import Any, Dict, Iterable

from tests.oracle.harness import FIXTURES_DIR, assert_snapshot, normalize


class _Failing:
    """Proxy raising RuntimeError on the listed methods, delegating the rest."""

    def __init__(self, target: Any, failing: Iterable[str], result: Dict[str, Any] = None):
        self._target = target
        self._failing = set(failing)
        self._result = result or {}

    def __getattr__(self, name):
        if name in self._result:
            value = self._result[name]
            return lambda *args, **kwargs: value
        if name in self._failing:
            def _raise(*args, **kwargs):
                raise RuntimeError(f"oracle failure in {name}")
            return _raise
        return getattr(self._target, name)


@contextmanager
def _override(env, dependency, factory):
    overrides = env.app.dependency_overrides
    previous = overrides.get(dependency)
    overrides[dependency] = factory
    try:
        yield
    finally:
        if previous is None:
            overrides.pop(dependency, None)
        else:
            overrides[dependency] = previous


def _record(env, response) -> Dict[str, Any]:
    return {"status": response.status_code, "body": normalize(response.json(), env.tmp_root)}


def _repo_dependency(env, repo_factory_name: str, failing: Iterable[str]):
    from src.api import dependencies
    from src.database.connection import db_manager

    real_factory = getattr(dependencies, repo_factory_name)
    sessions = []

    def factory():
        session = db_manager.get_session()
        sessions.append(session)
        return _Failing(real_factory(session), failing)

    return real_factory, factory, sessions


def test_failure_responses(oracle_env):
    from src.api import dependencies

    env = oracle_env
    client = env.client
    admin = env.admin_headers
    results = {}

    upload = env.upload(FIXTURES_DIR / "sample.txt")
    assert upload.status_code == 200
    env.drain_ingestion()

    # --- document repository failures -----------------------------------
    dep, factory, sessions = _repo_dependency(
        env, "get_document_repository", ["get_all_paginated", "get_statistics", "get_all"]
    )
    with _override(env, dep, factory):
        results["documents list"] = _record(env, client.get("/api/v1/documents/", headers=admin))
        results["documents stats"] = _record(
            env, client.get("/api/v1/documents/stats/overview", headers=admin)
        )
        results["validate consistency"] = _record(
            env,
            client.post(
                "/api/v1/documents/maintenance/validate-consistency?save_report=false",
                headers=admin,
            ),
        )
        results["rebuild with failing document listing"] = _record(
            env, client.post("/api/v1/admin/vector-store/rebuild", headers=admin)
        )
    for session in sessions:
        session.close()

    # --- audit / configuration / usage repository failures --------------
    dep, factory, sessions = _repo_dependency(env, "get_audit_log_repository", ["create_log", "get_logs_paginated"])
    with _override(env, dep, factory):
        results["cache clear"] = _record(env, client.post("/api/v1/admin/cache/clear", headers=admin))
        results["audit log"] = _record(env, client.get("/api/v1/admin/audit-log", headers=admin))
        results["login with failing audit"] = {
            "status": client.post(
                "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
            ).status_code
        }
        results["maintenance"] = _record(
            env, client.post("/api/v1/admin/maintenance?enabled=true", headers=admin)
        )
        results["logout with failing audit"] = _record(
            env, client.post("/api/v1/auth/logout", headers=admin)
        )
        results["refresh with failing audit"] = {
            "status": client.post("/api/v1/auth/refresh", headers=admin).status_code
        }
        results["delete with failing audit"] = _record(
            env, client.delete("/api/v1/documents/999", headers=admin)
        )
    for session in sessions:
        session.close()

    dep, factory, sessions = _repo_dependency(env, "get_configuration_repository", ["get_all", "set", "get"])
    with _override(env, dep, factory):
        results["configuration get"] = _record(env, client.get("/api/v1/admin/configuration", headers=admin))
        results["configuration put"] = _record(
            env, client.put("/api/v1/admin/configuration", headers=admin, json={"maintenance_mode": "true"})
        )
        results["usage with failing config"] = _record(env, client.get("/api/v1/admin/usage", headers=admin))
    for session in sessions:
        session.close()

    dep, factory, sessions = _repo_dependency(env, "get_usage_repository", ["get_today_by_model"])
    with _override(env, dep, factory):
        results["usage"] = _record(env, client.get("/api/v1/admin/usage", headers=admin))
    for session in sessions:
        session.close()

    # --- vector store failures --------------------------------------------
    broken_store = _Failing(
        env.vector_store,
        ["get_stats", "health_check", "get_document_chunks", "delete", "rebuild_vector_store"],
    )
    with _override(env, dependencies.get_vector_store, lambda: broken_store):
        results["stats with failing store"] = _record(
            env, client.get("/api/v1/documents/stats/overview", headers=admin)
        )
        results["full with failing store"] = _record(env, client.get("/api/v1/documents/1/full"))
        results["rebuild with failing store"] = _record(
            env, client.post("/api/v1/admin/vector-store/rebuild", headers=admin)
        )
        results["delete with failing store"] = _record(
            env, client.delete("/api/v1/documents/1", headers=admin)
        )
    results["documents after delete with failing store"] = _record(
        env, client.get("/api/v1/documents/", headers=admin)
    )

    # --- ingestion queue failures -------------------------------------------
    full_queue = _Failing(env.processor, [], result={"queue_document": False, "get_queue_size": 50000})
    with _override(env, dependencies.get_ingestion_processor, lambda: full_queue):
        results["upload queue full"] = _record(env, env.upload(FIXTURES_DIR / "sample.md"))
        results["admin upload queue full"] = _record(
            env, env.upload(FIXTURES_DIR / "sample.md", route="/api/v1/admin/documents/upload")
        )
    uploaded = env.upload(FIXTURES_DIR / "sample.md")
    results["upload after queue full"] = _record(env, uploaded)
    reprocess_route = f"/api/v1/documents/{uploaded.json()['id']}/reprocess"
    env.drain_ingestion()
    results["reprocess unknown after queue full"] = _record(
        env, client.post("/api/v1/documents/999/reprocess", headers=admin)
    )
    with _override(env, dependencies.get_ingestion_processor, lambda: full_queue):
        results["reprocess queue full"] = _record(env, client.post(reprocess_route, headers=admin))
    broken_queue = _Failing(env.processor, ["queue_document"])
    with _override(env, dependencies.get_ingestion_processor, lambda: broken_queue):
        results["upload queue error"] = _record(
            env, env.upload(FIXTURES_DIR / "sample.pdf")
        )
        results["admin upload queue error"] = _record(
            env, env.upload(FIXTURES_DIR / "sample.docx", route="/api/v1/admin/documents/upload")
        )
        results["reprocess queue error"] = _record(env, client.post(reprocess_route, headers=admin))
    results["documents final"] = _record(env, client.get("/api/v1/documents/", headers=admin))

    # --- chat stream failure before the pipeline -------------------------
    broken_rag = _Failing(env.rag_service, [])
    broken_rag.vector_store = _Failing(env.vector_store, ["get_corpus_version"])
    env.budget_guard.calls.clear()
    with _override(env, dependencies.get_rag_service, lambda: broken_rag):
        events = env.stream("Question pendant une panne")
    results["stream with failing corpus version"] = {
        "events": normalize(events, env.tmp_root),
        "budget_calls": list(env.budget_guard.calls),
    }
    assert_snapshot("api_failures", results)
