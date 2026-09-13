"""CompactBench scaffold: generator determinism + DR@K metric math."""

import json

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.benchmarks.compactbench.drk import (
    mcnemar_b_c,
    recall_at_k,
    wilson_ci,
)
from ctxpack.benchmarks.compactbench.planted_session_gen import (
    generate_planted_session,
)


def test_generator_is_seed_deterministic():
    a_entries, a_manifest = generate_planted_session(seed=7)
    b_entries, b_manifest = generate_planted_session(seed=7)
    assert json.dumps(a_entries) == json.dumps(b_entries)
    assert a_manifest == b_manifest
    c_entries, _ = generate_planted_session(seed=8)
    assert json.dumps(a_entries) != json.dumps(c_entries)


def test_generator_plant_mix_matches_preregistration():
    _, manifest = generate_planted_session(seed=1)
    assert len(manifest["decisions"]) == 15
    assert sum(1 for d in manifest["decisions"]
               if d["kind"] == "revised") == 5
    assert len(manifest["constraints"]) == 10
    assert len(manifest["literals"]) == 10
    assert len(manifest["failed"]) == 5
    for d in manifest["decisions"]:
        if d["kind"] == "revised":
            assert d["expected"] == str(d["history"][-1]), \
                "graded answer must be the FINAL value"


def test_planted_session_survives_the_real_pipeline(tmp_path):
    """The ledger must capture the plants — otherwise the ctx arm of the
    benchmark starts falsified by construction."""
    entries, manifest = generate_planted_session(seed=3)
    t = tmp_path / "planted.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    result = run_checkpoint(str(t), str(tmp_path / "ctx"),
                            as_of="2026-07-04")
    ledger = (tmp_path / "ctx" / f"session-{result.session_id[:8]}.ctx")
    text = ledger.read_text(encoding="utf-8")
    captured_decisions = sum(
        1 for d in manifest["decisions"] if d["kind"] == "stable"
        and d["expected"] in text)
    assert captured_decisions >= 8, (
        f"only {captured_decisions}/10 stable decisions reached the ledger")
    captured_constraints = sum(
        1 for c in manifest["constraints"] if c["expected"] in text)
    assert captured_constraints >= 8


def test_wilson_and_recall_curve():
    lo, hi = wilson_ci(9, 10)
    assert 0.55 < lo < 0.9 < hi <= 1.0
    curve = recall_at_k({1: [True] * 9 + [False],
                         3: [True] * 6 + [False] * 4})
    assert curve[1]["recall"] == 0.9
    assert curve[3]["recall"] == 0.6
    assert curve[1]["ci95"][0] > curve[3]["ci95"][0]


def test_mcnemar_discordant_pairs():
    # arm A right where B wrong 8 times, reverse once → significant
    paired = [(True, False)] * 8 + [(False, True)] + [(True, True)] * 20
    out = mcnemar_b_c(paired)
    assert out["b"] == 8 and out["c"] == 1
    assert out["p_value"] < 0.05
    assert mcnemar_b_c([(True, True)] * 5)["p_value"] == 1.0
