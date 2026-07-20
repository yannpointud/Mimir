"""
UsageTracker: prices and persists a single LLM call's usage row.

Orchestrates pricing.compute_cost_eur() -> UsageRepository.create_usage_entry(),
opening its own short-lived DB session (db_manager.get_session_context()),
mirroring BudgetGuard's session lifecycle. Deliberately does NOT import
src.llm_interface: mistral_api.py stays free of any DB/session coupling
(see 03-PATTERNS.md), and UsageTracker stays free of any HTTP/gateway
coupling -- both directions of the layering boundary are enforced.
"""

import logging
from typing import Optional

from src.config import settings
from src.cost.pricing import compute_cost_eur
from src.database.connection import db_manager
from src.database.repository import UsageRepository

logger = logging.getLogger(__name__)


class UsageTracker:
    """Prices an LLM call and persists the resulting usage row."""

    def record(
        self,
        call_type: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated: bool = False,
        session_id: Optional[str] = None,
    ) -> float:
        """
        Price and persist one LLM call's usage.

        Args:
            call_type: 'chat' or 'embedding'
            model: Model name as billed
            prompt_tokens: Input tokens consumed by the call
            completion_tokens: Output tokens produced by the call (0 for
                embedding calls)
            estimated: True if token counts/cost are estimated (e.g. a
                streaming disconnect before the real usage chunk arrived),
                False on a fully-observed call
            session_id: Optional session or "doc:{id}" identifier

        Returns:
            The computed cost in euros (the flat reservation estimate for
            the call_type if the model has no price entry -- see below).
        """
        try:
            cost_eur = compute_cost_eur(
                model, prompt_tokens, completion_tokens, settings.llm_price_table
            )
        except ValueError:
            # Fail LOUD but not CRASHING: keep the flat reservation estimate
            # as the billed cost so a later BudgetGuard.finalize() does NOT
            # refund the reservation (finalize applies actual - estimate, so
            # returning 0 here would net the ledger to zero per call and
            # silently disable the daily cap for an unpriced model). Billing
            # the flat estimate keeps the cap accumulating -- the real
            # T-03-04 mitigation -- while estimated=True flags the row as
            # non-authoritative until llm_price_table is fixed.
            cost_eur = (
                settings.budget_reservation_chat_eur
                if call_type == "chat"
                else settings.budget_reservation_embedding_eur
            )
            estimated = True
            logger.error(
                f"No price configured for model '{model}' -- recording usage "
                f"with flat reservation estimate cost_eur={cost_eur} "
                f"(estimated=True); update llm_price_table"
            )

        total_tokens = prompt_tokens + completion_tokens

        with db_manager.get_session_context() as session:
            UsageRepository(session).create_usage_entry(
                call_type=call_type,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_eur=cost_eur,
                estimated=estimated,
                session_id=session_id,
            )

        return cost_eur


# Module-level singleton, mirrors the cache_service/email_service pattern.
usage_tracker = UsageTracker()
