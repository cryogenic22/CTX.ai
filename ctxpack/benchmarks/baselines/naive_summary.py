"""Baseline 2: Naive summary — truncate to match ctxpack token budget."""

from __future__ import annotations


def prepare_naive_context(raw_text: str, target_tokens: int) -> str:
    """Truncate raw text to approximately target_tokens words."""
    words = raw_text.split()
    if len(words) <= target_tokens:
        return raw_text
    return " ".join(words[:target_tokens])
