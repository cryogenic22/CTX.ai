"""Save deliverable 3 (real trace) and deliverable 1 (latency) results as JSON."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ctxpack.agent import compress_state
from ctxpack.benchmarks.bench import run_bench
from ctxpack.benchmarks.scaling.corpus_generator import generate_corpus
from ctxpack.core.packer import pack
from ctxpack.core.serializer import serialize

REAL_AGENT_TRACE = [
    {"tool": "read_file", "result": {"file": "src/api/server.py", "content_summary": "FastAPI app, 342 lines", "classes": ["AppServer", "AuthMiddleware", "RateLimiter"], "routes": ["/api/v2/users", "/api/v2/orders", "/api/v2/health", "/api/v2/webhooks"]}},
    {"entities": [{"name": "API-SERVER", "framework": "FastAPI", "version": "0.104.1", "port": 8080, "workers": 4, "host": "0.0.0.0"}]},
    {"tool": "grep_code", "result": {"pattern": "authenticate|verify_token|jwt.decode", "matches": 12, "files": ["src/auth/jwt_handler.py", "src/auth/oauth.py", "src/middleware/auth.py", "tests/test_auth.py"], "sample_match": "def verify_token(token: str) -> dict: decoded = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])"}},
    {"entities": [{"name": "AUTH", "method": "JWT", "algorithm": "HS256", "token_expiry": "30m", "refresh_expiry": "7d", "secret_key_env": "JWT_SECRET_KEY", "issuer": "api.myapp.com"}]},
    {"tool": "read_file", "result": {"file": "src/db/models.py", "tables": ["users", "orders", "order_items", "payments", "sessions", "audit_log"], "orm": "SQLAlchemy 2.0", "relationships": "users -> orders (1:N), orders -> order_items (1:N), orders -> payments (1:1)"}},
    {"entities": [{"name": "USER", "table": "users", "fields": ["id (UUID, PK)", "email (unique, indexed)", "name", "role (enum: admin/user/readonly)", "created_at", "last_login", "is_active (boolean, default true)"], "pii_fields": ["email", "name", "phone"], "auth": "JWT with role-based access control"}]},
    {"tool": "run_tests", "result": {"command": "pytest tests/ -x --tb=short", "exit_code": 1, "passed": 67, "failed": 4, "errors_detail": ["FAILED tests/test_auth.py::test_token_refresh - jwt.ExpiredSignatureError", "FAILED tests/test_orders.py::test_concurrent_update - StaleDataError", "FAILED tests/test_webhooks.py::test_retry_backoff - TimeoutError", "FAILED tests/test_users.py::test_delete_cascade - IntegrityError"]}},
    {"decision": "Fix test_token_refresh by mocking time.time()"},
    {"tool": "read_file", "result": {"file": "config/settings.py", "env_vars": ["DATABASE_URL", "REDIS_URL", "JWT_SECRET_KEY", "STRIPE_API_KEY", "SENTRY_DSN", "LOG_LEVEL", "ALLOWED_ORIGINS"], "defaults": {"LOG_LEVEL": "INFO", "WORKERS": 4, "DB_POOL_SIZE": 10}}},
    {"entities": [{"name": "DATABASE", "engine": "PostgreSQL 15.4", "pool_size": 10, "max_overflow": 5, "pool_recycle": 3600}]},
    {"tool": "read_file", "result": {"file": "docker-compose.yml", "services": {"api": "python:3.12-slim, port 8080", "db": "postgres:15.4-alpine", "redis": "redis:7-alpine", "worker": "celery worker", "beat": "celery beat"}}},
    {"entities": [{"name": "REDIS", "version": "7.x", "purpose": "session cache + task queue", "maxmemory": "256mb", "eviction": "allkeys-lru", "used_for": ["session storage", "rate limiting", "celery broker"]}]},
    {"tool": "grep_code", "result": {"pattern": "oauth|auth0|openid", "matches": 8, "files": ["src/auth/oauth.py", "config/oauth_config.py", "docs/migration-plan.md"], "sample_match": "# TODO(migration): Replace JWT with Auth0 OAuth2 by Q2 2024", "context": "migration appears incomplete"}},
    {"entities": [{"name": "AUTH", "method": "OAuth2 (migration in progress)", "provider": "Auth0", "scopes": ["read", "write", "admin"], "migration_status": "incomplete", "todo": "Remove JWT fallback after Auth0 SSO rollout"}]},
    {"decision": "Auth is in dual-mode: JWT (legacy) + OAuth2/Auth0 (new, incomplete). Must support both during migration."},
    {"tool": "load_test", "result": {"tool": "locust", "duration": "5m", "users": 100, "results": {"total_requests": 15420, "failures": 23, "rps_mean": 51.4, "p50_ms": 42, "p95_ms": 187, "p99_ms": 892, "max_ms": 3200}, "bottleneck": "PostgreSQL connection pool exhaustion at >80 concurrent users"}},
    {"entities": [{"name": "PERFORMANCE", "p50": "42ms", "p95": "187ms", "p99": "892ms", "rps": 51.4, "bottleneck": "DB connection pool exhaustion", "recommendation": "Increase pool_size to 25, add PgBouncer"}]},
    {"decision": "Increase DB pool_size to 25, add PgBouncer in transaction mode"},
    {"entities": [{"name": "DATABASE", "pool_size": 25, "connection_pooler": "PgBouncer", "pool_mode": "transaction", "max_client_connections": 200}]},
    {"tool": "security_scan", "result": {"scanner": "bandit + safety", "findings": {"high": 2, "medium": 2, "low": 2}, "critical": ["CVE-2024-1234: sqlalchemy < 2.0.25", "cryptography==41.0.0 timing attack"]}},
    {"tool": "analyze_deps", "result": {"total_packages": 127, "direct_deps": 34, "outdated": 18, "vulnerable": 3}},
    {"decision": "Upgrade sqlalchemy to 2.0.25+ and cryptography to 42.x immediately"},
    {"tool": "read_file", "result": {"file": ".github/workflows/ci.yml", "stages": ["lint", "test", "security", "build", "deploy"], "coverage_threshold": "85%", "deploy_trigger": "push to main, manual approval for production"}},
    {"entities": [{"name": "CI-CD", "platform": "GitHub Actions", "stages": ["lint", "test", "security", "build", "deploy"], "deploy_target": "AWS ECS", "deploy_strategy": "blue-green", "coverage_min": "85%"}]},
    {"entities": [{"name": "API-SERVER", "api_version": "v2", "rate_limit": "100 req/min per user", "cors_origins": "ALLOWED_ORIGINS env var"}]},
    {"tool": "grep_code", "result": {"pattern": "class.*Exception|raise.*Error", "matches": 22, "custom_exceptions": ["OrderNotFoundError", "InsufficientFundsError", "DuplicateUserError", "WebhookDeliveryError", "RateLimitExceededError"]}},
    {"entities": [{"name": "WEBHOOKS", "retry_policy": "exponential backoff, max 5 retries, 30min ceiling", "events": ["order.created", "order.updated", "payment.succeeded", "payment.failed"], "delivery_timeout": "30s", "signature": "HMAC-SHA256"}]},
    {"entities": [{"name": "MONITORING", "apm": "Sentry", "metrics": "Prometheus + Grafana", "logging": "structured JSON, CloudWatch", "alerts": ["error_rate > 1%", "p95 > 500ms", "disk > 90%", "memory > 85%"]}]},
    {"decision": "Architecture is microservice-ready but currently monolith. Recommend: 1) Fix security vulns, 2) Complete OAuth2, 3) Add PgBouncer, 4) Extract webhook service"},
    {"entities": [{"name": "ORDER", "table": "orders", "status_flow": ["draft", "submitted", "processing", "shipped", "delivered"], "terminal_states": ["cancelled", "refunded"], "immutable_after": "submitted", "belongs_to": "USER via user_id", "payment_provider": "Stripe"}]},
]


def main():
    save_dir = os.path.join(
        os.path.dirname(__file__), "golden_set", "results",
    )
    os.makedirs(save_dir, exist_ok=True)
    version = "0.3.0-alpha"

    # ── Deliverable 3: Real trace ──
    print("Saving deliverable 3 (real trace)...")
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        result = compress_state(REAL_AGENT_TRACE, domain="coding-session")
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)

    trace_data = {
        "version": version,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deliverable": "real-trace-compression",
        "step_count": result.step_count,
        "tokens_raw": result.tokens_raw,
        "tokens_compressed": result.tokens_compressed,
        "compression_ratio": round(result.compression_ratio, 3),
        "entities_merged": result.entities_merged,
        "conflicts_detected": result.conflicts_detected,
        "warnings": result.warnings,
        "pack_latency_ms_mean": round(sum(times) / len(times), 2),
        "pack_latency_ms_all": [round(t, 2) for t in times],
        "ctx_text": result.ctx_text,
        "ctx_text_nl": serialize(result.document, natural_language=True),
    }
    path = os.path.join(save_dir, f"{version}-real-trace.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trace_data, f, indent=2, ensure_ascii=False)
    print(f"  Saved: {path}")

    # ── Deliverable 1: Latency benchmark ──
    print("Saving deliverable 1 (latency benchmark)...")
    latency_data = {
        "version": version,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deliverable": "latency-benchmark",
        "corpus_sizes": [],
    }

    for target in [1000, 5000, 10000]:
        with tempfile.TemporaryDirectory() as tmpdir:
            corpus_dir = os.path.join(tmpdir, "corpus")
            meta = generate_corpus(target, corpus_dir, seed=42 + target)
            raw_tokens = meta["actual_words"]

            pack(corpus_dir)  # warm up
            pack_times = []
            for _ in range(10):
                t0 = time.perf_counter()
                pr = pack(corpus_dir)
                t1 = time.perf_counter()
                pack_times.append((t1 - t0) * 1000)

            l2_text = serialize(pr.document)
            l1_text = serialize(pr.document, natural_language=True)
            l2_tokens = len(l2_text.split())
            l1_tokens = len(l1_text.split())

            ser_times = []
            for _ in range(10):
                t0 = time.perf_counter()
                serialize(pr.document)
                t1 = time.perf_counter()
                ser_times.append((t1 - t0) * 1000)

            latency_data["corpus_sizes"].append({
                "target_tokens": target,
                "raw_tokens": raw_tokens,
                "l2_tokens": l2_tokens,
                "l1_tokens": l1_tokens,
                "l2_ratio": round(raw_tokens / l2_tokens, 2) if l2_tokens else 0,
                "l1_ratio": round(raw_tokens / l1_tokens, 2) if l1_tokens else 0,
                "pack_ms_mean": round(sum(pack_times) / len(pack_times), 2),
                "pack_ms_p95": round(sorted(pack_times)[int(len(pack_times) * 0.95)], 2),
                "ser_ms_mean": round(sum(ser_times) / len(ser_times), 2),
                "pack_ms_all": [round(t, 2) for t in pack_times],
            })

    path = os.path.join(save_dir, f"{version}-latency.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(latency_data, f, indent=2, ensure_ascii=False)
    print(f"  Saved: {path}")

    # ── Bench suite ──
    print("Running bench suite (1K-10K, 10 iterations)...")
    suite = run_bench(sizes=[1000, 5000, 10000], iterations=10)
    bench_path = os.path.join(save_dir, f"{version}-bench.json")
    with open(bench_path, "w", encoding="utf-8") as f:
        f.write(suite.to_json())
    print(f"  Saved: {bench_path}")

    print("\nAll extension results saved.")


if __name__ == "__main__":
    main()
