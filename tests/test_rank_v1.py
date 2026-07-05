"""rank/v1 — event-sourced salience fold (spec v1.1 §6).

The labeled fixture is a REAL dogfood session (KP_SDLC ca35891c, 1406
turns, events regenerated from the raw transcript): the ratified
eval-first drift plan named which facts must rise and which must sink.
Ranking is a deterministic fold over ctx-events/v1 rows only — same
file, same scores, forever. Guards under test: constraints keep a rank
floor, event boosts are capped (no rich-get-richer), eval-workspace
rows are excluded by transcript-derived cwd, and rank/v0 stays the
byte-identical A/B baseline.
"""

import json
from pathlib import Path

import pytest

from ctxpack.core import rank

FIXDIR = Path(__file__).parent / "fixtures" / "rank_v1"


def _fixture_rows():
    return [json.loads(line) for line in
            (FIXDIR / "kp_sdlc_ca35891c_events.jsonl")
            .read_text(encoding="utf-8").splitlines()]


def _labels():
    return json.loads((FIXDIR / "labels.json").read_text(encoding="utf-8"))


def _row(event="fact_asserted", fact_id="f" * 16, session="s1", turn=1,
         cwd="", **detail):
    r = {"schema": "ctx-events/v1", "session": session,
         "checkpoint": "c" * 12, "event": event, "fact_id": fact_id,
         "turn": turn, "detail": detail}
    if cwd:
        r["cwd"] = cwd
    return r


# ------------------------------------------------- ratified fixture labels


def test_ratified_fixture_rise_beats_sink():
    labels = _labels()
    scores = rank.fold_events(_fixture_rows(),
                              project_root=labels["project_root"])
    rise = {fid: scores[fid] for fid in labels["rise"]}
    sink = {fid: scores[fid] for fid in labels["sink"]}
    assert min(rise.values()) > max(sink.values()), (
        f"rise={rise} sink={sink}")


def test_verdict_alias_sinks_below_canonical_decision():
    scores = rank.fold_events(_fixture_rows(),
                              project_root=_labels()["project_root"])
    verdict = scores["204a9205aaa6de52"]   # turn 74 "Verdict: ..."
    canonical = scores["93ae4a635b484199"]  # turn 813 "Decision: ..."
    assert verdict < canonical


def test_junk_decisions_sink_below_exact_identifiers():
    # the differentiation axis vs grep is literal EXACTNESS — junk prose
    # must never crowd a git_sha out of the gist
    rows = _fixture_rows()
    scores = rank.fold_events(rows, project_root=_labels()["project_root"])
    sha_scores = [scores[r["fact_id"]] for r in rows
                  if r["event"] == "fact_asserted"
                  and r["detail"].get("literal_kind") == "git_sha"]
    assert sha_scores
    for junk in ("7c48aa3fe980c0b5", "204a9205aaa6de52", "f40022fd6baa6b8a"):
        assert scores[junk] < min(sha_scores)


def test_fold_is_deterministic():
    rows = _fixture_rows()
    root = _labels()["project_root"]
    assert rank.fold_events(rows, project_root=root) == \
        rank.fold_events(rows, project_root=root)


# ------------------------------------------------------- floors and caps


def test_constraint_floor_survives_demotion():
    rows = [
        _row(fact_id="c" * 16, kind="CONSTRAINT", basis="user_imperative"),
        _row(event="incident", fact_id="c" * 16, turn=5,
             incident_id="i1", type="wrong"),
        _row(event="incident", fact_id="c" * 16, turn=9,
             incident_id="i2", type="stale"),
    ]
    scores = rank.fold_events(rows)
    assert scores["c" * 16] >= rank.CONSTRAINT_FLOOR


def test_incident_boost_and_demotion_capped():
    up = [_row(fact_id="a" * 16, kind="LITERAL", basis="literal_extractor",
               literal_kind="git_sha")]
    up += [_row(event="incident", fact_id="a" * 16, turn=i,
                incident_id=f"i{i}", type="saved") for i in range(6)]
    down = [_row(fact_id="b" * 16, kind="DECISION", basis="marker_stated",
                 marker="decision")]
    down += [_row(event="incident", fact_id="b" * 16, turn=i,
                  incident_id=f"j{i}", type="wrong") for i in range(6)]
    scores = rank.fold_events(up + down)
    lo, hi = rank.INCIDENT_CAP
    assert scores["a" * 16] <= 1.8 + hi + rank.RECENCY_EPSILON + 1e-9
    assert scores["b" * 16] >= 2.4 + lo - 1e-9


def test_reassertion_boost_capped():
    rows = [_row(fact_id="a" * 16, session=f"s{i}", kind="LITERAL",
                 basis="literal_extractor", literal_kind="git_sha")
            for i in range(9)]
    scores = rank.fold_events(rows)
    assert scores["a" * 16] <= (1.8 + rank.REASSERT_CAP
                                + rank.RECENCY_EPSILON + 1e-9)


def test_cross_session_reassertion_raises():
    once = [_row(fact_id="a" * 16, session="s1", kind="LITERAL",
                 basis="literal_extractor", literal_kind="path")]
    twice = once + [_row(fact_id="a" * 16, session="s2", kind="LITERAL",
                         basis="literal_extractor", literal_kind="path")]
    assert rank.fold_events(twice)["a" * 16] > \
        rank.fold_events(once)["a" * 16]


def test_incident_rows_dedup_by_incident_id():
    # incidents re-emit at every checkpoint — the fold must count each once
    rows = [_row(fact_id="a" * 16, kind="LITERAL",
                 basis="literal_extractor", literal_kind="git_sha")]
    rows += [_row(event="incident", fact_id="a" * 16, turn=3,
                  incident_id="same-incident", type="saved")] * 4
    score = rank.fold_events(rows)["a" * 16]
    assert score == pytest.approx(1.8 + 0.5, abs=rank.RECENCY_EPSILON)


# ------------------------------------------------ eval-traffic exclusion


def test_eval_workspace_rows_excluded_by_cwd():
    root = r"C:\repo"
    rows = [
        _row(fact_id="a" * 16, cwd=r"C:\repo", kind="DECISION",
             basis="marker_stated", marker="decision"),
        _row(fact_id="b" * 16, cwd=r"C:\repo\bench\workspace-3",
             kind="DECISION", basis="marker_stated", marker="decision"),
        _row(fact_id="d" * 16, kind="DECISION",  # pre-cwd-stamp row: kept
             basis="marker_stated", marker="decision"),
    ]
    scores = rank.fold_events(rows, project_root=root)
    assert "a" * 16 in scores
    assert "d" * 16 in scores
    assert "b" * 16 not in scores  # benchmark harness traffic


def test_no_project_root_keeps_everything():
    rows = [_row(fact_id="a" * 16, cwd=r"C:\anywhere", kind="ERROR",
                 basis="structural")]
    assert "a" * 16 in rank.fold_events(rows)


# ------------------------------------------------- policy contract


def test_v0_returns_empty_and_unknown_raises():
    rows = _fixture_rows()
    assert rank.fold_events(rows, policy=rank.RANK_POLICY_V0) == {}
    with pytest.raises(ValueError):
        rank.fold_events(rows, policy="rank/v9-vibes")


def test_resolve_policy_fail_open():
    assert rank.resolve_policy({}) == rank.DEFAULT_RANK_POLICY
    assert rank.resolve_policy(
        {"CTXPACK_RANK_POLICY": rank.RANK_POLICY_V0}) == rank.RANK_POLICY_V0
    # a typo in a hook environment must never break a checkpoint
    assert rank.resolve_policy(
        {"CTXPACK_RANK_POLICY": "rank/v1-tpyo"}) == rank.DEFAULT_RANK_POLICY


def test_inferred_penalty_scoped_to_decisions():
    # FAILED-APPROACH is verb-extracted (basis inferred) but its pattern
    # IS the documented dead-end convention — "do not retry" facts must
    # not sink below number_unit table noise
    rows = [
        _row(fact_id="a" * 16, kind="FAILED-APPROACH", basis="inferred"),
        _row(fact_id="b" * 16, kind="LITERAL", basis="literal_extractor",
             literal_kind="number_unit"),
        _row(fact_id="e" * 16, kind="DECISION", basis="inferred"),
    ]
    scores = rank.fold_events(rows)
    assert scores["a" * 16] > scores["b" * 16] > scores["e" * 16]


def test_legacy_truncated_kinds_normalize():
    legacy = rank.fold_events(
        [_row(fact_id="a" * 16, kind="FAILED", basis="marker_stated")])
    full = rank.fold_events(
        [_row(fact_id="a" * 16, kind="FAILED-APPROACH",
              basis="marker_stated")])
    assert legacy["a" * 16] == full["a" * 16]


# ------------------------------------------------- gist consumption


def _entry(etype, content, ts="2026-07-05T09:00:00Z"):
    return {"type": etype, "sessionId": "rank1234-session", "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _write(tmp_path, entries, name="session.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in entries),
                    encoding="utf-8")
    return str(path)


def _fid(entity):
    return next((f.value for f in entity.fields if f.key == "FACT-ID"), "")


def test_gist_literal_cap_keeps_highest_rank_identifiers(tmp_path,
                                                         monkeypatch):
    # 6 early git_shas + 45 late percentages: recency-only capping (v0)
    # would evict every sha; rank/v1 must keep them all
    from ctxpack.agent.checkpoint import run_checkpoint

    monkeypatch.delenv("CTXPACK_RANK_POLICY", raising=False)
    shas = [f"deadbeef{i:04d}" for i in range(6)]
    entries = [_entry("assistant", [{"type": "text", "text":
               "Shipped as commits "
               + ", ".join(f"`{s}`" for s in shas) + "."}])]
    entries += [_entry("assistant", [{"type": "text", "text":
                f"Coverage moved to {i}.{i % 10}% on shard {i}."}])
                for i in range(1, 46)]
    out = str(tmp_path / "ctx")
    run_checkpoint(_write(tmp_path, entries), out, as_of="2026-07-05")
    gist = (tmp_path / "ctx" / "latest-gist.md").read_text(encoding="utf-8")
    for sha in shas:
        assert sha in gist, f"high-rank sha {sha} evicted from gist"
    assert "highest-rank" in gist and "most-recent" not in gist


def test_gist_trim_evicts_lowest_rank_decision_first(tmp_path, monkeypatch):
    import ctxpack.agent.checkpoint as cp
    from ctxpack.agent.transcript_parser import parse_transcript

    entries = [_entry("assistant", [{"type": "text", "text":
        "Decision: keep the auth flow single-tenant because the SLA "
        "demands isolation.\n"
        "We chose sqlite for the scratch queue."}])]
    parsed = parse_transcript(_write(tmp_path, entries))
    decisions = [e for e in parsed.corpus.entities
                 if e.name.startswith("DECISION")]
    assert len(decisions) == 2
    ranks = {_fid(e): rank.prior_for(
        "DECISION",
        basis=next(f.value for f in e.fields if f.key == "BASIS"))
        for e in decisions}

    full = cp.build_gist(parsed, ranks=ranks)
    monkeypatch.setattr(cp, "GIST_BPE_BUDGET", cp._count_bpe(full) - 1)
    trimmed = cp.build_gist(parsed, ranks=ranks)
    assert "auth flow single-tenant" in trimmed   # marker decision survives
    assert "sqlite" not in trimmed                # inferred junk evicted


def test_legacy_gist_unchanged_without_ranks(tmp_path):
    # rank/v0 is the A/B baseline: no ranks → byte-identical legacy render
    from ctxpack.agent.checkpoint import build_gist
    from ctxpack.agent.transcript_parser import parse_transcript

    entries = [_entry("user", "Fix retries. Never bypass the rate limiter."),
               _entry("assistant", [{"type": "text", "text":
                      "Decision: use exponential backoff."}])]
    parsed = parse_transcript(_write(tmp_path, entries))
    assert build_gist(parsed) == build_gist(parsed, ranks=None)
    assert "most-recent" not in build_gist(parsed)  # cap note absent under cap


# ------------------------------------------------- emitter enrichment


def test_emitter_stamps_marker_literal_kind_and_full_kinds(tmp_path,
                                                           monkeypatch):
    from ctxpack.agent.checkpoint import run_checkpoint

    monkeypatch.delenv("CTXPACK_RANK_POLICY", raising=False)
    entries = [
        _entry("user", "Ship it. Never push straight to main."),
        _entry("assistant", [{"type": "text", "text":
               "Decision: pin the retry base at 750ms.\n"
               "Verdict: the migration held up under replay.\n"
               "The rollback approach didn't work because the schema "
               "drifted.\n"
               "Landed as commit deadbeef1234."}]),
    ]
    run_checkpoint(_write(tmp_path, entries), str(tmp_path / "ctx"),
                   as_of="2026-07-05")
    rows = [json.loads(l) for l in (tmp_path / "ctx" / "events.jsonl")
            .read_text(encoding="utf-8").splitlines()]
    asserted = [r for r in rows if r["event"] == "fact_asserted"]
    kinds = {r["detail"]["kind"] for r in asserted}
    assert "USER-REQUEST" in kinds          # no first-hyphen truncation
    assert "FAILED-APPROACH" in kinds
    markers = {r["detail"].get("marker") for r in asserted
               if r["detail"]["kind"] == "DECISION"}
    assert "decision" in markers and "verdict" in markers
    literal_kinds = {r["detail"].get("literal_kind") for r in asserted
                     if r["detail"]["kind"] == "LITERAL"}
    assert "git_sha" in literal_kinds
