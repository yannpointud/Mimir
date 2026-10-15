"""
BudgetGuard: thin session-managing service wrapping UsageRepository's atomic
reserve/finalize/release primitives.

Each public method opens its OWN short-lived DB session via
db_manager.get_session_context() rather than reusing a caller-supplied
session. This matters for two reasons:
  - reserve() must commit the reservation BEFORE the caller issues the
    network call to Mistral (once a StreamingResponse has been
    returned with an implicit 200, it is too late to turn it into a 429 --
    the reservation has to be durable first, independently of whatever
    session the endpoint itself is using).
  - Concurrency: each operation stays independent, no session is shared
    across reserve/finalize/release calls or across concurrent requests.
"""

from dataclasses import dataclass
from datetime import datetime

from src.config import settings
from src.database.connection import db_manager
from src.database.repository import ConfigurationRepository, UsageRepository
from src.shared.errors import BudgetExceeded

# Historical name of the budget-exhausted error, still imported by callers.
BudgetExceededError = BudgetExceeded


@dataclass
class BudgetReservation:
    """
    Carries the ledger date key and the flat estimate that was reserved, so
    a later finalize()/release() call knows which ledger row and how much
    to adjust.
    """

    today: str
    estimate_eur: float


class BudgetGuard:
    """
    Reserve/finalize/release the daily LLM spend budget, on top of
    UsageRepository's atomic ledger primitives.
    """

    def _effective_cap(self, session) -> float:
        """
        Effective daily cap: the Admin > Configuration hot override for key
        'daily_budget_eur' if present, else the .env default
        (settings.daily_budget_eur). Proves the hot Admin override wins.
        """
        override = ConfigurationRepository(session).get("daily_budget_eur")
        if override is not None:
            return float(override.value)
        return settings.daily_budget_eur

    def reserve(self, call_type: str) -> BudgetReservation | None:
        """
        Attempt to reserve today's flat per-type budget estimate.

        Args:
            call_type: 'chat' or 'embedding' -- selects the flat estimate
                from settings (budget_reservation_chat_eur /
                budget_reservation_embedding_eur). Deliberately independent
                of the price table (pricing.py), so even a model absent
                from the price table still consumes budget at reservation
                time (no free bypass via an unpriced model).

        Returns:
            A BudgetReservation if the reservation was accepted, or None if
            it would exceed the effective daily cap.
        """
        if call_type == "chat":
            estimate_eur = settings.budget_reservation_chat_eur
        elif call_type == "embedding":
            estimate_eur = settings.budget_reservation_embedding_eur
        else:
            raise ValueError(f"Unknown call_type '{call_type}' for budget reservation")

        today = datetime.utcnow().strftime("%Y-%m-%d")

        with db_manager.get_session_context() as session:
            cap_eur = self._effective_cap(session)
            accepted = UsageRepository(session).reserve(today, estimate_eur, cap_eur)

        if not accepted:
            return None
        return BudgetReservation(today=today, estimate_eur=estimate_eur)

    def finalize(self, reservation: BudgetReservation, actual_cost_eur: float) -> None:
        """
        Apply the real-vs-estimate delta to the ledger. No cap condition --
        the call already happened, spent_eur may end up slightly above the
        cap (expected).
        """
        delta_eur = actual_cost_eur - reservation.estimate_eur
        with db_manager.get_session_context() as session:
            UsageRepository(session).finalize(reservation.today, delta_eur)

    def release(self, reservation: BudgetReservation) -> None:
        """
        Roll back a reservation whose Mistral call failed, subtracting the
        reserved estimate from the ledger.
        """
        with db_manager.get_session_context() as session:
            UsageRepository(session).release(reservation.today, reservation.estimate_eur)


# Module-level singleton, mirrors the cache_service/email_service pattern.
budget_guard = BudgetGuard()
