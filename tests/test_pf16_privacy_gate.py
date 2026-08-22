"""PF-16 committed-fixture privacy gate.

COMPLEMENTS the E-6A standing gate (tests/test_fixture_privacy.py) —
E-6A bans the owner's identity and non-fictional home-dir users across
tests/fixtures/**; this gate adds the secret scanner + machine-path
detector over the WIDER committed surface (benchmarks, scorecards)
against an exact-match reviewed allowlist. Neither gate replaces the
other.

Green-field unit: red on the parent commit (module + allowlist absent).
The live-tree test is the GATE; the violation-fixture test is the
committed negative control the gate discipline requires (a gate never
observed failing must not count as a gate)."""

import json
import os

import pytest

from ctxpack.agent.fixture_privacy import (
    ALLOWLIST_FILE,
    ALLOWLIST_SCHEMA,
    GateError,
    committed_files,
    gate_findings,
    load_allowlist,
    run_gate,
    scan_file,
    scan_text,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIOLATION = os.path.join(REPO_ROOT, "tests", "privacy_gate_violation",
                         "planted.txt")


# ── the live gate ──

def test_committed_trees_match_the_reviewed_allowlist():
    """THE gate: every committed file under the fixture/benchmark/
    artifact roots matches the reviewed allowlist exactly — new hits,
    grown hits, and stale allowlist entries all fail. Forward guard
    freezing the reviewed 2026-08-22 state."""
    findings = run_gate(REPO_ROOT)
    assert findings == [], "\n".join(findings)


def test_gate_is_deterministic():
    from ctxpack.agent.fixture_privacy import scan_tree
    assert scan_tree(REPO_ROOT) == scan_tree(REPO_ROOT)


# ── the committed negative control ──

def test_gate_rejects_the_committed_violation_fixture():
    """Can-fail proof: the planted fixture (outside the scanned roots)
    trips BOTH detector families and would fail the gate if it ever
    entered a scanned tree with no allowlist entry."""
    counts = scan_file(VIOLATION)
    assert any(d.startswith("secret:") for d in counts)
    assert counts.get("user_path", 0) >= 1
    findings = gate_findings({"tests/privacy_gate_violation/planted.txt":
                              counts}, allowed={})
    assert findings and all("NEW hit" in f for f in findings)


# ── exact-match semantics, both directions ──

def test_new_grown_and_stale_hits_all_fail():
    observed = {"a.txt": {"secret:secret-assignment": 2}}
    ok = {("a.txt", "secret:secret-assignment"): 2}
    assert gate_findings(observed, ok) == []
    assert any("NEW hit" in f for f in gate_findings(observed, {}))
    grown = {("a.txt", "secret:secret-assignment"): 1}
    assert any("CHANGED hit" in f for f in gate_findings(observed, grown))
    stale = {**ok, ("gone.txt", "user_path"): 3}
    assert any("STALE allowlist entry" in f
               for f in gate_findings(observed, stale))


def test_unscanned_file_is_a_finding_not_a_silent_skip(tmp_path):
    """Can-fail: undecodable bytes cannot be proven clean — they must
    be explicitly allowlisted or they fail."""
    bad = tmp_path / "blob.bin"
    bad.write_bytes(b"\xff\xfe\x00garbage")
    assert scan_file(str(bad)) == {"unscanned": 1}
    findings = gate_findings({"blob.bin": {"unscanned": 1}}, allowed={})
    assert findings and "unscanned" in findings[0]


def test_user_path_detector_counts_distinct_paths():
    text = ("saved to C:\\Users\\alice\\one and C:\\Users\\alice\\one "
            "then /home/bob/two")
    assert scan_text(text)["user_path"] == 2


# ── the gate must fail loudly when it cannot run ──

def test_enumeration_failure_raises_never_passes(tmp_path):
    """Can-fail: a non-repo root means the gate could not enumerate —
    that is a GateError, never an empty (passing) scan."""
    with pytest.raises(GateError):
        committed_files(str(tmp_path))


def test_malformed_allowlist_refuses(tmp_path):
    for body in ('{"schema": "wrong/v9", "entries": []}',
                 '{"schema": "%s", "entries": [{"path": "x"}]}'
                 % ALLOWLIST_SCHEMA,
                 "not json at all"):
        p = tmp_path / "allow.json"
        p.write_text(body, encoding="utf-8")
        with pytest.raises(GateError):
            load_allowlist(str(p))


def test_allowlist_entries_all_carry_a_review_note():
    """Forward guard: the bar itself stays reviewable — every entry has
    a non-empty why (load_allowlist enforces it; this pins the live
    file, and pins that the violation fixture is NOT allowlisted)."""
    allowed = load_allowlist(os.path.join(REPO_ROOT, ALLOWLIST_FILE))
    assert allowed, "allowlist unexpectedly empty"
    raw = json.load(open(os.path.join(REPO_ROOT, ALLOWLIST_FILE),
                         encoding="utf-8"))
    assert raw["schema"] == ALLOWLIST_SCHEMA
    assert all(str(e["why"]).strip() for e in raw["entries"])
    assert not any("privacy_gate_violation" in p for p, _ in allowed)
