"""
Unit tests for the pure cost-calculation module (src/cost/pricing.py).

Covers the fail-closed behavior on unpriced models and the
independent input/output pricing contract required for differentiated
per-model billing. Zero Mistral calls -- pure function only.
"""

import pytest

from mimir.cost.pricing import compute_cost_eur

PRICE_TABLE = {
    "mistral-small-latest": {"input": 0.10, "output": 0.30},
    "mistral-embed": {"input": 0.10, "output": 0.0},
}


class TestComputeCostEur:
    """Tests for compute_cost_eur."""

    @pytest.mark.parametrize(
        "model, prompt_tokens, completion_tokens, price_table, expected",
        [
            # Input-only cost (no completion tokens)
            ("mistral-small-latest", 1_000_000, 0, PRICE_TABLE, 0.10),
            # Output-only cost (no prompt tokens)
            ("mistral-small-latest", 0, 1_000_000, PRICE_TABLE, 0.30),
            # Input + output summed independently
            ("mistral-small-latest", 1_000_000, 1_000_000, PRICE_TABLE, 0.40),
            # Embedding call: all cost is input, output price is 0
            ("mistral-embed", 1_000_000, 0, PRICE_TABLE, 0.10),
        ],
    )
    def test_computes_expected_cost(
        self, model, prompt_tokens, completion_tokens, price_table, expected
    ):
        """compute_cost_eur returns the correct euro amount for known models."""
        result = compute_cost_eur(model, prompt_tokens, completion_tokens, price_table)
        assert result == pytest.approx(expected)

    def test_unpriced_model_raises_value_error(self):
        """An unpriced model must raise, never silently bill 0 (fail-closed)."""
        with pytest.raises(ValueError, match="unknown-model"):
            compute_cost_eur("unknown-model", 100, 100, PRICE_TABLE)
