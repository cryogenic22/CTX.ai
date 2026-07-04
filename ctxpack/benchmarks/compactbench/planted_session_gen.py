"""Seeded generator: Claude-Code-shaped session JSONL with planted facts.

Emits (entries, manifest): the entries serialize to a transcript the
driver replays through real Claude Code; the manifest is the ground
truth the probes grade against. Deterministic per seed — same seed,
byte-identical output.

Plant mix per PREREGISTRATION.md: 15 decisions (5 revised 2-3x, final
value graded), 10 negation-bearing constraints, 10 exact literals,
5 failed approaches, interleaved with deterministic tool-call filler.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

_SERVICES = ["billing", "ledger", "checkout", "risk", "notify", "search",
             "ingest", "reports", "auth", "webhook"]
_KNOBS = ["POOL-SIZE", "TIMEOUT-MS", "BATCH-LIMIT", "RETRY-BASE-MS",
          "CACHE-TTL-S", "MAX-WORKERS", "QUEUE-DEPTH", "SHARD-COUNT"]
_FILLER_DESCS = ["Run test suite", "Inspect service logs",
                 "List failing checks", "Show recent commits",
                 "Check queue depth", "Profile hot path"]


def _sha(rng: random.Random) -> str:
    return hashlib.sha1(str(rng.random()).encode()).hexdigest()[:12]


def _entry(etype: str, content: Any, sid: str, turn: int) -> dict:
    return {"type": etype, "sessionId": sid,
            "timestamp": f"2026-07-04T{10 + turn // 360:02d}:"
                         f"{(turn // 6) % 60:02d}:{(turn * 7) % 60:02d}Z",
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _assistant_text(text: str, sid: str, turn: int) -> dict:
    return _entry("assistant", [{"type": "text", "text": text}], sid, turn)


def _filler(rng: random.Random, sid: str, turn: int) -> dict:
    desc = rng.choice(_FILLER_DESCS)
    svc = rng.choice(_SERVICES)
    return _entry("assistant", [{
        "type": "tool_use", "name": "Bash",
        "input": {"command": f"pytest tests/{svc} -q && tail -5 {svc}.log",
                  "description": f"{desc} for {svc}"}}], sid, turn)


def generate_planted_session(seed: int = 0) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    sid = f"cb{seed:04d}00-bench"
    entries: list[dict] = []
    manifest: dict[str, Any] = {"seed": seed, "session": sid,
                                "decisions": [], "constraints": [],
                                "literals": [], "failed": []}
    turn = 0

    def emit(entry: dict) -> None:
        nonlocal turn
        entries.append(entry)
        turn += 1

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
        for _ in range(rng.randint(2, 5)):
            emit(_filler(rng, sid, turn))
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
            for _ in range(rng.randint(2, 4)):
                emit(_filler(rng, sid, turn))
            reason = ("initial setting" if i == 0 else
                      "load test regression" if i == 1 else
                      "vendor limit confirmed")
            emit(_assistant_text(
                f"Decision: set {knob} to {value} — {reason}.", sid, turn))
        manifest["decisions"].append({
            "plant_turn": turn - 1, "kind": "revised", "key": knob,
            "history": values, "expected": str(values[-1])})

    # 10 constraints (user-stated, negation-bearing)
    for i in range(10):
        svc = rng.choice(_SERVICES)
        rule = rng.choice([
            f"Do not deploy {svc} on Fridays.",
            f"Never bypass the {svc} rate limiter, even in tests.",
            f"Do not change the {svc} schema without a migration ticket.",
            f"Always run the {svc} contract tests before merging.",
        ])
        emit(_entry("user", f"One more ground rule: {rule}", sid, turn))
        manifest["constraints"].append(
            {"plant_turn": turn - 1, "text": rule, "expected": rule})
        emit(_filler(rng, sid, turn))

    # 10 exact literals (SHAs/versions) — planted inside assistant text
    for i in range(10):
        sha = _sha(rng)
        svc = rng.choice(_SERVICES)
        emit(_assistant_text(
            f"Confirmed: the fix for {svc} landed as commit {sha} and is "
            f"tagged for the next release train.", sid, turn))
        manifest["literals"].append(
            {"plant_turn": turn - 1, "service": svc, "expected": sha})
        emit(_filler(rng, sid, turn))

    # 5 failed approaches
    for i in range(5):
        svc = rng.choice(_SERVICES)
        approach = rng.choice(["sticky sessions", "table-level locks",
                               "polling the vendor API", "in-memory queues",
                               "double-write migration"])
        text = (f"The {approach} approach didn't work because {svc} "
                f"deadlocked under concurrent load; reverted.")
        emit(_assistant_text(text, sid, turn))
        manifest["failed"].append(
            {"plant_turn": turn - 1, "approach": approach, "expected": approach})
        emit(_filler(rng, sid, turn))

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
