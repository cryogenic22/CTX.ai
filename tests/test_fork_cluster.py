"""drift-fork/v2 — cluster fixture, fixed-budget arms, negative
controls, receipts, cluster-level analysis (pre-registered A5,
PREREGISTRATION-resume-probe.md).

Built through the REAL producer (run_checkpoint), so these tests pin
the end-to-end contract: each cluster yields exactly two 2-head DAG
conflicts plus one linear chain; the no-fork variant yields zero
conflicts and an EMPTY product warning; budget parity between
ctx-nowarn-padded and ctx-warn holds per probe.
"""

from dataclasses import asdict

import pytest

from ctxpack.agent.session_reader import load_supersession
from ctxpack.benchmarks.agentic import fork_cluster as fc
from ctxpack.benchmarks.agentic.fork_fixture import fork_warn_block
from ctxpack.benchmarks.agentic.resume_probe import _norm


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    return fc.build_clusters(str(tmp_path_factory.mktemp("forkv2")), 1)[0]


@pytest.fixture(scope="module")
def plan(cluster):
    return fc.build_plan([cluster])


# ---------------------------------------------------------- validation


def test_full_table_validates():
    fc._validate_run()  # raises on any collision
    assert len(fc._CLUSTER_TABLE) == fc.N_CLUSTERS_PINNED


def test_pad_filler_is_clean():
    filler = _norm(" ".join((fc._PAD_HEADER,) + fc._PAD_SENTENCES))
    from ctxpack.benchmarks.agentic.resume_probe import _FORK_FLAG_TOKENS
    assert not any(t in filler for t in _FORK_FLAG_TOKENS)
    for _, rows in fc._CLUSTER_TABLE:
        for row in rows:
            assert _norm(row[0]) not in filler
            for v in row[1:]:
                assert _norm(v) not in filler


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


# ----------------------------------------------------------- run plan


def test_plan_rows_arms_and_parity(cluster, plan):
    rows, excluded = plan
    assert excluded == []
    assert len(rows) == 2 * len(fc.FORK_ARMS) + 2 * len(fc.CONTROL_ARMS)
    by_arm = {}
    for r in rows:
        by_arm.setdefault((r.probe.probe_id, r.arm), r)
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
        assert fc._PAD_HEADER in padded.context
        assert fc._PAD_HEADER not in warn.context


def test_plan_fork_receipts_all_pass(cluster, plan):
    rows, _ = plan
    for r in rows:
        if r.ptype == "fork" and r.arm in fc.PRIMARY_ARMS:
            assert r.receipts == {"v1_present": True, "v2_present": True,
                                  "base_present": True,
                                  "supersession_edges_present": True}, \
                f"{r.probe.probe_id}/{r.arm}: {r.receipts}"
            assert not r.excluded


def test_plan_false_alarm_arms_coincide(cluster, plan):
    # the product warning on a clean linear ledger is EMPTY, so the two
    # ctx arms coincide by construction (disclosed in A5 harness notes)
    rows, _ = plan
    fa_rows = [r for r in rows if r.ptype == "false-alarm"]
    assert len(fa_rows) == 2
    assert fa_rows[0].context == fa_rows[1].context
    assert {r.pad_delta for r in fa_rows} == {0, None}
    for r in fa_rows:
        assert r.fa_anchors == [cluster.fa.prior, cluster.fa.v0]


def test_plan_displacement_expected_present(plan):
    rows, _ = plan
    disp = [r for r in rows if r.ptype == "displacement"]
    assert len(disp) == 2
    for r in disp:
        assert r.receipts["expected_present"] is True


def test_fork_probe_excluded_on_any_failed_receipt():
    good = {"v1_present": True, "v2_present": True, "base_present": True,
            "supersession_edges_present": True}
    bad = dict(good, v2_present=False)
    assert fc.fork_probe_excluded(
        {"ctx-warn": good, "ctx-nowarn-padded": good}) is False
    assert fc.fork_probe_excluded(
        {"ctx-warn": good, "ctx-nowarn-padded": bad}) is True
    assert fc.fork_probe_excluded({"ctx-warn": good}) is True  # arm missing


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
        cluster="c01", ptype=ptype, arm="ctx-warn", context="",
        context_bpe=0, fa_anchors=anchors)


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


def test_false_alarm_gate():
    assert fc.false_alarm_gate(0, 8) is True
    assert fc.false_alarm_gate(1, 8) is True
    assert fc.false_alarm_gate(2, 8) is False
    assert fc.false_alarm_gate(0, 0) is False


def _result(cid, ptype, arm, correct, pid=None, flagged=None, bpe=100):
    return {"probe_id": pid or f"{cid}-{ptype}-{arm}", "cluster": cid,
            "ptype": ptype, "arm": arm, "correct": correct,
            "flagged": flagged, "excluded": False, "context_bpe": bpe}


def _cluster_rows(cid, padded_ok, warn_ok, fa_flagged=False):
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
    rows.append(_result(cid, "displacement", "ctx-nowarn-padded", True))
    rows.append(_result(cid, "displacement", "ctx-warn", True))
    for arm in ("ctx-nowarn-padded", "ctx-warn"):
        rows.append(_result(cid, "false-alarm", arm, not fa_flagged,
                            flagged=fa_flagged))
    return rows


def test_cluster_analysis_unlock_fires_on_pinned_thresholds():
    rows = []
    for i in range(8):
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=True)
    a = fc.cluster_analysis(rows)
    assert a["n_clusters"] == 8
    pr = a["primary"]
    assert pr["cluster_mean_miss_padded_nowarn"] == 1.0
    assert pr["cluster_mean_miss_warn"] == 0.0
    assert pr["sign_test"]["p_one_sided"] == pytest.approx(0.0039, abs=5e-4)
    assert a["false_alarm_gate"]["passed"] is True
    assert a["unlock"] is True
    assert a["additive_overhead_secondary"]["mean_warn_block_bpe"] == 40


def test_cluster_analysis_false_alarms_kill_the_unlock():
    rows = []
    for i in range(8):
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=True,
                              fa_flagged=(i < 2))
    a = fc.cluster_analysis(rows)
    assert a["primary"]["sign_test"]["p_one_sided"] < 0.05
    assert a["false_alarm_gate"]["passed"] is False
    assert len(a["false_alarm_gate"]["flagged_clusters"]) == 2
    assert a["unlock"] is False


def test_cluster_analysis_warn_misses_keep_it_shut():
    rows = []
    for i in range(8):                       # warn arm also misses
        rows += _cluster_rows(f"c{i:02d}", padded_ok=False, warn_ok=False)
    a = fc.cluster_analysis(rows)
    assert a["primary"]["sign_test"]["p_one_sided"] is None  # all ties
    assert a["unlock"] is False


def test_cluster_analysis_excluded_rows_are_ignored():
    rows = _cluster_rows("c00", padded_ok=False, warn_ok=True)
    rows += [dict(r, excluded=True, cluster="c99",
                  probe_id=r["probe_id"].replace("c00", "c99"))
             for r in list(rows)]
    a = fc.cluster_analysis(rows)
    assert a["n_clusters"] == 1
