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

# Calibration runs against FROZEN fixtures with committed cl100k
# counts (reviewer finding Q2-4: live dogfood ledgers are mutable, and
# importorskip made the whole gate optional in a pytest-only CI).
# Provenance + edit protocol: tests/fixtures/token_calibration/README.md
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "token_calibration"
EXPECTED = FIXTURE_DIR / "expected_cl100k.json"

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


def test_mcp_hydrate_estimates_the_emitted_representation(tmp_path):
    """Q2-1: prose and raw responses estimate THEIR OWN text, each
    carrying the matching estimator label."""
    from ctxpack.integrations.mcp_server import handle_hydrate, handle_pack

    (tmp_path / "svc.yaml").write_text(
        "service: billing\nowner: core-team\nsla: '99.9'\n"
        "note: do not restart without draining\n", encoding="utf-8")
    ctx_text = json.loads(handle_pack({"corpus_dir": str(tmp_path)}))[
        "ctx_text"]
    ctx_file = tmp_path / "packed.ctx"
    ctx_file.write_text(ctx_text, encoding="utf-8")

    prose = json.loads(handle_hydrate(
        {"file_path": str(ctx_file), "query": "billing restart drain"}))
    assert prose["format"] == "prose"
    assert prose["token_estimator"] == estimator_label("prose")
    assert prose["tokens_injected"] == estimate_tokens(
        prose["ctx_text"], kind="prose")

    raw = json.loads(handle_hydrate(
        {"file_path": str(ctx_file), "query": "billing restart drain",
         "raw": True}))
    assert raw["format"] == "ctx"
    assert raw["token_estimator"] == estimator_label("ctx")
    assert raw["tokens_injected"] == estimate_tokens(
        raw["ctx_text"], kind="ctx")
    assert raw["ctx_text"] != prose["ctx_text"]


def _load_expected():
    spec = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert len(spec["files"]) >= 5, "calibration corpus went missing"
    return spec


def test_calibration_fixtures_are_intact():
    """sha256 pinning — runs everywhere, no tiktoken needed. An edited
    fixture without a re-measured count fails HERE, loudly."""
    import hashlib
    spec = _load_expected()
    for name, meta in spec["files"].items():
        raw = (FIXTURE_DIR / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == meta["sha256"], (
            f"{name} changed without re-measuring — see "
            f"tests/fixtures/token_calibration/README.md")


def test_calibration_against_frozen_cl100k():
    """The drift gate (kill threshold 15%): ALWAYS runs — ground truth
    is the committed cl100k counts, so a pytest-only CI still enforces
    it. The <=5% target is reported separately and is not a gate."""
    spec = _load_expected()
    kill, target_misses = [], []
    for name, meta in spec["files"].items():
        # raw-bytes decode: the committed bytes are the canonical text —
        # read_text() newline translation would silently shift counts
        text = (FIXTURE_DIR / name).read_bytes().decode("utf-8")
        estimate = estimate_tokens(text, kind=meta["kind"])
        err = (estimate - meta["cl100k"]) / meta["cl100k"]
        print(f"calibration {meta['kind']} {name}: est={estimate} "
              f"cl100k={meta['cl100k']} err={err:+.1%}")
        if abs(err) > 0.15:
            kill.append(f"{name}: {err:+.1%}")
        elif abs(err) > 0.05:
            target_misses.append(f"{name}: {err:+.1%}")
    n = len(spec["files"])
    print(f"calibration target (<=5%): {n - len(target_misses) - len(kill)}"
          f"/{n} met; target misses (reported, not gated): "
          f"{target_misses or 'none'}")
    assert not kill, (
        f"estimator over the 15% kill threshold on: {kill} — "
        f"recalibrate divisors in core/tokens.py")


def test_frozen_counts_match_live_tokenizer():
    """Integrity re-measure — the only tiktoken-gated piece: verifies
    the COMMITTED counts against the live cl100k encoding when the
    tokenizer is installed (dedicated CI job installs it)."""
    tiktoken = pytest.importorskip("tiktoken")
    enc = tiktoken.get_encoding("cl100k_base")
    spec = _load_expected()
    for name, meta in spec["files"].items():
        text = (FIXTURE_DIR / name).read_bytes().decode("utf-8")
        live = len(enc.encode(text, disallowed_special=()))
        assert live == meta["cl100k"], (
            f"{name}: committed count {meta['cl100k']} != live {live} — "
            f"tokenizer version drift or stale expected_cl100k.json")
