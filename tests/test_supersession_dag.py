"""Supersession DAG — the eval-first contract (Slice 1) and its read-path
surfacing (Slice 2a).

The fold distinguishes a LINEAR REVISION (one current tip) from a BRANCH
CONFLICT (a base independently superseded by two facts → two competing
current values). Slice 2a surfaces that through ``session why`` without
touching the checkpoint write path or the gist. Pure/deterministic at the
fold layer; the read-path tests drive the real checkpoint producer.
"""

import json

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.session_reader import load_session, session_why
from ctxpack.core import factid
from ctxpack.core.supersession_dag import (
    build_graph,
    edges_from_events,
    fact_view,
)


def _ev(base, by, turn=0, reason="", session="s"):
    # real ctx-events/v1 shape: target at top level, superseding fact and
    # reason under `detail` (checkpoint.py `ev`). Reading `by`/`reason` at
    # the top level silently yields zero edges on real ledgers.
    return {"event": "fact_superseded", "fact_id": base, "turn": turn,
            "session": session, "detail": {"by": by, "reason": reason}}


# ----------------------------------------------------- fold contract (Slice 1)


def test_linear_chain_has_single_head_no_conflict():
    # A <- B <- C : C is the only current value; A and B are superseded
    g = build_graph(edges_from_events([_ev("A", "B", 1), _ev("B", "C", 2)]))
    assert g.heads == ["C"]
    assert g.superseded == ["A", "B"]
    assert g.conflicts == []
    assert g.status_of("A") == "superseded"
    assert g.status_of("C") == "current"


def test_branch_fork_is_flagged_with_both_competing_heads():
    # A superseded independently by B and by C — neither references the
    # other. This is the case a flat edge set silently collapses.
    g = build_graph(edges_from_events([_ev("A", "B", 1), _ev("A", "C", 2)]))
    assert g.heads == ["B", "C"]
    assert len(g.conflicts) == 1
    c = g.conflicts[0]
    assert c.heads == ["B", "C"]      # both current values surfaced
    assert c.roots == ["A"]           # the shared base
    assert c.facts == ["A", "B", "C"]


def test_diamond_reconciled_by_later_fact_is_not_a_conflict():
    # A <- B, A <- C, then D supersedes BOTH B and C : the fork closed,
    # D is the single current value — must NOT be reported as a conflict.
    g = build_graph(edges_from_events([
        _ev("A", "B", 1), _ev("A", "C", 2), _ev("B", "D", 3), _ev("C", "D", 4)]))
    assert g.heads == ["D"]
    assert g.conflicts == []


def test_independent_lineages_do_not_cross_contaminate():
    # X<-Y and P<-Q<-R are separate families; neither forks
    g = build_graph(edges_from_events([
        _ev("X", "Y"), _ev("P", "Q"), _ev("Q", "R")]))
    assert g.heads == ["R", "Y"]
    assert g.conflicts == []


def test_two_independent_forks_are_both_reported():
    g = build_graph(edges_from_events([
        _ev("A", "B"), _ev("A", "C"),     # fork 1
        _ev("P", "Q"), _ev("P", "R")]))   # fork 2
    assert len(g.conflicts) == 2
    assert sorted(c.roots for c in g.conflicts) == [["A"], ["P"]]


def test_edges_read_the_real_event_schema_and_drop_junk():
    events = [
        {"event": "fact_asserted", "fact_id": "A", "detail": {}},  # not an edge
        {"event": "fact_superseded", "fact_id": "A",
         "detail": {"by": "A"}},                                   # self-loop
        {"event": "fact_superseded", "fact_id": "A",
         "detail": {"by": ""}},                                    # blank head
        {"event": "fact_superseded", "fact_id": "A", "turn": 3,
         "session": "sX", "detail": {"by": "B", "reason": "landed"}},
    ]
    edges = edges_from_events(events)
    assert [(e.base, e.head) for e in edges] == [("A", "B")]
    assert edges[0].turn == 3
    assert edges[0].reason == "landed"
    assert edges[0].session == "sX"


def test_fold_is_order_independent():
    a = build_graph(edges_from_events([_ev("A", "B"), _ev("A", "C"), _ev("B", "D")]))
    b = build_graph(edges_from_events([_ev("B", "D"), _ev("A", "C"), _ev("A", "B")]))
    assert a == b


# ------------------------------------------------------ per-fact view (Slice 2a)


def test_fact_view_linear_reports_status_and_provenance():
    edges = edges_from_events([_ev("A", "B", turn=1, reason="revised", session="s2")])
    g = build_graph(edges)
    va = fact_view("A", edges, g)
    assert va["status"] == "superseded"
    assert va["superseded_by"] == [{"fact_id": "B", "turn": 1,
                                    "reason": "revised", "session": "s2"}]
    assert va["supersedes"] == []
    assert va["conflict"] is None
    vb = fact_view("B", edges, g)
    assert vb["status"] == "current"
    assert vb["supersedes"][0]["fact_id"] == "A"


def test_fact_view_fork_surfaces_conflict_for_every_member():
    edges = edges_from_events([_ev("A", "B", 1), _ev("A", "C", 2)])
    g = build_graph(edges)
    for fid in ("A", "B", "C"):
        v = fact_view(fid, edges, g)
        assert v["conflict"] == {"roots": ["A"], "heads": ["B", "C"],
                                 "facts": ["A", "B", "C"]}


def test_fact_view_diamond_is_reconciled_not_a_conflict():
    edges = edges_from_events([
        _ev("A", "B", 1), _ev("A", "C", 2), _ev("B", "D", 3), _ev("C", "D", 4)])
    g = build_graph(edges)
    vd = fact_view("D", edges, g)
    assert vd["status"] == "current" and vd["conflict"] is None
    assert sorted(x["fact_id"] for x in vd["supersedes"]) == ["B", "C"]
    va = fact_view("A", edges, g)          # base superseded, fork reconciled
    assert va["status"] == "superseded" and va["conflict"] is None


def test_fact_view_uninvolved_fact_is_none():
    edges = edges_from_events([_ev("A", "B")])
    assert fact_view("Z", edges, build_graph(edges)) is None


# --------------------------------------------- read path through session_why


_CONSTRAINT = "Do not run the $60 full pass until cost reporting is fixed."
_CFID = factid.fact_id("CONSTRAINT", _CONSTRAINT)


def _entry(etype, content, sid, ts="2026-07-06T09:00:00Z"):
    return {"type": etype, "sessionId": sid, "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _write(tmp_path, entries, name):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return str(p)


def _bank_constraint(tmp_path, out):
    run_checkpoint(_write(tmp_path, [
        _entry("user", f"Plan the run. {_CONSTRAINT}", "aaaa1111-s")],
        "a.jsonl"), str(out), as_of="2026-07-06")


def _supersession(match_bearing_result):
    return next(m["supersession"] for m in match_bearing_result["matches"]
                if "supersession" in m)


def test_why_annotates_linear_supersession_end_to_end(tmp_path):
    out = tmp_path / "ctx"
    _bank_constraint(tmp_path, out)
    decision = ("Decision: run the $60 full pass tonight for the six-arm "
                "numbers.\n"
                f"Supersedes: {_CFID} — cost reporting landed.")
    run_checkpoint(_write(tmp_path, [
        _entry("assistant", [{"type": "text", "text": decision}], "bbbb2222-s")],
        "b.jsonl"), str(out), as_of="2026-07-06")

    # the superseding decision (session B) reports what it supersedes
    docb, sidb = load_session(str(out), "bbbb2222")
    sup = _supersession(session_why(docb, sidb, "run the $60 full pass tonight",
                                    ledger_dir=str(out)))
    assert sup["status"] == "current"
    assert any(e["fact_id"] == _CFID for e in sup["supersedes"])
    assert "cost reporting landed" in sup["supersedes"][0]["reason"]

    # the constraint (session A) reports it was superseded, with provenance
    doca, sida = load_session(str(out), "aaaa1111")
    supa = _supersession(session_why(doca, sida, "cost reporting",
                                     ledger_dir=str(out)))
    assert supa["status"] == "superseded"
    assert supa["superseded_by"][0]["session"].startswith("bbbb2222")
    assert supa["conflict"] is None


def test_why_surfaces_fork_end_to_end(tmp_path):
    # two independent sessions each "resolve" the same constraint their own
    # way — the lint is satisfied (both declared Supersedes), but the DAG
    # catches the fork the lint cannot see. This is the DAG's added value.
    out = tmp_path / "ctx"
    _bank_constraint(tmp_path, out)
    for sid, tag in (("bbbb2222-s", "tonight"), ("cccc3333-s", "tomorrow")):
        d = (f"Decision: run the $60 full pass {tag} for the numbers.\n"
             f"Supersedes: {_CFID} — cost reporting handled {tag}.")
        run_checkpoint(_write(tmp_path, [
            _entry("assistant", [{"type": "text", "text": d}], sid)],
            f"{sid}.jsonl"), str(out), as_of="2026-07-06")

    doca, sida = load_session(str(out), "aaaa1111")
    wa = session_why(doca, sida, "cost reporting", ledger_dir=str(out))
    assert wa.get("has_conflict") is True
    supa = _supersession(wa)
    assert supa["status"] == "superseded"
    assert supa["conflict"] is not None
    assert len(supa["conflict"]["heads"]) == 2
    assert len(supa["superseded_by"]) == 2


def test_why_no_edges_stays_boring_and_identical(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, [
        _entry("assistant", [{"type": "text",
            "text": "Decision: adopt exponential backoff for the vendor "
                    "client because the limit is 40 req/min."}], "aaaa1111-s")],
        "a.jsonl"), str(out), as_of="2026-07-06")
    doc, sid = load_session(str(out), "aaaa1111")

    w = session_why(doc, sid, "exponential backoff", ledger_dir=str(out))
    assert w["found"] is True
    assert "has_conflict" not in w
    assert all("supersession" not in m for m in w["matches"])
    # a zero-edge ledger must read byte-for-byte like the no-DAG call
    assert w == session_why(doc, sid, "exponential backoff")


def test_why_diamond_reconciled_through_read_path(tmp_path):
    # the single-Supersedes producer can't emit a diamond, so synthesize
    # the events over the REAL fact_ids of banked decisions and drive the
    # read path: a reconciled fork must read as current, never a conflict.
    out = tmp_path / "ctx"
    text = "\n".join(
        f"Decision: choose option {name} for the pipeline stage."
        for name in ("alpha", "beta", "gamma", "delta"))
    run_checkpoint(_write(tmp_path, [
        _entry("assistant", [{"type": "text", "text": text}], "aaaa1111-s")],
        "a.jsonl"), str(out), as_of="2026-07-06")
    doc, sid = load_session(str(out), "aaaa1111")

    def fid(token):
        for m in session_why(doc, sid, token)["matches"]:
            for f in m["fields"]:
                if f["key"].upper() == "FACT-ID":
                    return f["value"]
        raise AssertionError(f"no fact for {token!r}")
    A, B, C, D = (fid(t) for t in ("alpha", "beta", "gamma", "delta"))

    def _row(base, by, turn):
        return {"schema": "ctx-events/v1", "session": "aaaa1111",
                "event": "fact_superseded", "fact_id": base, "turn": turn,
                "detail": {"by": by, "reason": "r"}}
    (out / "events.jsonl").write_text("\n".join(json.dumps(r) for r in (
        _row(A, B, 1), _row(A, C, 2), _row(B, D, 3), _row(C, D, 4))) + "\n",
        encoding="utf-8")

    supd = _supersession(session_why(doc, sid, "delta", ledger_dir=str(out)))
    assert supd["status"] == "current" and supd["conflict"] is None
    assert sorted(x["fact_id"] for x in supd["supersedes"]) == sorted([B, C])
    supa = _supersession(session_why(doc, sid, "alpha", ledger_dir=str(out)))
    assert supa["status"] == "superseded" and supa["conflict"] is None
