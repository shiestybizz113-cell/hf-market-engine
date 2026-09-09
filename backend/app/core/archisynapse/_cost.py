"""Cost estimation — shared between ai.py and archisynapse registry."""

_MODEL_RATES = {
    "gpt-4o-mini": (0.15, 0.60),
    "grok-3-mini": (0.30, 1.00),
}
_DEFAULT_RATES = (0.30, 1.00)


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    in_rate, out_rate = _MODEL_RATES.get(model, _DEFAULT_RATES)
    return (in_tokens / 1_000_000 * in_rate) + (out_tokens / 1_000_000 * out_rate)
