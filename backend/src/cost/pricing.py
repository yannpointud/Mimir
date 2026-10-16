"""
Pure cost calculation module for AI usage accounting.

Contains no DB access and no imports from src.database or src.llm_interface:
it is a pure function of (model, tokens, price grid) -> cost in euros.
"""


def compute_cost_eur(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    price_table: dict[str, dict[str, float]],
) -> float:
    """
    Compute the cost in euros of an LLM call from its token counts and a price grid.

    Args:
        model: Model identifier as billed by the provider (e.g. "mistral-small-latest").
        prompt_tokens: Number of input/prompt tokens consumed by the call.
        completion_tokens: Number of output/completion tokens produced by the call
            (0 for embedding calls, which have no completion).
        price_table: Mapping of model name to {"input": eur_per_1m_tokens, "output": eur_per_1m_tokens}.
            Prices are expressed in euros per 1,000,000 tokens.

    Returns:
        The cost of the call in euros, computed as the sum of the input and
        output contributions (each independently priced).

    Raises:
        ValueError: If `model` has no entry in `price_table`. This is
            deliberate fail-closed behavior: an unpriced model must raise an
            alert rather than silently bill 0, which would bypass the daily
            budget cap without anyone noticing.
    """
    prices = price_table.get(model)
    if prices is None:
        raise ValueError(f"No price configured for model '{model}'")

    return (prompt_tokens / 1_000_000) * prices["input"] + (completion_tokens / 1_000_000) * prices[
        "output"
    ]
