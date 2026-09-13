"""Seeded generator: Claude-Code-shaped session JSONL with planted facts.

Emits (entries, manifest): the entries serialize to a transcript the
driver replays through real Claude Code; the manifest is the ground
truth the probes grade against. Deterministic per seed — same seed,
byte-identical output.

Plant mix per PREREGISTRATION.md: 15 decisions (5 revised 2-3x, final
value graded), 10 negation-bearing constraints, 10 exact literals,
5 failed approaches, interleaved with deterministic tool-call filler.

Replay-critical invariants (learned against Claude Code 2.1.x):
- session IDs must be valid UUIDs (transcript filename + --resume both
  key on them) — derived deterministically from the seed;
- every assistant tool_use must be followed by a user tool_result with
  a matching id, or the reconstructed API conversation is rejected.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import random
import uuid
from typing import Any

_EPOCH = _dt.datetime(2026, 7, 4, 10, 0, 0, tzinfo=_dt.timezone.utc)

_SERVICES = ["billing", "ledger", "checkout", "risk", "notify", "search",
             "ingest", "reports", "auth", "webhook"]
_KNOBS = ["POOL-SIZE", "TIMEOUT-MS", "BATCH-LIMIT", "RETRY-BASE-MS",
          "CACHE-TTL-S", "MAX-WORKERS", "QUEUE-DEPTH", "SHARD-COUNT"]
_FILLER_DESCS = ["Run test suite", "Inspect service logs",
                 "List failing checks", "Show recent commits",
                 "Check queue depth", "Profile hot path"]
_TEST_VERBS = ["read", "write", "sync", "auth", "flush", "retry", "batch"]


def session_uuid(seed: int) -> str:
    """Deterministic, valid UUID for a seed (Claude Code requires UUIDs)."""
    digest = hashlib.sha1(f"compactbench-{seed}".encode()).digest()[:16]
    return str(uuid.UUID(bytes=digest, version=4))


def _entry(etype: str, content: Any, sid: str, turn: int) -> dict:
    # Real datetime arithmetic: turn counters can be large (the driver's
    # inflation filler uses high turn bases), and a synthetic timestamp
    # with an out-of-range hour makes Claude Code's session loader
    # reject the whole transcript ("No conversation found").
    ts = _EPOCH + _dt.timedelta(seconds=turn * 7)
    return {"type": etype, "sessionId": sid,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _assistant_text(text: str, sid: str, turn: int) -> dict:
    return _entry("assistant", [{"type": "text", "text": text}], sid, turn)


def _log_block(rng: random.Random, svc: str, lines: int) -> str:
    rows = [f"{svc}-{rng.randrange(10, 99)} :: PASS "
            f"test_{rng.choice(_TEST_VERBS)}_{rng.randrange(100, 999)} "
            f"[{rng.randrange(1, 900)}ms]" for _ in range(lines)]
    return "\n".join(rows)


def _filler_pair(rng: random.Random, sid: str, turn: int,
                 lines: int = 18) -> list[dict]:
    """One tool call and its result — the interference medium.

    Paired so the replayed conversation stays API-valid (an assistant
    tool_use with no tool_result is rejected on resume).
    """
    desc = rng.choice(_FILLER_DESCS)
    svc = rng.choice(_SERVICES)
    tool_id = f"toolu_cb{hashlib.sha1(str(rng.random()).encode()).hexdigest()[:20]}"
    call = _entry("assistant", [{
        "type": "tool_use", "id": tool_id, "name": "Bash",
        "input": {"command": f"pytest tests/{svc} -q && tail -5 {svc}.log",
                  "description": f"{desc} for {svc}"}}], sid, turn)
    result = _entry("user", [{
        "type": "tool_result", "tool_use_id": tool_id,
        "content": _log_block(rng, svc, lines)}], sid, turn + 1)
    return [call, result]


def _sha(rng: random.Random) -> str:
    return hashlib.sha1(str(rng.random()).encode()).hexdigest()[:12]


def generate_planted_session(seed: int = 0) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    sid = session_uuid(seed)
    entries: list[dict] = []
    manifest: dict[str, Any] = {"seed": seed, "session": sid,
                                "decisions": [], "constraints": [],
                                "literals": [], "failed": []}
    turn = 0

    def emit(entry: dict) -> None:
        nonlocal turn
        entries.append(entry)
        turn += 1

    def emit_filler(times: int) -> None:
        for _ in range(times):
            for e in _filler_pair(rng, sid, turn):
                emit(e)

    emit(_entry("user", "Continue hardening the payments platform. "
                        "Work through the backlog.", sid, turn))

    # 10 stable decisions + 5 revised knobs (2-3 revisions each)
    stable = rng.sample(_SERVICES, 10)
    for svc in stable:
        strategy = rng.choice(["least-connections routing",
                               "idempotency keys on writes",
                               "outbox pattern for events",
                               "circuit breaker at p99 500ms",
                               "read-through cache"])
        emit_filler(rng.randint(2, 5))
        text = (f"Decision: adopt {strategy} for the {svc} service because "
                f"load testing showed it holds at peak traffic.")
        emit(_assistant_text(text, sid, turn))
        manifest["decisions"].append({
            "plant_turn": turn - 1, "kind": "stable", "service": svc,
            "text": text, "expected": strategy})

    revised = rng.sample(_KNOBS, 5)
    for knob in revised:
        values = rng.sample([25, 50, 100, 250, 500, 750, 1000, 2000], 3)
        for i, value in enumerate(values):
            emit_filler(rng.randint(2, 4))
            reason = ("initial setting" if i == 0 else
                      "load test regression" if i == 1 else
                      "vendor limit confirmed")
            emit(_assistant_text(
                f"Decision: set {knob} to {value} — {reason}.", sid, turn))
        manifest["decisions"].append({
            "plant_turn": turn - 1, "kind": "revised", "key": knob,
            "history": values, "expected": str(values[-1])})

    # 10 constraints (user-stated, negation-bearing). Unique
    # (service, template) pairs so every plant is unambiguously probeable
    # — one targeted probe per planted fact, no accept-set merging.
    templates = [
        "Do not deploy {svc} on Fridays.",
        "Never bypass the {svc} rate limiter, even in tests.",
        "Do not change the {svc} schema without a migration ticket.",
        "Always run the {svc} contract tests before merging.",
    ]
    combos = [(svc, t) for svc in _SERVICES for t in templates]
    for svc, template in rng.sample(combos, 10):
        rule = template.format(svc=svc)
        emit(_entry("user", f"One more ground rule: {rule}", sid, turn))
        manifest["constraints"].append(
            {"plant_turn": turn - 1, "text": rule, "expected": rule})
        emit_filler(1)

    # 10 exact literals (SHAs) — one per service, planted in assistant text
    for svc in rng.sample(_SERVICES, 10):
        sha = _sha(rng)
        emit(_assistant_text(
            f"Confirmed: the fix for {svc} landed as commit {sha} and is "
            f"tagged for the next release train.", sid, turn))
        manifest["literals"].append(
            {"plant_turn": turn - 1, "service": svc, "expected": sha})
        emit_filler(1)

    # 5 failed approaches — each approach used once
    approaches = ["sticky sessions", "table-level locks",
                  "polling the vendor API", "in-memory queues",
                  "double-write migration"]
    for approach in rng.sample(approaches, 5):
        svc = rng.choice(_SERVICES)
        text = (f"The {approach} approach didn't work because {svc} "
                f"deadlocked under concurrent load; reverted.")
        emit(_assistant_text(text, sid, turn))
        manifest["failed"].append(
            {"plant_turn": turn - 1, "approach": approach, "expected": approach})
        emit_filler(1)

    manifest["total_turns"] = turn
    return entries, manifest


def write_session(seed: int, out_dir: str) -> tuple[str, str]:
    import os
    entries, manifest = generate_planted_session(seed)
    os.makedirs(out_dir, exist_ok=True)
    jsonl = os.path.join(out_dir, f"planted-{seed:04d}.jsonl")
    with open(jsonl, "w", encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    mpath = os.path.join(out_dir, f"planted-{seed:04d}-manifest.json")
    with open(mpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return jsonl, mpath
