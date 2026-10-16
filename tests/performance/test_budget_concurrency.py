"""
Concurrency proof for the daily budget cap: 10 parallel reserve() calls against a daily
budget cap that only affords 5 must yield EXACTLY 5 acceptances -- the
anti-TOCTOU contract implemented by UsageRepository.reserve() as a single
conditional UPDATE ... WHERE.

Mirrors the concurrency structure of tests/performance/test_faiss_concurrency.py:
independent OS-level DB connections driven via asyncio.gather over
asyncio.to_thread, NOT the conftest.py `test_session` fixture (that fixture
wraps everything in one rollback-only transaction on a single connection,
which cannot exercise real multi-writer SQLite serialization).

The global db_manager singleton is temporarily redirected to a fresh
temporary SQLite file for the duration of this test (restored in the fixture
teardown below) so the proof uses real db_manager.get_session() semantics
without writing synthetic ledger rows into the developer's actual project
database (data/sqlite/mimir.db).
"""

import asyncio

import pytest

from mimir.database.connection import db_manager
from mimir.database.models import LlmBudgetLedger
from mimir.database.repository import UsageRepository
from mimir.shared.clock import utc_now

ESTIMATE_EUR = 1.0
CAP_EUR = 5.0  # affords exactly 5 reservations of ESTIMATE_EUR
N_WORKERS = 10


def _reserve_worker(today: str) -> bool:
    """Runs in its own thread with its own independent DB session/connection
    (via db_manager.get_session()) -- never shared with another worker."""
    session = db_manager.get_session()
    try:
        usage_repo = UsageRepository(session)
        return usage_repo.reserve(today, ESTIMATE_EUR, CAP_EUR)
    finally:
        session.close()


def _release_worker(today: str) -> None:
    session = db_manager.get_session()
    try:
        usage_repo = UsageRepository(session)
        usage_repo.release(today, ESTIMATE_EUR)
    finally:
        session.close()


@pytest.mark.asyncio
@pytest.mark.performance
async def test_ten_parallel_reservations_cap_five_yields_exactly_five(isolated_db_manager):
    """10 concurrent reserve() calls against a cap affording 5 -> exactly 5
    True, 5 False; final spent_eur == 5 * ESTIMATE_EUR (no over-commit, no
    lost update)."""
    today = utc_now().strftime("%Y-%m-%d")

    results = await asyncio.gather(
        *[asyncio.to_thread(_reserve_worker, today) for _ in range(N_WORKERS)]
    )

    assert sum(1 for r in results if r) == 5
    assert sum(1 for r in results if not r) == 5

    verify_session = db_manager.get_session()
    try:
        ledger = verify_session.query(LlmBudgetLedger).filter_by(date=today).first()
        assert ledger is not None
        assert ledger.spent_eur == pytest.approx(5 * ESTIMATE_EUR)
    finally:
        verify_session.close()


@pytest.mark.asyncio
@pytest.mark.performance
async def test_release_frees_a_slot_for_a_subsequent_reservation(isolated_db_manager):
    """After 5 successful reserves exhaust the cap, a release() must free
    exactly one slot so a 6th reserve() then succeeds."""
    today = utc_now().strftime("%Y-%m-%d")

    first_five = await asyncio.gather(
        *[asyncio.to_thread(_reserve_worker, today) for _ in range(5)]
    )
    assert all(first_five)

    sixth_before_release = await asyncio.to_thread(_reserve_worker, today)
    assert sixth_before_release is False

    await asyncio.to_thread(_release_worker, today)

    sixth_after_release = await asyncio.to_thread(_reserve_worker, today)
    assert sixth_after_release is True
