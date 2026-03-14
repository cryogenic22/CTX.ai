"""Compression metrics: token counts and ratios.

IMPORTANT: This module provides TWO token counting methods:
  - count_tokens()       — whitespace split (fast, used internally)
  - count_bpe_tokens()   — actual BPE tokens via tiktoken (accurate, used for all reporting)

All compression ratios and cost estimates MUST use BPE tokens.
Word count is only valid as an internal heuristic — never for reporting.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class CompressionMetrics:
    """Compression measurement results."""

    token_count_source: int
    token_count_ctx: int
    compression_ratio: float
    bpe_source: int = 0
    bpe_ctx: int = 0
    bpe_compression_ratio: float = 0.0

    def to_dict(self) -> dict:
        d = {
            "word_count_source": self.token_count_source,
            "word_count_ctx": self.token_count_ctx,
            "word_compression_ratio": f"{self.compression_ratio:.1f}x",
        }
        if self.bpe_source > 0:
            d["bpe_source"] = self.bpe_source
            d["bpe_ctx"] = self.bpe_ctx
            d["bpe_compression_ratio"] = f"{self.bpe_compression_ratio:.2f}x"
        return d


def count_tokens(text: str) -> int:
    """Approximate token count using whitespace splitting.

    WARNING: This is a fast heuristic only. For .ctx output with dense
    notation, word count diverges significantly from BPE token count.
    Use count_bpe_tokens() from metrics.cost for all reporting.
    """
    return len(text.split())


def count_corpus_tokens(corpus_dir: str) -> int:
    """Count tokens across all files in a corpus directory (word-based)."""
    total = 0
    for root, _dirs, files in os.walk(corpus_dir):
        for fname in files:
            if fname.endswith((".yaml", ".yml", ".md", ".json")):
                path = os.path.join(root, fname)
                with open(path, encoding="utf-8") as f:
                    total += count_tokens(f.read())
    return total


def count_corpus_bpe(corpus_dir: str, model: str = "gpt-4o") -> int:
    """Count BPE tokens across all files in a corpus directory."""
    from .cost import count_bpe_tokens

    total = 0
    for root, _dirs, files in os.walk(corpus_dir):
        for fname in files:
            if fname.endswith((".yaml", ".yml", ".md", ".json")):
                path = os.path.join(root, fname)
                with open(path, encoding="utf-8") as f:
                    total += count_bpe_tokens(f.read(), model=model)
    return total


def measure_compression(
    source_tokens: int,
    ctx_text: str,
    *,
    source_bpe: int = 0,
    model: str = "gpt-4o",
) -> CompressionMetrics:
    """Measure compression ratio between source and ctx output.

    If source_bpe is provided, also computes BPE compression ratio.
    """
    from .cost import count_bpe_tokens

    ctx_tokens = count_tokens(ctx_text)
    ratio = source_tokens / ctx_tokens if ctx_tokens > 0 else 0.0

    bpe_ctx = 0
    bpe_ratio = 0.0
    if source_bpe > 0:
        bpe_ctx = count_bpe_tokens(ctx_text, model=model)
        bpe_ratio = source_bpe / bpe_ctx if bpe_ctx > 0 else 0.0

    return CompressionMetrics(
        token_count_source=source_tokens,
        token_count_ctx=ctx_tokens,
        compression_ratio=ratio,
        bpe_source=source_bpe,
        bpe_ctx=bpe_ctx,
        bpe_compression_ratio=bpe_ratio,
    )
