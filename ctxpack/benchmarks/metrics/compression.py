"""Compression metrics: token counts and ratios."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class CompressionMetrics:
    """Compression measurement results."""

    token_count_source: int
    token_count_ctx: int
    compression_ratio: float

    def to_dict(self) -> dict:
        return {
            "token_count_source": self.token_count_source,
            "token_count_ctx": self.token_count_ctx,
            "compression_ratio": f"{self.compression_ratio:.1f}x",
        }


def count_tokens(text: str) -> int:
    """Approximate token count using whitespace splitting."""
    return len(text.split())


def count_corpus_tokens(corpus_dir: str) -> int:
    """Count tokens across all files in a corpus directory."""
    total = 0
    for root, _dirs, files in os.walk(corpus_dir):
        for fname in files:
            if fname.endswith((".yaml", ".yml", ".md")):
                path = os.path.join(root, fname)
                with open(path, encoding="utf-8") as f:
                    total += count_tokens(f.read())
    return total


def measure_compression(source_tokens: int, ctx_text: str) -> CompressionMetrics:
    """Measure compression ratio between source and ctx output."""
    ctx_tokens = count_tokens(ctx_text)
    ratio = source_tokens / ctx_tokens if ctx_tokens > 0 else 0.0
    return CompressionMetrics(
        token_count_source=source_tokens,
        token_count_ctx=ctx_tokens,
        compression_ratio=ratio,
    )
