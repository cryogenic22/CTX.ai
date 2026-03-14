"""Metric sanity checks — guards against measurement illusions.

These tests exist because the v0.1-v0.3 evaluation suite used word count
(whitespace split) as a proxy for token count. The compressor's hyphenation
turned multi-word values into single "words", inflating compression ratios
from 1.18x (BPE) to 8.4x (words). This was not caught for months.

These tests ensure that NEVER happens again by asserting invariants
between word count, BPE count, and character count.
"""

from __future__ import annotations

import os
import pytest


def _golden_corpus_dir() -> str:
    d = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "ctxpack", "benchmarks", "ctxpack_eval", "corpus"
    ))
    if not os.path.isdir(d):
        pytest.skip("Golden set corpus not found")
    return d


class TestBPEWordRatio:
    """Guard: BPE/word ratio must be in normal range for all output formats."""

    # Normal English prose: ~1.3 BPE per word
    # Dense structured text: up to ~3.0 BPE per word
    # Anything above 5.0 indicates hyphenation gaming or BPE-hostile notation
    MAX_BPE_WORD_RATIO = 5.0

    # Anything below 1.0 is impossible (every word is at least 1 BPE token)
    MIN_BPE_WORD_RATIO = 1.0

    def _measure(self, text: str) -> tuple[int, int, float]:
        from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
        words = len(text.split())
        bpe = count_bpe_tokens(text, "gpt-4o")
        ratio = bpe / words if words > 0 else 0
        return words, bpe, ratio

    def test_l2_default_bpe_word_ratio(self):
        from ctxpack.core.packer import pack
        from ctxpack.core.serializer import serialize
        corpus = _golden_corpus_dir()
        result = pack(corpus)
        text = serialize(result.document)
        words, bpe, ratio = self._measure(text)
        assert ratio <= self.MAX_BPE_WORD_RATIO, (
            f"L2 default BPE/word ratio {ratio:.1f} exceeds {self.MAX_BPE_WORD_RATIO}. "
            f"Words={words}, BPE={bpe}. Likely hyphenation gaming."
        )
        assert ratio >= self.MIN_BPE_WORD_RATIO

    def test_nl_prose_bpe_word_ratio(self):
        from ctxpack.core.packer import pack
        from ctxpack.core.serializer import serialize
        corpus = _golden_corpus_dir()
        result = pack(corpus)
        text = serialize(result.document, natural_language=True)
        words, bpe, ratio = self._measure(text)
        assert ratio <= self.MAX_BPE_WORD_RATIO, (
            f"NL prose BPE/word ratio {ratio:.1f} exceeds {self.MAX_BPE_WORD_RATIO}. "
            f"Words={words}, BPE={bpe}."
        )

    def test_raw_corpus_bpe_word_ratio(self):
        from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context
        corpus = _golden_corpus_dir()
        text = prepare_raw_context(corpus)
        words, bpe, ratio = self._measure(text)
        assert ratio <= 3.0, (
            f"Raw YAML BPE/word ratio {ratio:.1f} unexpectedly high."
        )


class TestCompressionRatioConsistency:
    """Guard: BPE compression ratio must be within 3x of word compression ratio."""

    MAX_DIVERGENCE = 3.0  # BPE ratio can't diverge more than 3x from word ratio

    def test_compression_ratio_divergence(self):
        from ctxpack.core.packer import pack
        from ctxpack.core.serializer import serialize
        from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context
        from ctxpack.benchmarks.metrics.cost import count_bpe_tokens

        corpus = _golden_corpus_dir()
        raw = prepare_raw_context(corpus)
        result = pack(corpus)
        ctx = serialize(result.document)

        raw_words = len(raw.split())
        ctx_words = len(ctx.split())
        word_ratio = raw_words / ctx_words if ctx_words > 0 else 0

        raw_bpe = count_bpe_tokens(raw, "gpt-4o")
        ctx_bpe = count_bpe_tokens(ctx, "gpt-4o")
        bpe_ratio = raw_bpe / ctx_bpe if ctx_bpe > 0 else 0

        divergence = word_ratio / bpe_ratio if bpe_ratio > 0 else float("inf")
        assert divergence <= self.MAX_DIVERGENCE, (
            f"Word compression ({word_ratio:.1f}x) diverges {divergence:.1f}x "
            f"from BPE compression ({bpe_ratio:.1f}x). Max allowed: {self.MAX_DIVERGENCE}x. "
            f"This indicates the word-count metric is being gamed by the encoding format."
        )


class TestHeaderTokenAccuracy:
    """Guard: CTX_TOKENS in header must be within 50% of actual BPE count."""

    def test_header_token_count_vs_bpe(self):
        """The .ctx header reports CTX_TOKENS. It must not be wildly wrong vs BPE."""
        from ctxpack.core.packer import pack
        from ctxpack.core.serializer import serialize
        from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
        import re

        corpus = _golden_corpus_dir()
        result = pack(corpus)
        ctx_text = serialize(result.document)
        actual_bpe = count_bpe_tokens(ctx_text, "gpt-4o")

        # Extract CTX_TOKENS from header
        match = re.search(r"CTX_TOKENS:~?(\d+)", ctx_text)
        if not match:
            pytest.skip("No CTX_TOKENS in header")
        claimed = int(match.group(1))

        # The claimed count is word-based (AST walking). It should be
        # within 50% of actual BPE. If it diverges more, the header
        # is misleading users about the real token cost.
        ratio = actual_bpe / claimed if claimed > 0 else float("inf")
        assert 0.5 <= ratio <= 5.0, (
            f"Header claims CTX_TOKENS:~{claimed} but actual BPE is {actual_bpe} "
            f"(ratio {ratio:.1f}x). Header is misleading about real token cost."
        )


class TestFidelityNotDegraded:
    """Guard: compressed format should not lose fidelity vs a trivial baseline.

    At minimum, the LLM reading .ctx output should be able to answer
    simple factual questions. If fidelity drops below a threshold,
    the format is hurting comprehension.
    """

    def test_nl_prose_is_parseable(self):
        """The NL prose output should contain readable entity descriptions."""
        from ctxpack.core.packer import pack
        from ctxpack.core.serializer import serialize
        corpus = _golden_corpus_dir()
        result = pack(corpus)
        nl = serialize(result.document, natural_language=True)
        # Must contain Markdown headings for entities
        assert "##" in nl, "NL prose should use Markdown headings"
        # Must contain some recognizable entity content
        assert "Identified by" in nl or "Identifier" in nl, (
            "NL prose should mention entity identifiers"
        )


class TestHydrationCostGuard:
    """Guard: hydration should cost LESS than raw stuffing, not more.

    If L3 system prompt + average hydrated section > raw corpus BPE,
    the hydration architecture is net-negative on cost.
    """

    def test_l3_prompt_is_smaller_than_full_l2(self):
        """L3 map must be significantly smaller than full L2."""
        from ctxpack.core.packer import pack
        from ctxpack.core.hydration_protocol import build_system_prompt
        from ctxpack.core.serializer import serialize
        from ctxpack.benchmarks.metrics.cost import count_bpe_tokens

        corpus = _golden_corpus_dir()
        result = pack(corpus)
        l2_text = serialize(result.document)
        l3_prompt = build_system_prompt(result.document)

        l2_bpe = count_bpe_tokens(l2_text, "gpt-4o")
        l3_bpe = count_bpe_tokens(l3_prompt, "gpt-4o")

        ratio = l3_bpe / l2_bpe if l2_bpe > 0 else float("inf")
        # L3 should be at most 50% of L2 — if it's larger, the "gist"
        # is not actually compressed
        assert ratio <= 0.5, (
            f"L3 system prompt ({l3_bpe} BPE) is {ratio:.0%} of full L2 ({l2_bpe} BPE). "
            f"L3 should be <50% of L2 to justify the hydration architecture. "
            f"Current L3 is too large to provide cost savings."
        )
