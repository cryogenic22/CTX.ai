"""Token-accounting gate (execution plan W1-3).

User-facing "token" numbers must come from ctxpack.core.tokens and carry
their estimator label; whitespace word counts must never be presented as
tokens. Calibration vs cl100k runs when tiktoken is installed (kill
threshold from the plan: |error| > 15% fails; target is <=5% on the
content kind's home turf).
"""

import json

import pytest

from ctxpack.core.tokens import (
    ESTIMATOR_CTX,
    ESTIMATOR_PROSE,
    estimate_tokens,
    estimator_label,
)

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Calibration runs against REAL committed artifacts, not synthetic
# strings — synthetic .ctx mixes measured anywhere from 2.5 to 3.9
# chars/token depending on prose/symbol balance, while every real
# committed .ctx artifact sits in 2.73-3.16 (measured vs cl100k_base,
# 2026-07-11, chars/3 error -9%..+5%).
CTX_ARTIFACTS = [
    "ctx_mod.ctx",
    "spec/CTXPACK-SPEC.L2.ctx",
    "paper/ctxpack-whitepaper.L2.ctx",
    ".claude/ctx/session-eca3f61c.ctx",
    ".claude/ctx/session-bdfbd48b.ctx",
]
PROSE_ARTIFACTS = ["README.md", "docs/session-memory-onboarding.md"]

CTX_SAMPLE = "KEY:value | TIER:2\nDEPS:svc-1,svc-2 -> gw\n" * 20


def test_estimates_are_deterministic_and_labelled():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a", kind="ctx") == 1
    assert estimate_tokens(CTX_SAMPLE, kind="ctx") == estimate_tokens(
        CTX_SAMPLE, kind="ctx")
    assert estimator_label("ctx") == ESTIMATOR_CTX
    assert estimator_label("prose") == ESTIMATOR_PROSE
    with pytest.raises(KeyError):
        estimate_tokens("x", kind="nonsense")


def test_hydration_result_carries_estimator_label():
    from ctxpack.core.hydrator import HydrationResult

    assert HydrationResult().token_estimator == ESTIMATOR_CTX


def test_mcp_pack_metrics_never_say_bare_tokens(tmp_path):
    from ctxpack.integrations.mcp_server import handle_pack

    (tmp_path / "svc.yaml").write_text(
        "service: billing\nowner: core-team\nsla: '99.9'\n"
        "note: do not restart without draining\n", encoding="utf-8")
    payload = json.loads(handle_pack({"corpus_dir": str(tmp_path)}))
    metrics = payload["metrics"]
    assert "ctx_tokens" not in metrics and "source_tokens" not in metrics
    assert metrics["token_estimator"] == ESTIMATOR_CTX
    assert metrics["ctx_token_estimate"] > 0
    assert "compression_ratio_words" in metrics


def test_calibration_against_cl100k():
    tiktoken = pytest.importorskip("tiktoken")
    enc = tiktoken.get_encoding("cl100k_base")

    checked = 0
    for paths, kind in ((CTX_ARTIFACTS, "ctx"), (PROSE_ARTIFACTS, "prose")):
        for rel in paths:
            p = ROOT / rel
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            actual = len(enc.encode(text, disallowed_special=()))
            if actual < 500:
                continue
            estimate = estimate_tokens(text, kind=kind)
            err = (estimate - actual) / actual
            checked += 1
            print(f"calibration {kind} {rel}: est={estimate} "
                  f"actual={actual} err={err:+.1%}")
            assert abs(err) <= 0.15, (
                f"{kind} estimator drifted {err:+.1%} from cl100k on "
                f"{rel} — over the 15% kill threshold; recalibrate "
                f"divisors in core/tokens.py")
    assert checked >= 3, "calibration corpus went missing"
