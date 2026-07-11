"""CI wrapper + unit tests for the claims gate (W1-2 + reviewer Q2-3)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_claims import NUMERIC_PATTERNS, check, parse_ledger  # noqa: E402

_ARTIFACT = "ctxpack/benchmarks/results/definitive_eval.json"
LEDGER_SNIPPET = f"""
| C1 | Fidelity 86.7% vs 83.3% | measured | 86.7%, 83.3% | `{_ARTIFACT}` | n=30 | 2026-06 |
| E1 | Letta 74% on LoCoMo | external | 74% on LoCoMo |
| R1 | 26x cost | 26x | `paper/status-and-value-v0.5.md` |
"""


def _repo(tmp_path, readme="", ledger=LEDGER_SNIPPET, artifact_body="{}"):
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "paper").mkdir(exist_ok=True)
    (tmp_path / "docs" / "claims-ledger.md").write_text(
        ledger, encoding="utf-8")
    art = tmp_path / _ARTIFACT
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(artifact_body, encoding="utf-8")
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    return tmp_path


def test_repo_claims_gate_is_green():
    errors, _warnings = check(ROOT)
    assert not errors, "\n".join(errors)


def test_ledger_parsing():
    ledger = parse_ledger(LEDGER_SNIPPET)
    assert "86.7%" in ledger["covers"] and "74% on LoCoMo" in ledger["covers"]
    assert ("C1", _ARTIFACT, "") in ledger["artifacts"]
    assert ledger["signatures"] == ["26x"]
    assert ledger["ids"] == {"C1", "E1"}


def test_numeric_patterns_catch_claim_shapes():
    hits = ["hydrated 86.7% wins", "a 166x reduction", "F1 = 1.000 exact",
            "±13–18pp CI",
            # Q2-3 widened backstop — the shapes that bypassed the gate
            "significant at p=0.0039", "hook completes in <2s",
            "RAW baseline 0.78–0.82", "recovered 9 out of 10 decisions",
            "recall was zero after the first compaction"]
    for line in hits:
        assert any(p.search(line) for p in NUMERIC_PATTERNS), line
    misses = ["20 tools", "64K context", "Python 3.10+", "arXiv 2606.22528",
              "~2K-token gist", "commit 0ee35c8", "runs in 35 min"]
    for line in misses:
        assert not any(p.search(line) for p in NUMERIC_PATTERNS), line


def test_retracted_signature_detected(tmp_path):
    _repo(tmp_path,
          readme="CtxPack: 26x cheaper.\nFidelity 86.7% vs 83.3%.\n")
    (tmp_path / "paper" / "status-and-value-v0.5.md").write_text(
        "26x was retracted here.\n", encoding="utf-8")
    errors, _ = check(tmp_path)
    assert any("retracted claim signature '26x'" in e for e in errors)
    # the retraction context line itself must NOT be flagged
    assert not any("status-and-value" in e for e in errors)


def test_unledgered_number_fails(tmp_path):
    _repo(tmp_path, readme="Our new eval hit 99.9% accuracy.\n")
    errors, _ = check(tmp_path)
    assert any("README.md:1" in e and "numerical claim" in e for e in errors)


# ------------------------------------------------------- Q2-3 additions


def test_inline_claim_id_covers_a_numeric_line(tmp_path):
    _repo(tmp_path, readme="We measured a 42.5% lift. [CL:C1]\n")
    errors, _ = check(tmp_path)
    assert not errors, errors


def test_unknown_claim_id_fails(tmp_path):
    _repo(tmp_path, readme="We measured a 42.5% lift. [CL:C99]\n")
    errors, _ = check(tmp_path)
    assert any("unknown claim ID [CL:C99]" in e for e in errors)


def test_measured_artifact_outside_results_tree_fails(tmp_path):
    ledger = (
        "| C1 | Fidelity 86.7% | measured | 86.7% | "
        "`paper/status-and-value-v0.5.md` | n=30 | 2026-06 |\n")
    _repo(tmp_path, ledger=ledger)
    (tmp_path / "paper" / "status-and-value-v0.5.md").write_text(
        "prose\n", encoding="utf-8")
    errors, _ = check(tmp_path)
    assert any("not in the immutable results tree" in e for e in errors)


def test_artifact_sha_mismatch_fails(tmp_path):
    ledger = (
        f"| C1 | Fidelity 86.7% | measured | 86.7% | "
        f"`{_ARTIFACT}` sha256:deadbeef0000 | n=30 | 2026-06 |\n")
    _repo(tmp_path, ledger=ledger, artifact_body='{"v": 1}')
    errors, _ = check(tmp_path)
    assert any("artifact content changed" in e for e in errors)


def test_papers_numeric_coverage_warns_per_file_not_per_line(tmp_path):
    _repo(tmp_path)
    (tmp_path / "paper" / "big.md").write_text(
        "claim one: 12.5% lift\nclaim two: 8x faster\n"
        "claim three: p=0.01\n", encoding="utf-8")
    errors, warnings = check(tmp_path)
    assert not errors
    hits = [w for w in warnings if "paper/big.md" in w]
    assert len(hits) == 1                      # summarized, not spammed
    assert "3 uncovered numeric line(s)" in hits[0]
