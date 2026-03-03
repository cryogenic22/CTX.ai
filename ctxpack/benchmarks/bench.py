"""Latency benchmark for ctxpack pack + serialize pipeline.

Measures wall-clock latency at various corpus sizes to validate
CDN/inference-pipeline integration claims.

Usage:
    from ctxpack.benchmarks.bench import run_bench
    suite = run_bench(sizes=[1000, 5000], iterations=10)
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.packer import pack
from ..core.packer.compressor import count_tokens
from ..core.serializer import serialize
from .scaling.corpus_generator import generate_corpus


@dataclass
class BenchResult:
    """Benchmark results for a single corpus size."""

    size: int
    source_tokens: int
    iterations: int
    pack_times_ms: list[float] = field(default_factory=list)
    serialize_times_ms: list[float] = field(default_factory=list)
    ctx_tokens: int = 0

    @property
    def pack_mean(self) -> float:
        return _mean(self.pack_times_ms)

    @property
    def pack_p50(self) -> float:
        return _percentile(self.pack_times_ms, 50)

    @property
    def pack_p95(self) -> float:
        return _percentile(self.pack_times_ms, 95)

    @property
    def pack_p99(self) -> float:
        return _percentile(self.pack_times_ms, 99)

    @property
    def ser_mean(self) -> float:
        return _mean(self.serialize_times_ms)

    @property
    def ser_p50(self) -> float:
        return _percentile(self.serialize_times_ms, 50)

    @property
    def ser_p95(self) -> float:
        return _percentile(self.serialize_times_ms, 95)

    @property
    def ser_p99(self) -> float:
        return _percentile(self.serialize_times_ms, 99)

    @property
    def throughput_tokens_per_ms(self) -> float:
        """Pack throughput: source tokens / pack mean time."""
        if self.pack_mean <= 0:
            return 0.0
        return self.source_tokens / self.pack_mean


@dataclass
class BenchSuite:
    """Collection of benchmark results across sizes."""

    results: list[BenchResult] = field(default_factory=list)
    timestamp: str = ""

    def to_json(self) -> str:
        data: dict[str, Any] = {
            "timestamp": self.timestamp,
            "results": [],
        }
        for r in self.results:
            data["results"].append({
                "size": r.size,
                "source_tokens": r.source_tokens,
                "ctx_tokens": r.ctx_tokens,
                "iterations": r.iterations,
                "pack_mean_ms": round(r.pack_mean, 2),
                "pack_p50_ms": round(r.pack_p50, 2),
                "pack_p95_ms": round(r.pack_p95, 2),
                "pack_p99_ms": round(r.pack_p99, 2),
                "ser_mean_ms": round(r.ser_mean, 2),
                "ser_p50_ms": round(r.ser_p50, 2),
                "ser_p95_ms": round(r.ser_p95, 2),
                "ser_p99_ms": round(r.ser_p99, 2),
                "throughput_tok_per_ms": round(r.throughput_tokens_per_ms, 1),
            })
        return json.dumps(data, indent=2)


def run_bench(
    *,
    sizes: list[int] | None = None,
    iterations: int = 10,
) -> BenchSuite:
    """Run latency benchmark across corpus sizes.

    Args:
        sizes: List of target token counts (default: [1000, 5000, 10000, 25000, 50000, 100000]).
        iterations: Number of iterations per size for timing.

    Returns:
        BenchSuite with results for each size.
    """
    if sizes is None:
        sizes = [1000, 5000, 10000, 25000, 50000, 100000]

    suite = BenchSuite(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    for size in sizes:
        result = _bench_size(size, iterations)
        suite.results.append(result)

    return suite


def _bench_size(target_tokens: int, iterations: int) -> BenchResult:
    """Benchmark a single corpus size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        corpus_dir = os.path.join(tmpdir, "corpus")
        meta = generate_corpus(target_tokens, corpus_dir, seed=42 + target_tokens)

        result = BenchResult(
            size=target_tokens,
            source_tokens=meta["actual_words"],
            iterations=iterations,
        )

        # Warm-up run (not measured)
        pack_result = pack(corpus_dir)
        doc = pack_result.document
        result.ctx_tokens = count_tokens(doc.body)

        # Measure pack latency
        for _ in range(iterations):
            t0 = time.perf_counter()
            pack(corpus_dir)
            t1 = time.perf_counter()
            result.pack_times_ms.append((t1 - t0) * 1000)

        # Measure serialize latency (on the warm-up result)
        for _ in range(iterations):
            t0 = time.perf_counter()
            serialize(doc)
            t1 = time.perf_counter()
            result.serialize_times_ms.append((t1 - t0) * 1000)

        return result


def format_table(suite: BenchSuite) -> str:
    """Format benchmark results as an aligned text table."""
    header = (
        f"{'Size':>8s}  {'Source':>7s}  {'Pack(mean)':>10s}  {'Pack(p95)':>10s}  "
        f"{'Ser(mean)':>10s}  {'Throughput':>12s}"
    )
    sep = "-" * len(header)
    lines = [header, sep]

    for r in suite.results:
        size_label = _size_label(r.size)
        lines.append(
            f"{size_label:>8s}  {r.source_tokens:>7d}  "
            f"{r.pack_mean:>8.1f}ms  {r.pack_p95:>8.1f}ms  "
            f"{r.ser_mean:>8.1f}ms  "
            f"{r.throughput_tokens_per_ms:>8.1f} tok/ms"
        )

    return "\n".join(lines)


# ── Helpers ──


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _percentile(values: list[float], pct: float) -> float:
    """Compute percentile using linear interpolation (stdlib only)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]

    # Linear interpolation
    k = (pct / 100) * (n - 1)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_vals[lo]
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _size_label(tokens: int) -> str:
    """Human-readable size label: 1000 → '1K', 50000 → '50K'."""
    if tokens >= 1000:
        return f"{tokens // 1000}K"
    return str(tokens)
