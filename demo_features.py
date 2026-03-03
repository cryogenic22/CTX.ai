"""Demo script: generate comparison table for ctxpack extension features.

Produces a publication-ready table showing compression, fidelity proxies,
and latency across domain knowledge (L2/L1) and agent state scenarios.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time

# Force UTF-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure ctxpack is importable
sys.path.insert(0, os.path.dirname(__file__))

from ctxpack.agent import compress_state
from ctxpack.benchmarks.bench import run_bench, format_table
from ctxpack.benchmarks.scaling.corpus_generator import generate_corpus
from ctxpack.core.packer import pack
from ctxpack.core.packer.compressor import count_tokens
from ctxpack.core.serializer import serialize


# ── Agent step fixtures at various scales ──

AGENT_10_STEPS = [
    {"tool": "read_file", "result": {"file": "app.py", "classes": ["App", "Router", "DB"]}},
    {"entities": [{"name": "APP", "framework": "FastAPI", "version": "0.104", "port": 8000}]},
    {"tool": "search_code", "result": {"pattern": "def auth", "matches": 3, "files": ["auth.py", "middleware.py"]}},
    {"entities": [{"name": "AUTH", "method": "JWT", "expiry": "1h", "refresh": "7d"}]},
    {"tool": "read_file", "result": {"file": "models.py", "tables": ["users", "sessions", "tokens"]}},
    {"entities": [{"name": "USER", "fields": ["id", "email", "role", "created_at"], "pii": ["email"]}]},
    {"entities": [{"name": "APP", "database": "PostgreSQL", "orm": "SQLAlchemy"}]},
    {"decision": "Use connection pooling with max 20 connections"},
    {"tool": "run_tests", "result": {"passed": 42, "failed": 3, "errors": ["auth timeout", "db connection", "missing env"]}},
    {"entities": [{"name": "AUTH", "method": "OAuth2", "provider": "Auth0"}]},
]

AGENT_25_STEPS = AGENT_10_STEPS + [
    {"decision": "Migrate from JWT to OAuth2 for SSO support"},
    {"entities": [{"name": "CONFIG", "env": "production", "debug": "false", "log_level": "WARNING"}]},
    {"tool": "read_file", "result": {"file": "docker-compose.yml", "services": ["web", "db", "redis", "worker"]}},
    {"entities": [{"name": "REDIS", "purpose": "caching", "max_memory": "256mb", "eviction": "allkeys-lru"}]},
    {"entities": [{"name": "APP", "cache_layer": "Redis", "session_store": "Redis"}]},
    {"tool": "analyze_deps", "result": {"total": 87, "outdated": 12, "vulnerable": 3, "critical": ["lodash@4.17.20", "express@4.17.1"]}},
    {"entities": [{"name": "USER", "auth_method": "OAuth2", "mfa": "TOTP", "session_ttl": "3600s"}]},
    {"decision": "Enable rate limiting: 100 req/min per user, 1000 req/min per API key"},
    {"tool": "run_linter", "result": {"errors": 0, "warnings": 15, "files_checked": 42}},
    {"entities": [{"name": "DB", "engine": "PostgreSQL", "version": "15.4", "pool_size": 20, "max_overflow": 10}]},
    {"entities": [{"name": "DB", "backup": "daily", "retention": "30d", "point_in_time": "enabled"}]},
    {"tool": "security_scan", "result": {"high": 1, "medium": 5, "low": 12, "info": 30}},
    {"entities": [{"name": "API", "version": "v2", "auth": "Bearer token", "rate_limit": "100/min"}]},
    {"decision": "Use structured logging with correlation IDs for distributed tracing"},
    {"entities": [{"name": "CONFIG", "secrets_manager": "AWS Secrets Manager", "config_source": "environment"}]},
]

AGENT_50_STEPS = AGENT_25_STEPS + [
    {"tool": "read_file", "result": {"file": "routes/users.py", "endpoints": ["/users", "/users/{id}", "/users/me", "/users/search"]}},
    {"entities": [{"name": "ENDPOINT-USERS", "methods": ["GET", "POST", "PUT", "DELETE"], "auth_required": "true", "pagination": "cursor-based"}]},
    {"tool": "read_file", "result": {"file": "routes/orders.py", "endpoints": ["/orders", "/orders/{id}", "/orders/{id}/items", "/orders/{id}/status"]}},
    {"entities": [{"name": "ORDER", "status_flow": ["draft", "submitted", "processing", "shipped", "delivered"], "payment": "Stripe"}]},
    {"entities": [{"name": "ORDER", "belongs_to": "USER", "immutable_after": "submitted"}]},
    {"tool": "read_file", "result": {"file": "middleware/auth.py", "decorators": ["require_auth", "require_admin", "require_scope"]}},
    {"entities": [{"name": "AUTH", "scopes": ["read", "write", "admin"], "token_type": "Bearer", "issuer": "Auth0"}]},
    {"decision": "Implement webhook retry with exponential backoff (max 5 retries, 30min ceiling)"},
    {"tool": "load_test", "result": {"rps": 500, "p50_ms": 45, "p95_ms": 120, "p99_ms": 350, "error_rate": "0.1%"}},
    {"entities": [{"name": "PERF", "target_p95": "200ms", "current_p95": "120ms", "headroom": "40%"}]},
    {"entities": [{"name": "DB", "read_replicas": 2, "connection_pooler": "PgBouncer", "pool_mode": "transaction"}]},
    {"tool": "read_file", "result": {"file": "migrations/", "count": 47, "latest": "047_add_user_preferences.py"}},
    {"entities": [{"name": "USER", "preferences": ["theme", "locale", "notifications"], "gdpr_exportable": "true"}]},
    {"decision": "All PII fields must be encrypted at rest using AES-256-GCM"},
    {"entities": [{"name": "ENCRYPTION", "algorithm": "AES-256-GCM", "key_rotation": "90d", "kms": "AWS KMS"}]},
    {"tool": "check_ci", "result": {"pipeline": "GitHub Actions", "status": "green", "coverage": "87%", "last_deploy": "2024-01-15"}},
    {"entities": [{"name": "CI", "platform": "GitHub Actions", "stages": ["lint", "test", "build", "deploy"], "deploy_target": "AWS ECS"}]},
    {"entities": [{"name": "APP", "deploy_strategy": "blue-green", "rollback": "automatic", "health_check": "/health"}]},
    {"decision": "Use feature flags for gradual rollout of OAuth2 migration"},
    {"tool": "read_file", "result": {"file": "monitoring/alerts.py", "alerts": ["high_error_rate", "slow_response", "disk_full", "memory_high"]}},
    {"entities": [{"name": "MONITORING", "tool": "Datadog", "alerts": ["PagerDuty"], "dashboards": ["API health", "DB performance", "Auth flow"]}]},
    {"entities": [{"name": "APP", "observability": "OpenTelemetry", "log_aggregator": "Datadog"}]},
    {"decision": "Implement circuit breaker pattern for external service calls (Stripe, Auth0)"},
    {"entities": [{"name": "REDIS", "cluster_mode": "sentinel", "nodes": 3, "failover": "automatic"}]},
    {"entities": [{"name": "CONFIG", "feature_flags": "LaunchDarkly", "ab_testing": "enabled"}]},
]


def _measure_pack_latency(corpus_dir: str, iterations: int = 5) -> float:
    """Measure mean pack latency in ms."""
    # warm up
    pack(corpus_dir)
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        pack(corpus_dir)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return sum(times) / len(times)


def _measure_agent_latency(steps: list, iterations: int = 5) -> float:
    """Measure mean agent compress latency in ms."""
    # warm up
    compress_state(steps)
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        compress_state(steps)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return sum(times) / len(times)


def _count_raw_tokens(text: str) -> int:
    return len(text.split())


def run_demo():
    print("=" * 78)
    print("  ctxpack Feature Demo — Extension Comparison Table")
    print("=" * 78)
    print()

    rows = []

    # ── Part 1: Domain Knowledge (L2 vs L1) at multiple sizes ──
    print("[1/3] Domain knowledge compression (L2 vs L1)...")
    for target in [1000, 5000, 10000]:
        with tempfile.TemporaryDirectory() as tmpdir:
            corpus_dir = os.path.join(tmpdir, "corpus")
            meta = generate_corpus(target, corpus_dir, seed=42 + target)
            raw_tokens = meta["actual_words"]

            latency = _measure_pack_latency(corpus_dir)
            result = pack(corpus_dir)

            l2_text = serialize(result.document)
            l2_tokens = _count_raw_tokens(l2_text)
            l2_ratio = raw_tokens / l2_tokens if l2_tokens else 0

            l1_text = serialize(result.document, natural_language=True)
            l1_tokens = _count_raw_tokens(l1_text)
            l1_ratio = raw_tokens / l1_tokens if l1_tokens else 0

            size_label = f"{target // 1000}K" if target >= 1000 else str(target)

            rows.append({
                "scenario": f"Domain {size_label} (L2)",
                "raw": raw_tokens,
                "compressed": l2_tokens,
                "ratio": l2_ratio,
                "merged": "—",
                "conflicts": "—",
                "latency": latency,
            })
            rows.append({
                "scenario": f"Domain {size_label} (L1)",
                "raw": raw_tokens,
                "compressed": l1_tokens,
                "ratio": l1_ratio,
                "merged": "—",
                "conflicts": "—",
                "latency": latency,  # same pack, different serialize
            })
            print(f"  {size_label}: raw={raw_tokens}, L2={l2_tokens} ({l2_ratio:.1f}x), L1={l1_tokens} ({l1_ratio:.1f}x), {latency:.1f}ms")

    # ── Part 2: Agent State Compression at multiple step counts ──
    print()
    print("[2/3] Agent state compression...")
    for label, steps in [("10 steps", AGENT_10_STEPS), ("25 steps", AGENT_25_STEPS), ("50 steps", AGENT_50_STEPS)]:
        latency = _measure_agent_latency(steps)
        result = compress_state(steps)

        rows.append({
            "scenario": f"Agent ({label})",
            "raw": result.tokens_raw,
            "compressed": result.tokens_compressed,
            "ratio": result.compression_ratio,
            "merged": str(result.entities_merged),
            "conflicts": str(result.conflicts_detected),
            "latency": latency,
        })
        print(f"  {label}: raw={result.tokens_raw}, ctx={result.tokens_compressed}, "
              f"ratio={result.compression_ratio:.1f}x, merged={result.entities_merged}, "
              f"conflicts={result.conflicts_detected}, {latency:.1f}ms")
        if result.warnings:
            for w in result.warnings[:3]:
                print(f"    ⚠ {w}")

    # ── Part 3: Latency benchmark ──
    print()
    print("[3/3] Latency benchmark (pack pipeline)...")
    suite = run_bench(sizes=[1000, 5000, 10000], iterations=10)
    print()
    print(format_table(suite))

    # ── Final comparison table ──
    print()
    print()
    print("=" * 98)
    print("  COMPARISON TABLE")
    print("=" * 98)
    print()
    hdr = f"{'Scenario':<24s} {'Raw Tok':>8s} {'Ctx Tok':>8s} {'Ratio':>7s} {'Merged':>7s} {'Conflicts':>10s} {'Latency':>10s}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        ratio_str = f"{r['ratio']:.1f}x"
        latency_str = f"{r['latency']:.1f}ms"
        print(f"{r['scenario']:<24s} {r['raw']:>8d} {r['compressed']:>8d} {ratio_str:>7s} {str(r['merged']):>7s} {str(r['conflicts']):>10s} {latency_str:>10s}")

    # ── Agent output sample ──
    print()
    print()
    print("=" * 78)
    print("  SAMPLE: Agent 50-step compressed output")
    print("=" * 78)
    print()
    agent_result = compress_state(AGENT_50_STEPS)
    print(agent_result.ctx_text)

    # ── L1 vs L2 sample ──
    print()
    print("=" * 78)
    print("  SAMPLE: L2 vs L1 output (1K corpus, first 25 lines)")
    print("=" * 78)
    with tempfile.TemporaryDirectory() as tmpdir:
        corpus_dir = os.path.join(tmpdir, "corpus")
        generate_corpus(1000, corpus_dir, seed=42)
        result = pack(corpus_dir)

        l2_text = serialize(result.document)
        l1_text = serialize(result.document, natural_language=True)

        l2_lines = l2_text.splitlines()[:25]
        l1_lines = l1_text.splitlines()[:25]

        print()
        print("-- L2 (compact notation) --")
        for line in l2_lines:
            print(f"  {line}")

        print()
        print("-- L1 (natural language) --")
        for line in l1_lines:
            print(f"  {line}")

    print()
    print("=" * 78)
    print("  Demo complete.")
    print("=" * 78)


if __name__ == "__main__":
    run_demo()
