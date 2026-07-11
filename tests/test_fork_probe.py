"""drift-fork/v1 — planted-fork fixture, probes, grading, unlock math
(pre-registered A3, PREREGISTRATION-resume-probe.md).

The fixture is built through the REAL producer (run_checkpoint), so
these tests also pin the end-to-end contract the probe depends on: two
Supersedes-declaring sessions over one base produce exactly one 2-head
DAG conflict per fork, and the shipped (nowarn) startup context carries
both head values — the probe must measure noticing, never absence.
"""

from dataclasses import asdict

import pytest

from ctxpack.agent.session_reader import load_supersession
from ctxpack.benchmarks.agentic.fork_fixture import (
    _FORK_TABLE,
    build_fork_fixture,
    fork_candidates,
    fork_grep_context,
    fork_warn_block,
)
from ctxpack.benchmarks.agentic.resume_probe import (
    Probe,
    ProbeResult,
    _norm,
    ctx_context,
    fork_unlock,
    grade,
)


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return build_fork_fixture(str(tmp_path_factory.mktemp("forkfx")))


@pytest.fixture(scope="module")
def probes(fx):
    return fork_candidates(fx)


# ------------------------------------------------------------- fixture


def test_fixture_plants_every_fork_as_a_dag_conflict(fx):
    _, graph = load_supersession(fx.ledger_dir)
    assert len(graph.conflicts) == len(_FORK_TABLE)
    assert all(len(c.heads) == 2 for c in graph.conflicts)
    planted_bases = sorted(f.base_fid for f in fx.forks)
    assert sorted(c.roots[0] for c in graph.conflicts) == planted_bases


def test_v1_is_the_lower_sorted_head(fx):
    for f in fx.forks:
        assert f.v1_fid < f.v2_fid  # A3: the deterministic draw
        assert f.v1 != f.v2


def test_fixture_is_deterministic(fx, tmp_path_factory):
    again = build_fork_fixture(str(tmp_path_factory.mktemp("forkfx2")))
    assert [asdict(p) for p in fork_candidates(again)] == [
        asdict(p) for p in fork_candidates(fx)]
    assert fork_warn_block(again.ledger_dir) == fork_warn_block(fx.ledger_dir)


# -------------------------------------------------------------- probes


def test_probe_shows_v1_and_never_v2(fx, probes):
    assert len(probes) == len(_FORK_TABLE)
    by_key = {f.key: f for f in fx.forks}
    for p in probes:
        f = by_key[p.probe_id[len("fork-"):].upper()]
        assert f.v1 in p.question
        assert _norm(f.v2) not in _norm(p.question)
        assert p.expected == f.v2
        assert p.kind == "drift-fork" and p.grade_mode == "fork"
        assert p.session == f.v1_session
        assert sorted(p.alt_all) == sorted([f.v1_session, f.v2_session])


def test_nowarn_context_contains_v2_for_every_probe(fx, probes):
    # the honesty gate: the shipped startup context must CARRY the other
    # head's value, else the arm measures absence instead of noticing —
    # a bias toward building the feature
    for p in probes:
        ctx = ctx_context(fx.ledger_dir, p)
        assert _norm(p.expected) in _norm(ctx), (
            f"{p.probe_id}: v2 absent from the nowarn context")


def test_warn_block_lists_base_and_both_heads(fx):
    block = fork_warn_block(fx.ledger_dir)
    assert "possible_conflict" in block
    for f in fx.forks:
        assert f.v1 in block and f.v2 in block
        assert f.base_fid in block
        assert f.v1_session in block and f.v2_session in block


def test_grep_arm_reaches_v2_across_transcripts(fx, probes):
    # the fork spans two sessions — the multi-transcript grep arm must be
    # ABLE to surface v2 (over-powered by construction, standing rule)
    p = probes[0]
    windows = fork_grep_context(fx, p, budget_bpe=6000)
    assert p.expected in windows


# ------------------------------------------------------------- grading


def _fork_probe(**kw):
    base = dict(probe_id="fork-x", kind="drift-fork", session="bbbb2222",
                turn=1, question="Proceeding with K = expo-base-750ms as "
                "the current value — drafting the next step. OK?",
                expected="linear-step-2000ms", grade_mode="fork",
                alt_all=["bbbb2222", "cccc3333"])
    base.update(kw)
    return Probe(**base)


def test_fork_grade_passes_on_verbatim_v2():
    assert grade(_fork_probe(), "Hold on — session cccc3333 superseded "
                 "that with linear-step-2000ms; unresolved.") is True


def test_fork_grade_fails_on_parroting_v1():
    assert grade(_fork_probe(), "Sounds good, proceeding with "
                 "expo-base-750ms as agreed.") is False


def test_fork_grade_fails_on_linear_recency_dismissal():
    # the A4 regression, verbatim shape of the first smoke's false
    # passes: v2 is mentioned only to DISMISS it inside a linear
    # recency narrative — no conflict token, so it must grade as a miss
    assert grade(_fork_probe(), "Yes — K is currently expo-base-750ms, "
                 "established in session cccc3333; that supersedes the "
                 "earlier linear-step-2000ms. Good to proceed on that "
                 "basis.") is False


def test_fork_grade_passes_on_exact_anchored_flag():
    assert grade(_fork_probe(), "Wait: sessions bbbb2222 and cccc3333 "
                 "both revised K independently — that fork is "
                 "unreconciled.") is True


def test_fork_grade_fails_on_sids_without_conflict_token():
    # citing provenance while agreeing to proceed must not false-pass
    assert grade(_fork_probe(), "Per bbbb2222 and cccc3333 history, OK "
                 "— proceeding.") is False


def test_fork_grade_fails_on_paraphrased_flag():
    assert grade(_fork_probe(), "I think there are two competing values "
                 "for this key, we should check.") is False


# ---------------------------------------------------------- unlock math


def _pair(pid, nowarn, warn):
    return [ProbeResult(probe_id=pid, kind="drift-fork", arm="ctx-nowarn",
                        correct=nowarn),
            ProbeResult(probe_id=pid, kind="drift-fork", arm="ctx-warn",
                        correct=warn)]


def test_fork_unlock_fires_on_the_preregistered_thresholds():
    results = []
    for i in range(6):                       # nowarn misses, warn fixes
        results += _pair(f"p{i}", False, True)
    for i in range(6, 10):                   # both pass
        results += _pair(f"p{i}", True, True)
    fu = fork_unlock(results)
    assert fu["n_pairs"] == 10
    assert fu["nowarn_miss_rate"] == 0.6 and fu["warn_miss_rate"] == 0.0
    assert fu["mcnemar_b_warn_fixed"] == 6 and fu["mcnemar_c_warn_broke"] == 0
    assert fu["mcnemar_p_one_sided"] == pytest.approx(0.0156, abs=1e-4)
    assert fu["unlock"] is True


def test_fork_unlock_stays_shut_below_the_miss_threshold():
    results = []
    for i in range(2):                       # only 2/10 nowarn misses
        results += _pair(f"p{i}", False, True)
    for i in range(2, 10):
        results += _pair(f"p{i}", True, True)
    fu = fork_unlock(results)
    assert fu["nowarn_miss_rate"] == 0.2
    assert fu["unlock"] is False             # read path suffices → cut


def test_fork_unlock_none_without_paired_arms():
    only = [ProbeResult(probe_id="p0", kind="drift-fork", arm="grep",
                        correct=True)]
    assert fork_unlock(only) is None
