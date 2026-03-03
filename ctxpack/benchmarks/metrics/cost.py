"""Cost calculation per baseline."""

from __future__ import annotations

from dataclasses import dataclass

# Approximate pricing per 1K input tokens (USD) as of 2026
_PRICING = {
    "claude-sonnet-4-6": 0.003,
    "claude-sonnet-4-20250514": 0.003,
    "claude-sonnet-4-5-20250929": 0.003,
    "claude-haiku-4-5": 0.001,
    "claude-haiku-4-5-20251001": 0.001,
    "claude-opus-4-6": 0.015,
    "gpt-4o": 0.0025,
    "gpt-4o-mini": 0.00015,
    "gpt-5.2": 0.005,
    "o4-mini": 0.0011,
    "gemini-2.5-pro": 0.00125,
    "gemini-2.5-flash": 0.00015,
    "gemini-2.5-flash-lite": 0.0,
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


# Model → tiktoken encoding mapping
_MODEL_ENCODING = {
    "gpt-4o": "cl100k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-5.2": "o200k_base",
    "gpt-5.2-pro": "o200k_base",
    "o3": "o200k_base",
    "o4-mini": "o200k_base",
    # Claude / Gemini use ~4 chars/token estimate (no public tokenizer)
}


def count_bpe_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count BPE tokens for a given text and model.

    Uses tiktoken for OpenAI models, falls back to len(text)//4 estimate.
    """
    encoding_name = _MODEL_ENCODING.get(model)
    if encoding_name:
        try:
            import tiktoken
            enc = tiktoken.get_encoding(encoding_name)
            return len(enc.encode(text))
        except (ImportError, Exception):
            pass
    # Fallback: ~4 chars per BPE token (standard English+symbols estimate)
    return max(1, len(text) // 4)


def estimate_cost_bpe(text: str, model: str = "claude-sonnet-4-6") -> CostMetrics:
    """Estimate cost using actual BPE token counts instead of word-split.

    For OpenAI models, uses tiktoken for exact counts.
    For Claude/Gemini, uses ~4 chars/token estimate.
    """
    bpe_tokens = count_bpe_tokens(text, model=model)
    rate = _PRICING.get(model, 0.003)
    cost = (bpe_tokens / 1000) * rate
    return CostMetrics(
        input_tokens=bpe_tokens,
        cost_per_query=cost,
        model=model,
    )
