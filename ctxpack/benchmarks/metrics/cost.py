"""Cost calculation per baseline."""

from __future__ import annotations

from dataclasses import dataclass

# Approximate pricing per 1K input tokens (USD) as of 2026
_PRICING = {
    "claude-sonnet-4-6": 0.003,
    "claude-haiku-4-5": 0.001,
    "claude-opus-4-6": 0.015,
}


@dataclass
class CostMetrics:
    """Cost measurement for a baseline."""

    input_tokens: int
    cost_per_query: float
    model: str

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "cost_per_query": f"${self.cost_per_query:.4f}",
            "model": self.model,
        }


def estimate_cost(token_count: int, model: str = "claude-sonnet-4-6") -> CostMetrics:
    """Estimate cost per query for a given token count."""
    rate = _PRICING.get(model, 0.003)
    cost = (token_count / 1000) * rate
    return CostMetrics(
        input_tokens=token_count,
        cost_per_query=cost,
        model=model,
    )
