"""CI wrapper + unit tests for the claims gate (execution plan W1-2)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_claims import NUMERIC_PATTERNS, check, parse_ledger  # noqa: E402

LEDGER_SNIPPET = """
| C1 | Fidelity 86.7% vs 83.3% | measured | 86.7%, 83.3% | `paper/status-and-value-v0.5.md` | n=30 | 2026-06 |
| E1 | Letta 74% on LoCoMo | external | 74% on LoCoMo |
| R1 | 26x cost | 26x | `paper/status-and-value-v0.5.md` |
"""


def test_repo_claims_gate_is_green():
    errors, _warnings = check(ROOT)
    assert not errors, "\n".join(errors)


def test_ledger_parsing():
    covers, artifacts, signatures = parse_ledger(LEDGER_SNIPPET)
    assert "86.7%" in covers and "74% on LoCoMo" in covers
    assert ("C1", "paper/status-and-value-v0.5.md") in artifacts
    assert signatures == ["26x"]


def test_numeric_patterns_catch_claim_shapes():
    hits = ["hydrated 86.7% wins", "a 166x reduction", "F1 = 1.000 exact",
            "±13–18pp CI"]
    for line in hits:
        assert any(p.search(line) for p in NUMERIC_PATTERNS), line
    misses = ["20 tools", "64K context", "Python 3.10+", "arXiv 2606.22528",
              "~2K-token gist"]
    for line in misses:
        assert not any(p.search(line) for p in NUMERIC_PATTERNS), line


def test_retracted_signature_detected(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "paper").mkdir()
    (tmp_path / "docs" / "claims-ledger.md").write_text(
        LEDGER_SNIPPET, encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "CtxPack: 26x cheaper.\nFidelity 86.7% vs 83.3%, measured.\n",
        encoding="utf-8")
    (tmp_path / "paper" / "status-and-value-v0.5.md").write_text(
        "26x was retracted here.\n", encoding="utf-8")
    errors, _ = check(tmp_path)
    assert any("retracted claim signature '26x'" in e for e in errors)
    # the retraction context line itself must NOT be flagged
    assert not any("status-and-value" in e for e in errors)


def test_unledgered_number_fails(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "paper").mkdir()
    (tmp_path / "docs" / "claims-ledger.md").write_text(
        LEDGER_SNIPPET, encoding="utf-8")
    (tmp_path / "paper" / "status-and-value-v0.5.md").write_text(
        "retraction doc\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "Our new eval hit 99.9% accuracy.\n", encoding="utf-8")
    errors, _ = check(tmp_path)
    assert any("README.md:1" in e and "numerical claim" in e for e in errors)
