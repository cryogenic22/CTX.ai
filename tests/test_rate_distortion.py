"""Tests for WS6: Rate-Distortion Experiment."""

from __future__ import annotations

import os
import pytest

from ctxpack.benchmarks.rate_distortion import RDPoint, run_rate_distortion


def _golden_corpus_dir() -> str:
    d = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "ctxpack", "benchmarks", "ctxpack_eval", "corpus"
    ))
    if not os.path.isdir(d):
        pytest.skip("Golden set corpus not found")
    return d


class TestRDOffline:
    """Tests that work without API keys — compression/token counting only."""

    def test_rd_returns_points_for_each_preset(self):
        corpus = _golden_corpus_dir()
        points = run_rate_distortion(corpus, api_key="")
        assert len(points) == 3
        assert [p.preset for p in points] == ["conservative", "balanced", "aggressive"]

    def test_rd_monotonic_compression_across_presets(self):
        corpus = _golden_corpus_dir()
        points = run_rate_distortion(corpus, api_key="")
        # Conservative has lowest compression, aggressive highest
        assert points[0].compression_ratio <= points[2].compression_ratio

    def test_rd_word_tokens_monotonic(self):
        corpus = _golden_corpus_dir()
        points = run_rate_distortion(corpus, api_key="")
        # Conservative should have >= balanced >= aggressive tokens
        assert points[0].word_tokens >= points[2].word_tokens

    def test_rd_output_has_all_required_fields(self):
        corpus = _golden_corpus_dir()
        points = run_rate_distortion(corpus, api_key="")
        for p in points:
            assert p.preset in ("conservative", "balanced", "aggressive")
            assert p.compression_ratio > 0
            assert p.bpe_tokens > 0
            assert p.word_tokens > 0
            assert p.cost_per_query >= 0

    def test_rd_bpe_tokens_are_positive(self):
        corpus = _golden_corpus_dir()
        points = run_rate_distortion(corpus, api_key="")
        for p in points:
            assert p.bpe_tokens > 0, f"BPE tokens should be positive for {p.preset}"

    def test_rd_to_dict_serializable(self):
        corpus = _golden_corpus_dir()
        points = run_rate_distortion(corpus, api_key="")
        for p in points:
            d = p.to_dict()
            assert "preset" in d
            assert "compression_ratio" in d
            assert isinstance(d["cost_per_query"], str)  # formatted as $X.XXXX

    def test_rd_no_fidelity_without_api_key(self):
        corpus = _golden_corpus_dir()
        points = run_rate_distortion(corpus, api_key="")
        for p in points:
            assert p.fidelity_rule == 0.0
            assert p.fidelity_judge == 0.0
            assert p.details == []
