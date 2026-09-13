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
    counts, sha = scan_file(VIOLATION)
    assert any(d.startswith("secret:") for d in counts)
    assert counts.get("user_path", 0) >= 1
    findings = gate_findings(
        {"tests/privacy_gate_violation/planted.txt":
         {"detectors": counts, "sha256": sha}}, allowed={})
    assert findings and all("NEW hit" in f for f in findings)


# ── exact-match semantics, both directions ──

def test_new_grown_stale_and_changed_bytes_all_fail():
    sha = "a" * 64
    observed = {"a.txt": {"detectors": {"secret:secret-assignment": 2},
                          "sha256": sha}}
    ok = {("a.txt", "secret:secret-assignment"): (2, sha)}
    assert gate_findings(observed, ok) == []
    assert any("NEW hit" in f for f in gate_findings(observed, {}))
    grown = {("a.txt", "secret:secret-assignment"): (1, sha)}
    assert any("CHANGED hit" in f for f in gate_findings(observed, grown))
    stale = {**ok, ("gone.txt", "user_path"): (3, sha)}
    assert any("STALE allowlist entry" in f
               for f in gate_findings(observed, stale))


def test_f4_same_count_swap_fails_on_reviewed_bytes(tmp_path):
    """Finding 4a (P1): replacing a reviewed false positive with a real
    secret of the SAME detector count must fail — the allowance binds
    the reviewed bytes, not the count. RED on 91054ca: both variants
    produced {secret-assignment: 1} and the swap passed."""
    benign = tmp_path / "f.py"
    benign.write_text("resp = ask(model, api_key=client_key)\n",
                      encoding="utf-8")
    counts_b, sha_b = scan_file(str(benign))
    assert counts_b == {"secret:secret-assignment": 1}
    allowed = {("f.py", "secret:secret-assignment"): (1, sha_b)}
    ok = gate_findings({"f.py": {"detectors": counts_b,
                                 "sha256": sha_b}}, allowed)
    assert ok == []

    benign.write_text(
        "resp = ask(model, api_key=supersecretvalue12345)\n",
        encoding="utf-8")
    counts_s, sha_s = scan_file(str(benign))
    assert counts_s == counts_b            # the same-count swap
    findings = gate_findings({"f.py": {"detectors": counts_s,
                                       "sha256": sha_s}}, allowed)
    assert findings and "CHANGED BYTES" in findings[0]


def test_rf1_wide_and_invalid_encodings_cannot_pass_as_clean(tmp_path):
    """RF1 (Codex Finding 1, P1): lossy decoding read a UTF-16 secret as
    clean ({} detector map). A publishable fixture must be clean UTF-8
    text; wide/invalid encodings are REFUSED (non_text/non_utf8), never
    lossy-scanned. RED on eb2aa8a: UTF-16LE returned {} and passed with
    no allowlist entry."""
    secret = "AKIAIOSFODNN7EXAMPLE"
    le = tmp_path / "le.txt"
    le.write_bytes(secret.encode("utf-16-le"))
    be = tmp_path / "be.txt"
    be.write_bytes(secret.encode("utf-16-be"))
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"prefix \xff\xfe\xfa not utf8 " + secret.encode())
    for f in (le, be):
        counts, sha = scan_file(str(f))
        assert counts == {"non_text": 1}, (f.name, counts)
        # refused files are NEW hits unless explicitly dispositioned —
        # the encoded secret can never pass silently
        assert gate_findings({f.name: {"detectors": counts,
                                       "sha256": sha}}, allowed={})
    counts, sha = scan_file(str(bad))
    assert counts == {"non_utf8": 1}, counts
    assert gate_findings({"bad.txt": {"detectors": counts,
                                      "sha256": sha}}, allowed={})


def test_rf1_valid_utf8_controls_stay_clean(tmp_path):
    """RF1 (c): genuine UTF-8 text (incl. non-ASCII and a benign
    binary-lookalike with high bytes that still decode) is scanned
    normally, not refused."""
    ok = tmp_path / "ok.md"
    ok.write_text("# notes — café, naïve, 数据; api_key parameter\n",
                  encoding="utf-8")
    counts, sha = scan_file(str(ok))
    assert "non_text" not in counts and "non_utf8" not in counts
    assert len(sha) == 64


def test_rf1_niah_log_carries_an_explicit_sha_bound_disposition():
    """RF1 (b): the one committed non-UTF-8 result file has an explicit
    owner disposition in the allowlist, bound to its exact bytes — no
    lossy-clean waiver, and a byte change breaks the sha."""
    import json
    rel = "ctxpack/benchmarks/agentic/results/niah_full_run.log"
    raw = json.load(open(os.path.join(REPO_ROOT, ALLOWLIST_FILE),
                        encoding="utf-8"))
    entry = next((e for e in raw["entries"] if e["path"] == rel), None)
    assert entry is not None, "niah log must be explicitly dispositioned"
    assert entry["detector"] in ("non_utf8", "non_text")
    assert len(entry["sha256"]) == 64
    counts, sha = scan_file(os.path.join(REPO_ROOT, rel))
    assert entry["sha256"] == sha              # bound to the reviewed bytes


def test_unreadable_committed_file_raises_never_passes(tmp_path):
    """Can-fail: a committed file the gate cannot READ is a GateError
    — the gate never passes by being unable to look."""
    with pytest.raises(GateError):
        scan_file(str(tmp_path / "missing.bin"))


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
    for e in raw["entries"]:
        assert str(e["why"]).strip()
        assert len(e["sha256"]) == 64          # byte-bound (Finding 4a)
        assert " or synthetic" not in e["why"]  # exact dispositions only
    assert not any("privacy_gate_violation" in p for p, _ in allowed)
