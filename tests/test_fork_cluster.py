"""drift-fork/v2 — cluster fixture, fixed-budget arms, negative
controls, receipts, cluster-level analysis (pre-registered A5 +
harness notes v2, PREREGISTRATION-resume-probe.md).

Built through the REAL producer (run_checkpoint), so these tests pin
the end-to-end contract: each cluster yields exactly two 2-head DAG
conflicts plus one linear chain; the no-fork variant yields zero
conflicts; the v2 treatment is the PRODUCT warning (plan construction
therefore only runs where the product renderer exists — those tests
skip on a pre-feature branch, and one test asserts the abort there).
"""

from dataclasses import asdict

import pytest

from ctxpack.agent.session_reader import load_supersession
from ctxpack.benchmarks.agentic import fork_cluster as fc
from ctxpack.benchmarks.agentic.fork_fixture import fork_warn_block
from ctxpack.benchmarks.agentic.resume_probe import (
    _norm,
    conflict_flag_positive,
)

_PRODUCT = fc._product_header() is not None
needs_product = pytest.mark.skipif(
    not _PRODUCT,
    reason="product fork renderer absent on this branch — plan "
           "construction runs on feat/fork-surfacing-parked")


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    return fc.build_clusters(str(tmp_path_factory.mktemp("forkv2")), 1)[0]


@pytest.fixture(scope="module")
def deep_cluster(tmp_path_factory):
    # c03 is a pinned depth-2 cluster (the heads fork off a linear
    # revision, not the base) with head order b-then-c
    cid, rows = fc._CLUSTER_TABLE[2]
    return fc.build_cluster(str(tmp_path_factory.mktemp("forkv2deep")),
                            cid, 2, rows)


@pytest.fixture(scope="module")
def plan(cluster):
    if not _PRODUCT:
        pytest.skip("plan construction needs the product renderer")
    return fc.build_plan([cluster])


# ---------------------------------------------------------- validation


def test_full_table_validates():
    fc._validate_run()  # raises on any collision
    assert len(fc._CLUSTER_TABLE) == fc.N_CLUSTERS_PINNED
    assert set(fc._VARIATIONS) == {cid for cid, _ in fc._CLUSTER_TABLE}


def test_clusters_are_not_structural_clones():
    """Blocker 2: the pinned variation table must actually vary head
    order, depth, distractor load, timestamps, and phrasing."""
    vs = fc._VARIATIONS.values()
    assert len({v["head_order"] for v in vs}) > 1
    assert len({v["depth"] for v in vs}) > 1
    assert len({v["distractors"] for v in vs}) > 1
    assert len({v["ts"] for v in vs}) == len(fc._VARIATIONS)
    assert len({v["template"] for v in vs}) > 1
    assert len({v["q_variant"] for v in vs}) > 1


def test_pad_filler_is_clean():
    filler = _norm(" ".join((fc._PAD_HEADER,) + fc._PAD_SENTENCES))
    from ctxpack.benchmarks.agentic.resume_probe import _FORK_FLAG_TOKENS
    assert not any(t in filler for t in _FORK_FLAG_TOKENS)
    for _, rows in fc._CLUSTER_TABLE:
        for row in rows:
            assert _norm(row[0]) not in filler
            for v in row[1:]:
                assert _norm(v) not in filler


def test_manifest_sha_is_deterministic():
    assert fc.cluster_manifest_sha256() == fc.cluster_manifest_sha256()
    assert len(fc.cluster_manifest_sha256()) == 64


def test_require_exact_tokenizer_stamps():
    stamp = fc.require_exact_tokenizer()
    assert stamp.startswith("tiktoken ") and "cl100k_base" in stamp


def test_arm_order_counterbalances():
    orders = {fc.arm_order(i) for i in range(fc.N_CLUSTERS_PINNED)}
    assert len(orders) == len(fc.FORK_ARMS)      # full rotation coverage
    for i in range(fc.N_CLUSTERS_PINNED):
        assert sorted(fc.arm_order(i)) == sorted(fc.FORK_ARMS)
        assert sorted(fc.displacement_arm_order(i)) == sorted(
            fc.DISPLACEMENT_ARMS)


# ------------------------------------------------------------- fixture


def test_cluster_plants_two_forks_and_one_linear(cluster):
    _, graph = load_supersession(cluster.fork_ledger)
    assert len(graph.conflicts) == 2
    assert all(len(c.heads) == 2 for c in graph.conflicts)
    assert len(cluster.forks) == 2
    for f in cluster.forks:
        assert f.v1_fid < f.v2_fid          # A3 carried: deterministic draw
        assert f.v1 != f.v2
    # displacement key is a linear chain with a defined current value
    assert cluster.disp.current == fc._CLUSTER_TABLE[0][1][2][2]


def test_depth2_cluster_forks_off_the_revision(deep_cluster):
    """Blocker 2 (revision depth): in a depth-2 cluster the heads
    supersede a pinned linear REVISION (the fork sits deeper in the
    chain); the fold still roots the conflict at the chain origin."""
    from ctxpack.benchmarks.agentic.fork_fixture import _decision_rows

    rev = fc._REVISION_VALUES[deep_cluster.cid]
    _, graph = load_supersession(deep_cluster.fork_ledger)
    assert len(graph.conflicts) == 2
    rev_rows = _decision_rows(deep_cluster.fork_ledger,
                              f"{deep_cluster.cid}rrrrr")
    texts = " ".join(t for _, t, _ in rev_rows)
    for v in rev.values():
        assert v in texts                    # revision session banked vR
    roots = {r for c in graph.conflicts for r in c.roots}
    assert roots == {f.base_fid for f in deep_cluster.forks}
    for f in deep_cluster.forks:
        assert f.base_value not in rev.values()   # chain root = base


def test_nofork_variant_is_clean(cluster):
    _, graph = load_supersession(cluster.nofork_ledger)
    assert graph.conflicts == []
    assert fork_warn_block(cluster.nofork_ledger) == ""
    fa = cluster.fa
    assert (fa.v0, fa.prior, fa.current) == fc._CLUSTER_TABLE[0][1][0][1:]


def test_cluster_is_deterministic(cluster, tmp_path_factory):
    again = fc.build_clusters(str(tmp_path_factory.mktemp("forkv2b")), 1)[0]
    assert ([asdict(p) for _, p in fc.cluster_probes(again)]
            == [asdict(p) for _, p in fc.cluster_probes(cluster)])
    assert (fork_warn_block(again.fork_ledger)
            == fork_warn_block(cluster.fork_ledger))


# -------------------------------------------------------------- probes


def test_cluster_probe_shapes(cluster):
    probes = fc.cluster_probes(cluster)
    assert [pt for pt, _ in probes] == ["fork", "fork", "displacement",
                                        "false-alarm"]
    by_key = {f.key: f for f in cluster.forks}
    for pt, p in probes:
        if pt == "fork":
            f = by_key[p.probe_id.rsplit("-fork-", 1)[-1].upper()]
            assert f.v1 in p.question
            assert _norm(f.v2) not in _norm(p.question)
            assert p.expected == f.v2 and p.grade_mode == "fork"
        elif pt == "displacement":
            assert p.grade_mode == "exact"
            assert p.expected == cluster.disp.current
            assert cluster.disp.key in p.question
        else:
            assert cluster.fa.current in p.question     # TRUE current value
            assert _norm(cluster.fa.prior) not in _norm(p.question)
            assert p.expected == cluster.fa.prior


def test_question_variant_follows_the_pinned_table(cluster, deep_cluster):
    q1 = fc.cluster_probes(cluster)[0][1].question
    q2 = fc.cluster_probes(deep_cluster)[0][1].question
    v1 = fc._VARIATIONS[cluster.cid]["q_variant"]
    v2 = fc._VARIATIONS[deep_cluster.cid]["q_variant"]
    assert v1 != v2
    assert fc._QUESTION_VARIANTS[v1].split("{")[0] in q1
    assert fc._QUESTION_VARIANTS[v2].split("{")[0] in q2


# ------------------------------------------------------------- padding


def test_pad_to_bpe_reaches_target():
    base = "The base context text used for the padding parity check."
    from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
    target = count_bpe_tokens(base, model="claude") + 137
    padded, achieved, delta = fc.pad_to_bpe(base, target)
    assert padded.startswith(base)
    assert fc._PAD_HEADER in padded
    assert abs(delta) <= fc.PAD_DELTA_ABORT
    assert achieved + delta == target


def test_pad_to_bpe_no_padding_when_already_at_target():
    base = "Short text."
    from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
    cur = count_bpe_tokens(base, model="claude")
    padded, achieved, delta = fc.pad_to_bpe(base, cur)
    assert padded == base and achieved == cur and delta == 0


def test_fit_filler_grows_in_place():
    from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
    before, after = "PREFIX SECTION.\n", "\n## Decisions\ntail text"
    target = count_bpe_tokens(before + after, model="claude") + 90
    filler, achieved, delta = fc._fit_filler(before, after, target)
    assert filler.startswith(fc._PAD_HEADER)
    assert abs(delta) <= fc.PAD_DELTA_ABORT
    assert count_bpe_tokens(before + filler + after,
                            model="claude") == achieved


# --------------------------------------------- product-warning sourcing


@pytest.mark.skipif(_PRODUCT, reason="only meaningful pre-feature")
def test_plan_aborts_without_the_product_renderer(cluster):
    """Blocker 1 flip side: on a branch without the product renderer
    the harness must ABORT, never simulate the treatment."""
    with pytest.raises(RuntimeError, match="never simulates"):
        fc.build_plan([cluster])


@needs_product
def test_split_product_warning_roundtrips(cluster):
    from ctxpack.benchmarks.agentic.resume_probe import ctx_context
    probe = fc.cluster_probes(cluster)[0][1]
    context = ctx_context(cluster.fork_ledger, probe)
    before, warn, after = fc.split_product_warning(context)
    assert before + warn + after == context
    assert warn.startswith(fc._product_header())
    assert fc._product_header() not in before + after


# ----------------------------------------------------------- run plan


@needs_product
def test_plan_counts_and_parity(cluster, plan):
    assert len(plan) == fc.EXPECTED_COMPLETIONS_PER_CLUSTER
    by_arm = {}
    for r in plan:
        by_arm.setdefault((r.probe.probe_id, r.arm), r)
    header = fc._product_header()
    for f in cluster.forks:
        pid = f"{cluster.cid}-fork-{f.key.lower()}"
        warn = by_arm[(pid, "ctx-warn")]
        padded = by_arm[(pid, "ctx-nowarn-padded")]
        nowarn = by_arm[(pid, "ctx-nowarn")]
        grep = by_arm[(pid, "grep")]
        # fixed total budget: padded == warn within the pinned tolerance
        assert abs(warn.context_bpe - padded.context_bpe) \
            <= fc.PAD_DELTA_ABORT
        assert warn.context_bpe > nowarn.context_bpe
        assert grep.context_bpe <= warn.context_bpe
        # the treatment is the PRODUCT warning; the placebo replaces it
        # IN PLACE (blocker 1)
        assert header in warn.context
        assert header not in padded.context
        assert header not in nowarn.context
        assert fc._PAD_HEADER in padded.context
        assert fc._PAD_HEADER not in warn.context
        w_before, _blk, w_after = fc.split_product_warning(warn.context)
        assert padded.context.startswith(w_before)
        assert padded.context.endswith(w_after)
        assert padded.filler_sha256 and padded.filler_len
        assert warn.context_sha256 != padded.context_sha256


@needs_product
def test_plan_fork_receipts_all_pass(plan):
    for r in plan:
        if r.ptype == "fork" and r.arm in fc.PRIMARY_ARMS:
            assert r.receipts == {"v1_present": True, "v2_present": True,
                                  "base_present": True,
                                  "supersession_edges_present": True}, \
                f"{r.probe.probe_id}/{r.arm}: {r.receipts}"


@needs_product
def test_plan_false_alarm_is_one_completion_with_detector_receipt(
        cluster, plan):
    # blocker 8 + answers (a)/(b): the clean no-fork context is called
    # ONCE; the detector's own output is a separate receipt
    fa_rows = [r for r in plan if r.ptype == "false-alarm"]
    assert len(fa_rows) == 1
    row = fa_rows[0]
    assert row.arm == fc.FALSE_ALARM_ARM
    assert row.receipts["expected_present"] is True
    assert row.receipts["product_warning_absent"] is True
    assert row.receipts["fold_conflicts_zero"] is True
    assert row.receipts["candidates_file_absent"] is True
    assert row.fa_anchors == [cluster.fa.prior, cluster.fa.v0]


@needs_product
def test_plan_displacement_expected_present(plan):
    disp = [r for r in plan if r.ptype == "displacement"]
    assert len(disp) == 2
    for r in disp:
        assert r.receipts["expected_present"] is True


@needs_product
def test_plan_arm_order_is_counterbalanced(plan):
    fork_arms_seen = [r.arm for r in plan if r.ptype == "fork"]
    # cluster 0 rotation: arm_order(0) repeated per fork probe
    expected = list(fc.arm_order(0)) * 2
    assert fork_arms_seen == expected


# ------------------------------------------------------------- grading


def _row(ptype, expected="grain-300s-meanfold", anchors=None, alts=None):
    from ctxpack.benchmarks.agentic.resume_probe import Probe
    return fc.PlanRow(
        probe=Probe(probe_id="t", kind="x", session="c01eeeee", turn=1,
                    question="q", expected=expected,
                    grade_mode={"fork": "fork",
                                "displacement": "exact",
                                "false-alarm": "fork-inverted"}[ptype],
                    alt_all=alts),
        cluster="c01", cluster_index=0, ptype=ptype, arm="ctx-warn",
        context="", context_bpe=0, context_sha256="", fa_anchors=anchors)


def test_grade_row_displacement_exact():
    row = _row("displacement")
    assert fc.grade_row(row, "It is grain-300s-meanfold.") == (True, None)
    assert fc.grade_row(row, "It is grain-060s-rawline.") == (False, None)


def test_grade_row_false_alarm_flags_only_anchored_conflict():
    row = _row("false-alarm", expected="keep-30d-tiered",
               anchors=["keep-30d-tiered", "keep-07d-rolling"],
               alts=["c01eeeee", "c01fffff"])
    ok, flagged = fc.grade_row(row, "Yes — keep-90d-coldline is current, "
                               "proceeding.")
    assert (ok, flagged) == (True, False)
    ok, flagged = fc.grade_row(row, "Careful, there is a conflict with "
                               "keep-30d-tiered from earlier.")
    assert (ok, flagged) == (False, True)
    # conflict token without an exact anchor is NOT a flag (A4 inverted)
    ok, flagged = fc.grade_row(row, "There might be competing values "
                               "somewhere, but proceeding.")
    assert (ok, flagged) == (True, False)
    # anchor without a conflict token is NOT a flag
    ok, flagged = fc.grade_row(row, "Earlier it was keep-30d-tiered; "
                               "now it is current. Proceed.")
    assert (ok, flagged) == (True, False)


# --------------------------------------------- A4.1 polarity (blocker 3)


def test_negated_conflict_is_a_dismissal_not_a_false_alarm():
    """The reviewer's exact adversarial case: 'There is no conflict;
    vB was superseded' must NOT count as a flag."""
    row = _row("false-alarm", expected="keep-30d-tiered",
               anchors=["keep-30d-tiered", "keep-07d-rolling"],
               alts=["c01eeeee", "c01fffff"])
    ok, flagged = fc.grade_row(
        row, "There is no conflict; keep-30d-tiered was superseded and "
             "keep-90d-coldline is current.")
    assert (ok, flagged) == (True, False)


def test_negated_conflict_does_not_pass_the_fork_grade():
    """'not a conflict; v2 is old' must grade as a MISS."""
    row = _row("fork", alts=["c01bbbbb", "c01ccccc"])
    ok, _ = fc.grade_row(
        row, "This is not a conflict; grain-300s-meanfold is simply the "
             "old value. Proceed.")
    assert ok is False


def test_positive_conflict_still_passes_the_fork_grade():
    row = _row("fork", alts=["c01bbbbb", "c01ccccc"])
    ok, _ = fc.grade_row(
        row, "Hold on — there is an unreconciled fork here: "
             "grain-300s-meanfold was banked independently.")
    assert ok is True


def test_polarity_scope_is_the_clause():
    # a negator in a PREVIOUS clause must not neutralize the token
    assert conflict_flag_positive(_norm(
        "i cannot proceed: unresolved fork between the two heads"))
    assert conflict_flag_positive(_norm(
        "no objection at first glance, but this fork is real"))
    # negator within the token's own clause window neutralizes it
    assert not conflict_flag_positive(_norm(
        "there is no conflict here"))
    assert not conflict_flag_positive(_norm(
        "this is not an unresolved fork"))
    assert not conflict_flag_positive(_norm(
        "the values proceed without divergence"))


# ------------------------------------------------------ analysis math


def test_sign_test_known_values():
    assert fc.sign_test_one_sided(8, 0) == pytest.approx(1 / 256)
    assert fc.sign_test_one_sided(4, 4) == pytest.approx(0.6367, abs=1e-3)
    assert fc.sign_test_one_sided(0, 0) is None


def test_wilson_known_values():
    lo, hi = fc.wilson_interval(8, 8)
    assert lo == pytest.approx(0.676, abs=0.005) and hi == 1.0
    lo, hi = fc.wilson_interval(0, 8)
    assert lo == 0.0 and hi == pytest.approx(0.324, abs=0.005)
    assert fc.wilson_interval(0, 0) == [0.0, 0.0]


def test_false_alarm_gate_is_zero_tolerance():
    # hardened in v2 (blocker 8): ANY flagged cluster fails the gate
    assert fc.false_alarm_gate(0, 8) is True
    assert fc.false_alarm_gate(1, 8) is False
    assert fc.false_alarm_gate(2, 8) is False
    assert fc.false_alarm_gate(0, 0) is False


def _result(cid, ptype, arm, correct, pid=None, flagged=None, bpe=100):
    return {"probe_id": pid or f"{cid}-{ptype}-{arm}", "cluster": cid,
            "ptype": ptype, "arm": arm, "correct": correct,
            "flagged": flagged, "context_bpe": bpe}


def _cluster_rows(cid, padded_ok, warn_ok, fa_flagged=False,
                  disp_warn_ok=True, disp_padded_ok=True):
    rows = []
    for i in range(2):
        pid = f"{cid}-fork-k{i}"
        rows += [
            _result(cid, "fork", "ctx-nowarn", False, pid=pid, bpe=100),
            _result(cid, "fork", "ctx-nowarn-padded", padded_ok, pid=pid,
                    bpe=140),
            _result(cid, "fork", "ctx-warn", warn_ok, pid=pid, bpe=140),
            _result(cid, "fork", "grep", False, pid=pid, bpe=140),
        ]
    rows.append(_result(cid, "displacement", "ctx-nowarn-padded",
                        disp_padded_ok))
    rows.append(_result(cid, "displacement", "ctx-warn", disp_warn_ok))
    rows.append(_result(cid, "false-alarm", fc.FALSE_ALARM_ARM,
                        not fa_flagged, flagged=fa_flagged))
    return rows


def test_cluster_analysis_unlock_fires_on_pinned_thresholds():
    rows = []
    for i in range(8):
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=True)
    a = fc.cluster_analysis(rows)
    assert a["n_clusters"] == 8
    assert a["completeness"]["complete"] is True
    pr = a["primary"]
    assert pr["cluster_mean_miss_padded_nowarn"] == 1.0
    assert pr["cluster_mean_miss_warn"] == 0.0
    assert pr["sign_test"]["p_one_sided"] == pytest.approx(0.0039, abs=5e-4)
    assert a["false_alarm_gate"]["passed"] is True
    assert a["displacement_gate"]["passed"] is True
    assert a["unlock"] is True
    assert a["additive_overhead_secondary"]["mean_warn_block_bpe"] == 40


def test_cluster_analysis_single_false_alarm_kills_the_unlock():
    rows = []
    for i in range(8):
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=True,
                              fa_flagged=(i == 0))
    a = fc.cluster_analysis(rows)
    assert a["primary"]["sign_test"]["p_one_sided"] < 0.05
    assert a["false_alarm_gate"]["passed"] is False
    assert len(a["false_alarm_gate"]["flagged_clusters"]) == 1
    assert a["unlock"] is False


def test_cluster_analysis_displacement_harm_kills_the_unlock():
    # blocker 8: >1 harmful-discordant displacement clusters fail hard
    rows = []
    for i in range(8):
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=True,
                              disp_warn_ok=(i >= 2), disp_padded_ok=True)
    a = fc.cluster_analysis(rows)
    assert a["displacement_gate"]["harmful_discordant_clusters"] == 2
    assert a["displacement_gate"]["passed"] is False
    assert a["unlock"] is False


def test_cluster_analysis_one_harmful_discordant_is_tolerated():
    rows = []
    for i in range(8):
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=True,
                              disp_warn_ok=(i >= 1), disp_padded_ok=True)
    a = fc.cluster_analysis(rows)
    assert a["displacement_gate"]["harmful_discordant_clusters"] == 1
    assert a["displacement_gate"]["passed"] is True
    assert a["unlock"] is True


def test_cluster_analysis_warn_misses_keep_it_shut():
    rows = []
    for i in range(8):                       # warn arm also misses
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=False)
    a = fc.cluster_analysis(rows)
    assert a["primary"]["sign_test"]["p_one_sided"] is None  # all ties
    assert a["unlock"] is False


def test_cluster_analysis_incomplete_run_never_unlocks():
    # blocker 7: unlock requires EXACTLY the pinned 8 complete clusters
    rows = []
    for i in range(7):
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=True)
    a = fc.cluster_analysis(rows)
    assert a["completeness"]["complete"] is False
    assert a["primary"]["sign_test"]["p_one_sided"] < 0.05
    assert a["unlock"] is False
