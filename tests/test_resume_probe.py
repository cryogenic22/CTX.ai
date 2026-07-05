"""Resume-probe harness (Layer 2) — generation, grading, arm mechanics."""

import json

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.benchmarks.agentic.resume_probe import (
    Probe,
    _mangle_project_dir,
    ctx_context,
    generate_probes,
    grade,
)


def _entry(etype, content, sid):
    return {"type": etype, "sessionId": sid,
            "timestamp": "2026-07-04T10:00:00Z",
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _ledger(tmp_path):
    entries = [
        _entry("user", "Please fix retry handling. Do not touch the auth "
                       "service while doing this work.", "aaaa1111-s"),
        _entry("assistant", [{"type": "text", "text":
            "Decision: use exponential backoff with base 750ms for every "
            "vendor call because the rate limit is 40 requests per "
            "minute. Fixed in commit deadbeef1234."}], "aaaa1111-s"),
    ]
    t = tmp_path / "s.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    out = tmp_path / "ctx"
    run_checkpoint(str(t), str(out), as_of="2026-07-04")
    return str(out)


def test_generate_probes_is_seeded_deterministic(tmp_path):
    ledger = _ledger(tmp_path)
    a = generate_probes(ledger, n=10, seed=42)
    b = generate_probes(ledger, n=10, seed=42)
    assert [p.probe_id for p in a] == [p.probe_id for p in b]
    assert a, "no probes generated from a ledger with a decision"
    kinds = {p.kind for p in a}
    assert "decision" in kinds


def test_decision_probe_grading(tmp_path):
    ledger = _ledger(tmp_path)
    probe = next(p for p in generate_probes(ledger, n=10, seed=1)
                 if p.kind == "decision")
    # the expected phrase comes from the decision tail — a full restatement
    # passes, an unrelated answer fails
    assert grade(probe, probe.source_text) is True
    assert grade(probe, "We decided to use polling instead.") is False
    assert grade(probe, "") is False
    assert grade(probe, "(error: HTTP 500)") is False


def test_exact_grade_normalizes_quotes():
    p = Probe(probe_id="x", kind="literal", session="s", turn=1,
              question="q", expected="a1b2c3d4e5", grade_mode="exact")
    assert grade(p, "The value is `a1b2c3d4e5`.") is True
    assert grade(p, "The value is a1b2c3d4XX.") is False


def test_ctx_arm_includes_source_session_literals(tmp_path):
    # v2 arm (pre-registered 2026-07-05): every banked literal of the
    # probe's source session is addressable in the ctx context, even
    # when it never appears in the startup gist or a hydrated section
    ledger = _ledger(tmp_path)
    probe = next(p for p in generate_probes(ledger, n=10, seed=42))
    ctx = ctx_context(ledger, probe)
    assert "ctxpack session literals" in ctx
    assert "deadbeef1234" in ctx


def test_mangle_project_dir_matches_claude_code():
    assert _mangle_project_dir(r"C:\Users\kapil\Documents\CTX_mod") == \
        "C--Users-kapil-Documents-CTX-mod"
