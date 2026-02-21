"""Tests for the evaluation framework."""

import os
import json
import pytest

from ctxpack.benchmarks.eval_config import EvalConfig
from ctxpack.benchmarks.metrics.compression import count_tokens, measure_compression
from ctxpack.benchmarks.metrics.cost import estimate_cost
from ctxpack.benchmarks.metrics.conflict import measure_conflicts
from ctxpack.benchmarks.baselines.raw_stuffing import prepare_raw_context
from ctxpack.benchmarks.baselines.naive_summary import prepare_naive_context
from ctxpack.benchmarks.runner import run_eval, save_results
from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize


GOLDEN_SET = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ctxpack", "benchmarks", "golden_set",
)

SAMPLE_CORPUS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample-corpus"
)


class TestCompressionMetrics:
    def test_count_tokens(self):
        assert count_tokens("hello world foo bar") == 4

    def test_measure_compression(self):
        m = measure_compression(1000, "a b c d e f g h i j")
        assert m.token_count_source == 1000
        assert m.token_count_ctx == 10
        assert m.compression_ratio == 100.0


class TestCostMetrics:
    def test_estimate_cost(self):
        c = estimate_cost(10000, model="claude-sonnet-4-6")
        assert c.input_tokens == 10000
        assert c.cost_per_query > 0

    def test_cost_scales_with_tokens(self):
        c1 = estimate_cost(1000)
        c2 = estimate_cost(10000)
        assert c2.cost_per_query > c1.cost_per_query


class TestConflictMetrics:
    def test_perfect_detection(self):
        m = measure_conflicts(3, 3, 3)
        assert m.precision == 1.0
        assert m.recall == 1.0

    def test_partial_recall(self):
        m = measure_conflicts(4, 2, 2)
        assert m.precision == 1.0
        assert m.recall == 0.5


class TestBaselines:
    def test_raw_stuffing(self):
        raw = prepare_raw_context(SAMPLE_CORPUS)
        assert len(raw) > 0
        assert "customer" in raw.lower()

    def test_naive_summary_truncation(self):
        raw = "word " * 1000
        naive = prepare_naive_context(raw, 100)
        assert count_tokens(naive) == 100


class TestEvalRunner:
    def test_run_eval_no_fidelity(self):
        """Run eval without fidelity (no API key needed)."""
        result = pack(SAMPLE_CORPUS)
        ctx_text = serialize(result.document)

        config = EvalConfig(
            golden_set_path=GOLDEN_SET,
            run_fidelity=False,
            run_latency=False,
            run_conflicts=True,
        )

        results = run_eval(config, ctx_text=ctx_text, version="test")
        assert "version" in results
        assert "baselines" in results
        assert "ctxpack_l2" in results["baselines"]
        assert results["baselines"]["ctxpack_l2"]["tokens"] > 0

    def test_results_json_serializable(self):
        result = pack(SAMPLE_CORPUS)
        ctx_text = serialize(result.document)
        config = EvalConfig(
            golden_set_path=GOLDEN_SET,
            run_fidelity=False,
        )
        results = run_eval(config, ctx_text=ctx_text)
        # Should not raise
        json_str = json.dumps(results, indent=2)
        assert len(json_str) > 0

    def test_save_results(self, tmp_path):
        result = pack(SAMPLE_CORPUS)
        ctx_text = serialize(result.document)
        config = EvalConfig(
            golden_set_path=GOLDEN_SET,
            run_fidelity=False,
            output_dir=str(tmp_path),
        )
        results = run_eval(config, ctx_text=ctx_text, version="0.2.0-test")
        path = save_results(results, config)
        assert os.path.exists(path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded["version"] == "0.2.0-test"
