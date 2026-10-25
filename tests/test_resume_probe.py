"""Resume-probe harness (Layer 2) — generation, grading, arm mechanics."""

import json
import os

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.benchmarks.agentic.resume_probe import (
    CTX_ARM_VERSION,
    LITERAL_DISAMBIGUATION,
    Probe,
    _mangle_project_dir,
    ctx_context,
    generate_probes,
    grade,
    to_report,
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
    # os.path.abspath(repo_path) with non-alphanumerics -> '-' (hyphens kept).
    # abspath is platform-dependent, so assert against a path already absolute
    # on the running platform (Windows ground truth; POSIX equivalent).
    if os.name == "nt":
        assert _mangle_project_dir(r"C:\Users\kapil\Documents\CTX_mod") == \
            "C--Users-kapil-Documents-CTX-mod"
    else:
        assert _mangle_project_dir("/Users/kapil/Documents/CTX_mod") == \
            "-Users-kapil-Documents-CTX-mod"


def _ambiguous_ledger(tmp_path):
    # one assistant turn banking TWO distinct git_sha literals — "the
    # exact git_sha around turn N" admits either, so both probes must be
    # skipped (pre-registered A2, PREREGISTRATION-resume-probe.md)
    entries = [
        _entry("user", "Please land the retry fix and revert the probe.",
               "bbbb2222-s"),
        _entry("assistant", [{"type": "text", "text":
            "Decision: land the retry fix ahead of the release branch "
            "cut because the vendor limit change ships next week. "
            "Fixed in commit deadbeef1234 and reverted the probe in "
            "commit cafebabe5678."}], "bbbb2222-s"),
    ]
    t = tmp_path / "amb.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    out = tmp_path / "ctx-amb"
    run_checkpoint(str(t), str(out), as_of="2026-07-04")
    return str(out)


def test_ambiguous_same_turn_literals_are_skipped(tmp_path):
    ledger = _ambiguous_ledger(tmp_path)
    meta = {}
    probes = generate_probes(ledger, n=20, seed=42, meta=meta)
    lit_expected = {p.expected for p in probes if p.kind == "literal"}
    assert "deadbeef1234" not in lit_expected
    assert "cafebabe5678" not in lit_expected
    assert meta.get("ambiguous_literals_skipped", 0) == 2


def test_single_literal_per_turn_still_probes(tmp_path):
    # the control: one git_sha at the turn (plus a number_unit — a
    # DIFFERENT kind never collides) → probe kept, nothing skipped
    ledger = _ledger(tmp_path)
    meta = {}
    probes = generate_probes(ledger, n=20, seed=42, meta=meta)
    assert any(p.kind == "literal" and p.expected == "deadbeef1234"
               for p in probes)
    assert meta.get("ambiguous_literals_skipped", 0) == 0


def test_report_config_stamps_disambiguation_policy(tmp_path):
    ledger = _ledger(tmp_path)
    meta = {}
    probes = generate_probes(ledger, n=5, seed=42, meta=meta)
    report = to_report(str(tmp_path), probes, [], seed=42,
                       model="none", probe_set="recall", gen_meta=meta)
    cfg = report["config"]
    assert cfg["literal_disambiguation"] == LITERAL_DISAMBIGUATION
    assert cfg["ambiguous_literals_skipped"] == 0  # disclosed even at 0


def test_report_stamps_bm25_ctx_arm_version(tmp_path):
    ledger = _ledger(tmp_path)
    probes = generate_probes(ledger, n=5, seed=42)
    report = to_report(str(tmp_path), probes, [], seed=42,
                       model="none", probe_set="recall")
    assert CTX_ARM_VERSION == "v3-bm25"
    assert report["config"]["ctx_arm"] == CTX_ARM_VERSION
    assert "BM25 keyword hydration" in report["config"]["arm_notes"]
