"""Deterministic synthetic coding-agent trajectory with embedded needles.

Simulates a multi-hour Claude-Code-style session on a fictional payments
platform ("meridian"). The trajectory is generated at a target BPE length
by interleaving fixed NEEDLE events with deterministic filler episodes
(test runs, file reads, greps, lint output).

Needle types:
- static:   a fact stated once at a controlled depth (classic NIAH)
- updated:  a config value revised k times; question asks the FINAL value
            (the proactive-interference probe from Wang & Sun 2025)
- aggregate: cross-session question requiring info from multiple events
- absent:   NOT_IN_CONTEXT adversarial

Every event renders BOTH a transcript block (for raw/BM25/compaction
conditions) and, for needle/update events, a structured step dict (for the
CTX condition — modelling harness-boundary event capture, e.g. a
PostToolUse hook recording config edits and decisions). Filler renders as
{"tool": ...} steps with summary-level results.

Zero dependencies. Fully deterministic for a given (target_bpe, seed).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from ctxpack.benchmarks.metrics.cost import count_bpe_tokens


# ---------------------------------------------------------------------------
# Fixed needle set (identical across lengths so results are comparable)
# ---------------------------------------------------------------------------

STATIC_NEEDLES = [
    {
        "id": "S1", "depth": 0.10, "name": "CONFIG-DB-POOL",
        "fields": {"pool_size": "27",
                   "reason": "pgbouncer max_client_conn is 30 with 3 reserved for migrations"},
        "transcript": ("Decision: setting the meridian-api database connection pool "
                       "size to 27 - pgbouncer max_client_conn is 30 and we reserve "
                       "3 connections for schema migrations."),
        "question": "What was the database connection pool size set to, and why?",
        "expected": "27, because pgbouncer max_client_conn is 30 with 3 connections reserved for migrations",
    },
    {
        "id": "S2", "depth": 0.30, "name": "BUG-FLAKY-LEDGER-TEST",
        "fields": {"test": "test_ledger_rollover",
                   "root_cause": "shared Redis fixture key fx:spot leaks from test_fx_cache when run in that order"},
        "transcript": ("Root cause found: test_ledger_rollover only fails when it runs "
                       "after test_fx_cache - both share the Redis fixture key fx:spot "
                       "and the earlier test leaves a stale entry."),
        "question": "What was the root cause of the flaky test_ledger_rollover failure?",
        "expected": "a shared Redis fixture key fx:spot leaking a stale entry from test_fx_cache when tests run in that order",
    },
    {
        "id": "S3", "depth": 0.50, "name": "DECISION-WEBHOOK-SIGNING",
        "fields": {"algorithm": "HMAC-SHA256", "key_id": "whsec-2026-04",
                   "rotation": "quarterly"},
        "transcript": ("Decision: outbound webhooks are signed with HMAC-SHA256 using "
                       "key id whsec-2026-04; keys rotate quarterly."),
        "question": "How are outbound webhooks signed, and what is the current key id?",
        "expected": "HMAC-SHA256 with key id whsec-2026-04, rotated quarterly",
    },
    {
        "id": "S4", "depth": 0.70, "name": "INCIDENT-STAGING-0624",
        "fields": {"date": "2026-06-24",
                   "cause": "expired intermediate TLS certificate on the vault-agent sidecar",
                   "fix": "pinned CA bundle v3.11"},
        "transcript": ("Investigated the staging outage from 2026-06-24: caused by an "
                       "expired intermediate TLS certificate on the vault-agent sidecar. "
                       "Fixed by pinning CA bundle v3.11 in the base image."),
        "question": "What caused the staging outage on 2026-06-24 and what was the fix?",
        "expected": "an expired intermediate TLS certificate on the vault-agent sidecar; fixed by pinning CA bundle v3.11",
    },
    {
        "id": "S5", "depth": 0.90, "name": "PERF-CHECKOUT-P99",
        "fields": {"budget_ms": "420", "current_ms": "380"},
        "transcript": ("Perf check: p99 checkout latency budget is 420ms; after the "
                       "batching fix we measure 380ms at peak load."),
        "question": "What is the p99 checkout latency budget and the measured value after the fix?",
        "expected": "budget 420ms, measured 380ms after the fix",
    },
]

# Each chain: value revised over the session; question asks the FINAL value.
UPDATE_CHAINS = [
    {
        "id": "U1", "name": "CONFIG-RETRY-BACKOFF",
        "key": "backoff_base_ms",
        "revisions": [
            (0.08, "250", "initial guess from vendor docs"),
            (0.35, "500", "250ms still tripped the vendor rate limit under burst"),
            (0.60, "650", "load test 2026-06-27 showed occasional 429s at 500ms"),
            (0.85, "750", "final value after the second load test came back clean"),
        ],
        "question": "What is the FINAL value of the vendor retry backoff base (backoff_base_ms) at the end of the session?",
        "expected": "750ms",
    },
    {
        "id": "U2", "name": "CONFIG-JWT-TTL",
        "key": "access_token_ttl_minutes",
        "revisions": [
            (0.15, "60", "default from the auth library"),
            (0.45, "30", "security review asked for shorter-lived tokens"),
            (0.80, "22", "must stay under the SSO gateway introspection cache of 25 minutes"),
        ],
        "question": "What is the FINAL JWT access token TTL (in minutes) at the end of the session?",
        "expected": "22 minutes",
    },
    {
        "id": "U3", "name": "CONFIG-CANARY-TRAFFIC",
        "key": "canary_traffic_percent",
        "revisions": [
            (0.20, "1", "standard initial canary"),
            (0.42, "5", "error rate flat, widening"),
            (0.66, "25", "pushing for faster signal before the freeze"),
            (0.88, "10", "rolled back partially - p95 regression at 25 percent"),
        ],
        "question": "What is the FINAL canary traffic percentage at the end of the session?",
        "expected": "10 percent",
    },
    {
        "id": "U4", "name": "CONFIG-PAYMENT-RETRY",
        "key": "max_attempts",
        "revisions": [
            (0.12, "5", "legacy default"),
            (0.55, "3", "duplicate-charge risk flagged by risk team"),
            (0.78, "4", "compromise after adding the idempotency key check"),
        ],
        "question": "What is the FINAL value of payment retry max_attempts at the end of the session?",
        "expected": "4",
    },
]

AGGREGATE_QUESTION = {
    "id": "M1",
    "question": ("Which configuration values were revised three or more times during "
                 "the session? Name each and give its final value."),
    "expected": ("retry backoff base (final 750ms), canary traffic percent (final 10), "
                 "JWT access token TTL (final 22 minutes), and payment retry max_attempts (final 4)"),
}

ABSENT_QUESTIONS = [
    {"id": "A1",
     "question": "Which Kubernetes ingress controller does the meridian platform use?",
     "expected": "NOT_IN_CONTEXT"},
    {"id": "A2",
     "question": "Who approved the Q3 infrastructure budget for the migration?",
     "expected": "NOT_IN_CONTEXT"},
]


# ---------------------------------------------------------------------------
# Filler episode templates (payments-domain vocabulary => real interference)
# ---------------------------------------------------------------------------

_MODULES = ["billing.retry", "ledger.rollover", "fx.cache", "checkout.session",
            "payouts.batch", "webhooks.dispatch", "risk.scoring", "auth.tokens",
            "merchants.onboarding", "refunds.queue"]
_FILES = ["src/meridian/billing/retry.py", "src/meridian/ledger/rollover.py",
          "src/meridian/fx/cache.py", "src/meridian/checkout/session.py",
          "src/meridian/payouts/batch.py", "src/meridian/webhooks/dispatch.py",
          "src/meridian/risk/scoring.py", "src/meridian/auth/tokens.py"]
_LINT_CODES = ["E501 line too long", "F401 unused import", "B008 mutable default",
               "SIM108 ternary", "PLR0913 too many args"]


def _filler_episode(rng: random.Random, idx: int) -> tuple[str, dict[str, Any]]:
    """One deterministic filler episode: (transcript_block, step_dict)."""
    kind = rng.choice(["pytest", "read", "grep", "lint", "git", "ci"])
    mod = rng.choice(_MODULES)
    f = rng.choice(_FILES)

    if kind == "pytest":
        passed, failed = rng.randint(30, 220), rng.choice([0, 0, 0, 1, 2, 3])
        dur = round(rng.uniform(2.0, 45.0), 1)
        lines = [f"$ pytest tests/{mod.split('.')[0]} -q"]
        for _ in range(rng.randint(8, 18)):
            m2 = rng.choice(_MODULES)
            ms = rng.randint(3, 240)
            lines.append(f"tests/{m2.replace('.', '/')}_test.py::test_"
                         f"{rng.choice(['apply', 'rollback', 'idempotent', 'timeout', 'partial', 'batch'])}"
                         f"_{rng.randint(1, 40)} PASSED ({ms}ms)")
        if failed:
            lines.append(f"FAILED tests::{mod} - AssertionError on balance delta "
                         f"(expected {rng.randint(100, 999)}, got {rng.randint(100, 999)})")
        lines.append(f"{passed} passed, {failed} failed in {dur}s")
        text = "\n".join(lines)
        step = {"tool": f"pytest-{idx}", "result": {"module": mod, "passed": passed, "failed": failed}}
    elif kind == "read":
        ln = rng.randint(10, 400)
        body = []
        for j in range(rng.randint(10, 22)):
            body.append(rng.choice([
                f"    def {rng.choice(['process', 'apply', 'validate', 'enqueue', 'settle'])}_{rng.randint(1, 30)}(self, batch_id: str) -> Result:",
                f"        # window={rng.randint(2, 60)}s threshold={rng.randint(50, 950)}ms",
                f"        cursor = self.store.open(batch_id, mode='{rng.choice(['rw', 'ro'])}')",
                f"        if cursor.lag_ms > {rng.randint(100, 2000)}: raise StaleCursor(batch_id)",
                f"        return self._apply(batch_id, retries=self.cfg.retries)",
                f"        log.debug('settled %s in %sms', batch_id, elapsed)",
                f"        metrics.incr('{mod}.{rng.choice(['ok', 'retry', 'drop'])}')",
            ]))
        text = f"Read({f}:{ln})\n" + "\n".join(body)
        step = {"tool": f"read-{idx}", "result": {"file": f, "line": ln}}
    elif kind == "grep":
        hits = rng.randint(2, 14)
        lines = [f"$ grep -rn \"{mod.split('.')[-1]}\" src/"]
        for _ in range(hits):
            f2 = rng.choice(_FILES)
            lines.append(f"{f2}:{rng.randint(5, 500)}: "
                         f"{rng.choice(['import', 'from', 'call to', 'ref'])} {mod}")
        text = "\n".join(lines)
        step = {"tool": f"grep-{idx}", "result": {"pattern": mod, "hits": hits}}
    elif kind == "lint":
        n = rng.randint(0, 9)
        lines = [f"$ ruff check {f}"]
        for _ in range(n):
            lines.append(f"{f}:{rng.randint(5, 400)}:{rng.randint(1, 80)}: "
                         f"{rng.choice(_LINT_CODES)}")
        lines.append(f"Found {n} errors.")
        text = "\n".join(lines)
        step = {"tool": f"ruff-{idx}", "result": {"file": f, "issues": n}}
    elif kind == "git":
        nf = rng.randint(1, 5)
        lines = ["$ git diff --stat"]
        for _ in range(nf):
            lines.append(f" {rng.choice(_FILES)} | {rng.randint(2, 80)} +-")
        lines.append(f" {nf} files changed, {rng.randint(1, 120)} insertions(+), "
                     f"{rng.randint(0, 60)} deletions(-)")
        text = "\n".join(lines)
        step = {"tool": f"git-{idx}", "result": {"files": nf}}
    else:
        job = rng.randint(10000, 99999)
        ok = rng.random() > 0.2
        lines = [f"CI run #{job}: {'green' if ok else 'red'}"]
        for stage in ["build", "unit", "integration", "scan", "package"]:
            lines.append(f"  {stage}: {'ok' if (ok or rng.random() > 0.3) else 'FAIL'} "
                         f"({rng.randint(0, 14)}m{rng.randint(0, 59)}s, "
                         f"cache {'hit' if rng.random() > 0.4 else 'miss'})")
        text = "\n".join(lines)
        step = {"tool": f"ci-{idx}", "result": {"job": job, "green": ok}}

    return text, step


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryBundle:
    """Everything the runner needs for one trajectory length."""

    transcript: str = ""                 # RAW condition context
    episodes: list[str] = field(default_factory=list)   # BM25 chunks
    steps: list[dict] = field(default_factory=list)     # CTX condition input
    questions: list[dict] = field(default_factory=list)
    target_bpe: int = 0
    actual_bpe: int = 0


def generate_trajectory(target_bpe: int, seed: int = 42) -> TrajectoryBundle:
    """Build a trajectory of ~target_bpe tokens with the fixed needle set."""
    rng = random.Random(seed)

    # 1. Collect needle events as (depth, transcript, step) tuples
    events: list[tuple[float, str, dict]] = []
    for n in STATIC_NEEDLES:
        step = {"entities": [{"name": n["name"], **n["fields"]}]}
        events.append((n["depth"], n["transcript"], step))
    for chain in UPDATE_CHAINS:
        for rev_i, (depth, value, reason) in enumerate(chain["revisions"]):
            text = (f"Config update: {chain['key']} set to {value} - {reason}. "
                    f"(revision {rev_i + 1} of {chain['name'].lower()})")
            step = {"entities": [{"name": chain["name"],
                                  chain["key"]: value,
                                  "reason": reason,
                                  "as_of_revision": str(rev_i + 1)}]}
            events.append((depth, text, step))
    events.sort(key=lambda e: e[0])

    # 2. Estimate filler needed
    needle_bpe = sum(count_bpe_tokens(t, model="claude") for _, t, _ in events)
    filler_budget = max(0, target_bpe - needle_bpe)

    # Generate filler episodes until budget is met
    filler: list[tuple[str, dict]] = []
    total = 0
    idx = 0
    while total < filler_budget:
        text, step = _filler_episode(rng, idx)
        filler.append((text, step))
        total += count_bpe_tokens(text, model="claude")
        idx += 1

    # 3. Interleave: place each needle event at its depth fraction
    n_slots = len(filler) + len(events)
    blocks: list[tuple[str, dict]] = []
    placed = 0
    fi = 0
    for slot in range(n_slots):
        frac = slot / max(1, n_slots - 1)
        if placed < len(events) and frac >= events[placed][0]:
            _, text, step = events[placed]
            blocks.append((text, step))
            placed += 1
        elif fi < len(filler):
            blocks.append(filler[fi])
            fi += 1
    # Any leftover needle events go at the end
    for k in range(placed, len(events)):
        blocks.append((events[k][1], events[k][2]))

    episodes = [f"### Step {i + 1}\n{text}" for i, (text, _) in enumerate(blocks)]
    transcript = "\n\n".join(episodes)
    steps = [step for _, step in blocks]

    # 4. Question set
    questions: list[dict] = []
    for n in STATIC_NEEDLES:
        questions.append({"id": n["id"], "question": n["question"],
                          "expected": n["expected"], "type": "static",
                          "difficulty": "medium"})
    for c in UPDATE_CHAINS:
        questions.append({"id": c["id"], "question": c["question"],
                          "expected": c["expected"], "type": "updated",
                          "difficulty": "hard"})
    questions.append({**AGGREGATE_QUESTION, "type": "aggregate", "difficulty": "hard"})
    for a in ABSENT_QUESTIONS:
        questions.append({**a, "type": "absent", "difficulty": "medium"})

    return TrajectoryBundle(
        transcript=transcript,
        episodes=episodes,
        steps=steps,
        questions=questions,
        target_bpe=target_bpe,
        actual_bpe=count_bpe_tokens(transcript, model="claude"),
    )
