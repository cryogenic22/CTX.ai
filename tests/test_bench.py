"""Tests for ctxpack bench (latency benchmark)."""

from __future__ import annotations

import json

import pytest

from ctxpack.benchmarks.bench import (
    BenchResult,
    BenchSuite,
    _mean,
    _percentile,
    _size_label,
    format_table,
    run_bench,
)


class TestHelpers:
    def test_mean_basic(self):
        assert _mean([1.0, 2.0, 3.0]) == 2.0

    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_percentile_single(self):
        assert _percentile([5.0], 50) == 5.0

    def test_percentile_ordered(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        p50 = _percentile(vals, 50)
        p95 = _percentile(vals, 95)
        p99 = _percentile(vals, 99)
        assert p50 <= p95 <= p99

    def test_percentile_empty(self):
        assert _percentile([], 50) == 0.0

    def test_size_label(self):
        assert _size_label(1000) == "1K"
        assert _size_label(50000) == "50K"
        assert _size_label(500) == "500"


class TestBenchResult:
    def test_properties(self):
        r = BenchResult(
            size=1000,
            source_tokens=950,
            iterations=3,
            pack_times_ms=[10.0, 12.0, 11.0],
            serialize_times_ms=[0.3, 0.4, 0.5],
            ctx_tokens=150,
        )
        assert r.pack_mean > 0
        assert r.pack_p50 > 0
        assert r.pack_p50 <= r.pack_p95 <= r.pack_p99
        assert r.ser_mean > 0
        assert r.throughput_tokens_per_ms > 0

    def test_throughput_zero_time(self):
        r = BenchResult(size=0, source_tokens=0, iterations=0)
        assert r.throughput_tokens_per_ms == 0.0


class TestRunBench:
    def test_small_bench(self):
        """Run bench with smallest size and minimal iterations."""
        suite = run_bench(sizes=[1000], iterations=2)
        assert isinstance(suite, BenchSuite)
        assert len(suite.results) == 1
        r = suite.results[0]
        assert r.size == 1000
        assert r.source_tokens > 0
        assert r.ctx_tokens > 0
        assert len(r.pack_times_ms) == 2
        assert len(r.serialize_times_ms) == 2
        assert all(t > 0 for t in r.pack_times_ms)
        assert all(t > 0 for t in r.serialize_times_ms)

    def test_percentiles_ordered(self):
        suite = run_bench(sizes=[1000], iterations=5)
        r = suite.results[0]
        assert r.pack_p50 <= r.pack_p95 <= r.pack_p99
        assert r.ser_p50 <= r.ser_p95 <= r.ser_p99

    def test_throughput_positive(self):
        suite = run_bench(sizes=[1000], iterations=2)
        r = suite.results[0]
        assert r.throughput_tokens_per_ms > 0

    def test_timestamp_present(self):
        suite = run_bench(sizes=[1000], iterations=2)
        assert suite.timestamp != ""


class TestFormatters:
    def test_format_table(self):
        suite = run_bench(sizes=[1000], iterations=2)
        table = format_table(suite)
        assert "Size" in table
        assert "Pack(mean)" in table
        assert "1K" in table

    def test_to_json_valid(self):
        suite = run_bench(sizes=[1000], iterations=2)
        raw = suite.to_json()
        data = json.loads(raw)
        assert "results" in data
        assert len(data["results"]) == 1
        r = data["results"][0]
        assert r["size"] == 1000
        assert r["pack_mean_ms"] > 0
        assert r["throughput_tok_per_ms"] > 0


class TestCLI:
    def test_bench_command(self):
        from ctxpack.cli.main import main

        rc = main(["bench", "--sizes", "1000", "--iterations", "2"])
        assert rc == 0

    def test_bench_json(self):
        from ctxpack.cli.main import main

        rc = main(["bench", "--sizes", "1000", "--iterations", "2", "--json"])
        assert rc == 0
