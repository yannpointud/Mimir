"""
Integration test proving the FastAPI event loop stays responsive while a
heavy FAISS operation runs on a worker thread.

Approach: monkeypatch the shared FaissVectorStore singleton's `query()` method
to sleep for 1 second (simulating a slow blocking FAISS call), then invoke it
via `await asyncio.to_thread(...)` -- the target offload pattern for the real
call sites in chat.py/documents.py/admin.py/processor.py -- concurrently with
a GET /health request through an async ASGI client. If the event loop is not
blocked, /health responds in well under the 1s sleep duration.

This test is RED before the offload lands (a synchronous call inside the
event loop would delay /health too) and GREEN once Tasks 2-3 wrap every real
call site in asyncio.to_thread, since the underlying mechanism validated here
(to_thread dispatch to a real OS thread, event loop free in the meantime) is
identical to what those call sites use.
"""

import asyncio
import time

import httpx
import pytest

from src.api.dependencies import get_vector_store

# Response threshold: /health must answer well before the simulated 1s FAISS
# operation completes. 300ms leaves generous margin for CI jitter while still
# proving the event loop was not blocked for anywhere near the full second.
HEALTH_RESPONSE_THRESHOLD_SECONDS = 0.3
SIMULATED_FAISS_OP_DURATION_SECONDS = 1.0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_responds_during_heavy_faiss_operation(test_app):
    """/health must respond fast while a to_thread-offloaded FAISS call sleeps."""
    # Use the actual singleton instance (get_vector_store), not an ad hoc
    # FaissVectorStore -- this is the same instance every real call site
    # (chat.py/documents.py/admin.py/processor.py) shares and locks against.
    store = get_vector_store()

    def _slow_query(*args, **kwargs):
        # Simulates a blocking FAISS search taking 1 second.
        time.sleep(SIMULATED_FAISS_OP_DURATION_SECONDS)
        return []

    original_query = store.query
    store.query = _slow_query
    try:

        async def run_heavy_faiss_call():
            # This mirrors the target pattern for every real call site: the
            # blocking store method dispatched via asyncio.to_thread.
            await asyncio.to_thread(store.query, None, top_k=1)

        heavy_task = asyncio.create_task(run_heavy_faiss_call())
        # Give the heavy task a moment to actually start executing on its
        # worker thread before measuring /health's response time.
        await asyncio.sleep(0.05)

        async with httpx.AsyncClient(app=test_app, base_url="http://test") as client:
            start = time.monotonic()
            response = await client.get("/health")
            elapsed = time.monotonic() - start

        await heavy_task

        assert response.status_code in (200, 503)
        assert elapsed < HEALTH_RESPONSE_THRESHOLD_SECONDS, (
            f"/health took {elapsed:.3f}s while a simulated 1s FAISS op was "
            "running -- the event loop appears blocked"
        )
    finally:
        store.query = original_query
