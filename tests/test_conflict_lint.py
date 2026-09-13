"""Decision-conflict lint — drift governance (ratified 2026-07-05).

Contract under test: precision-first (silent unless the match is
exact), deterministic, checkpoint-time; the override path is
`Supersedes: <fact_id> — <reason>`; the goal is "never change decisions
silently", not "never change decisions". The flagship scenario is the
real drift probe: a banked "$60 full pass" constraint vs a later
session's decision to run it.
"""

import json

import pytest

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.core import factid, rank

CONSTRAINT_TEXT = ("Do not run the $60 full pass until cost reporting "
                   "is fixed.")
CONSTRAINT_FID = factid.fact_id("CONSTRAINT", CONSTRAINT_TEXT)
DRIFT_DECISION = ("Decision: run the $60 full pass tonight to get the "
                  "six-arm numbers.")


def _entry(etype, content, sid="aaaa1111-session",
           ts="2026-07-06T09:00:00Z"):
    return {"type": etype, "sessionId": sid, "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _write(tmp_path, entries, name):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in entries),
                    encoding="utf-8")
    return str(path)


def _session_a(tmp_path):
    """Earlier session banking the constraint."""
    entries = [_entry("user", f"Plan the eval run. {CONSTRAINT_TEXT}")]
    return _write(tmp_path, entries, "a.jsonl")


def _session_b(tmp_path, text):
    entries = [_entry("assistant", [{"type": "text", "text": text}],
                      sid="bbbb2222-session")]
    return _write(tmp_path, entries, "b.jsonl")


def _events(out):
    return [json.loads(l) for l in (out / "events.jsonl")
            .read_text(encoding="utf-8").splitlines()]


def _journal_tail(out):
    lines = (out / "checkpoints.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1])


# ------------------------------------------------- flagship drift case


def test_cross_session_constraint_collision_flags(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    run_checkpoint(_session_b(tmp_path, DRIFT_DECISION), str(out),
                   as_of="2026-07-06")

    conflicts = [r for r in _events(out) if r["event"] == "conflict"]
    assert len(conflicts) == 1
    row = conflicts[0]
    assert row["detail"]["case"] == "constraint_collision"
    assert row["detail"]["against_fact_id"] == CONSTRAINT_FID
    assert "$60 full pass" in row["detail"]["phrase"]
    assert row["detail"]["resolved"] is False

    gist = (out / "session-bbbb2222-gist.md").read_text(encoding="utf-8")
    assert "Decision conflicts (UNRESOLVED" in gist
    assert "Supersedes: <fact_id>" in gist
    assert CONSTRAINT_FID in gist

    journal = _journal_tail(out)
    assert journal["lint_conflicts"] == 1
    assert journal["lint_resolved"] == 0


def test_supersedes_override_resolves(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    text = (DRIFT_DECISION + "\n"
            f"Supersedes: {CONSTRAINT_FID} — cost reporting landed in "
            "commit `deadbeef1234`.")
    run_checkpoint(_session_b(tmp_path, text), str(out),
                   as_of="2026-07-06")

    rows = _events(out)
    conflict = next(r for r in rows if r["event"] == "conflict")
    assert conflict["detail"]["resolved"] is True
    superseded = next(r for r in rows if r["event"] == "fact_superseded")
    assert superseded["fact_id"] == CONSTRAINT_FID
    assert "cost reporting landed" in superseded["detail"]["reason"]

    gist = (out / "session-bbbb2222-gist.md").read_text(encoding="utf-8")
    assert "UNRESOLVED" not in gist
    journal = _journal_tail(out)
    assert journal["lint_conflicts"] == 0
    assert journal["lint_resolved"] == 1

    # the fid in the Supersedes line must not be banked as a git_sha
    lits = [r for r in rows if r["event"] == "fact_asserted"
            and r["detail"]["kind"] == "LITERAL"]
    assert not any(r["fact_id"] == factid.fact_id(
        "LITERAL", CONSTRAINT_FID, key="git_sha") for r in lits)


def test_superseded_fact_demoted_in_rank_fold(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    text = (DRIFT_DECISION + "\n"
            f"Supersedes: {CONSTRAINT_FID} — cost reporting is fixed now.")
    run_checkpoint(_session_b(tmp_path, text), str(out),
                   as_of="2026-07-06")
    scores = rank.fold_events(rank.load_events(str(out / "events.jsonl")))
    # demoted, but a demoted constraint is still a constraint: floor holds
    assert scores[CONSTRAINT_FID] == pytest.approx(
        rank.CONSTRAINT_FLOOR, abs=rank.RECENCY_EPSILON)


# ------------------------------------------------- precision guards


def test_same_message_pair_is_exposition_not_drift(tmp_path):
    out = tmp_path / "ctx"
    text = (f"Constraint: never run the $60 full pass until cost "
            f"reporting is fixed.\n{DRIFT_DECISION}")
    run_checkpoint(_session_b(tmp_path, text), str(out),
                   as_of="2026-07-06")
    assert not [r for r in _events(out) if r["event"] == "conflict"]


def test_later_same_session_constraint_never_flags_earlier_decision(
        tmp_path):
    # review P1 repro: a decision must not be linted against a
    # constraint from a LATER turn of the same session — that is a
    # retroactive conflict from future text
    out = tmp_path / "ctx"
    entries = [
        _entry("assistant", [{"type": "text", "text": DRIFT_DECISION}],
               sid="dddd4444-session"),
        _entry("user", CONSTRAINT_TEXT, sid="dddd4444-session"),
    ]
    run_checkpoint(_write(tmp_path, entries, "d.jsonl"), str(out),
                   as_of="2026-07-06")
    assert not [r for r in _events(out) if r["event"] == "conflict"]


def test_earlier_same_session_constraint_flags_later_decision(tmp_path):
    # in-session drift (the CompactBench axis): constraint at an
    # earlier turn, conflicting decision later in the SAME session
    out = tmp_path / "ctx"
    entries = [
        _entry("user", f"Plan the eval run. {CONSTRAINT_TEXT}",
               sid="eeee5555-session"),
        _entry("assistant", [{"type": "text", "text": DRIFT_DECISION}],
               sid="eeee5555-session"),
    ]
    run_checkpoint(_write(tmp_path, entries, "e.jsonl"), str(out),
                   as_of="2026-07-06")
    rows = [r for r in _events(out) if r["event"] == "conflict"]
    assert len(rows) == 1
    assert rows[0]["detail"]["case"] == "constraint_collision"
    assert rows[0]["detail"]["resolved"] is False


def test_unrelated_decision_stays_silent(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    run_checkpoint(_session_b(
        tmp_path, "Decision: adopt exponential backoff for the vendor "
        "client because the limit is 40 req/min."), str(out),
        as_of="2026-07-06")
    assert not [r for r in _events(out) if r["event"] == "conflict"]
    gist = (out / "session-bbbb2222-gist.md").read_text(encoding="utf-8")
    assert "UNRESOLVED" not in gist


def test_glue_only_overlap_stays_silent(tmp_path):
    # a shared 5-gram of pure glue words is not evidence
    out = tmp_path / "ctx"
    a = [_entry("user", "You must not do it in the same way as before "
                "under any conditions.")]
    run_checkpoint(_write(tmp_path, a, "a.jsonl"), str(out),
                   as_of="2026-07-06")
    run_checkpoint(_session_b(
        tmp_path, "Decision: we will not do it in the same style."),
        str(out), as_of="2026-07-06")
    assert not [r for r in _events(out) if r["event"] == "conflict"]


def test_only_canonical_marker_decisions_are_linted(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    run_checkpoint(_session_b(
        tmp_path,
        "We chose to run the $60 full pass tonight for the numbers.\n"
        "Verdict: run the $60 full pass tonight and see."), str(out),
        as_of="2026-07-06")
    assert not [r for r in _events(out) if r["event"] == "conflict"]


def test_earlier_journal_order_only(tmp_path):
    # a constraint banked LATER must not retroactively flag an earlier
    # session's decision when its block is re-materialized
    out = tmp_path / "ctx"
    run_checkpoint(_session_b(tmp_path, DRIFT_DECISION), str(out),
                   as_of="2026-07-06")
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    run_checkpoint(str(tmp_path / "b.jsonl"), str(out),
                   as_of="2026-07-06")  # re-materialize B's block
    assert not [r for r in _events(out) if r["event"] == "conflict"]


# ------------------------------------------------- journal observability


def test_journal_lint_status_ok_on_clean_run(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    journal = _journal_tail(out)
    assert journal["lint_status"] == "ok"
    assert "lint_error" not in journal
    assert "lint_ledgers_skipped" not in journal


def test_journal_lint_status_error_when_lint_crashes(tmp_path, monkeypatch):
    # fail-open contract (review P2): the checkpoint hook still succeeds,
    # but the crash is journaled — "clean lint" and "lint crashed" must
    # not both read lint_conflicts=0 with nothing else to tell them apart.
    # TM-14 (Finding 1): the journal carries the stable status plus the
    # BOUNDED category only — the message text never persists.
    import ctxpack.agent.conflict_lint as cl

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic lint crash")

    monkeypatch.setattr(cl, "lint_decisions", boom)
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    journal = _journal_tail(out)
    assert journal["lint_status"] == "error"
    assert journal["lint_error"] == "runtime_error"     # category, not text
    assert "synthetic lint crash" not in json.dumps(journal)
    assert journal["lint_conflicts"] == 0
    # the crash is visible where a human reads: the gist says so
    gist = next(out.glob("session-*-gist.md")).read_text(encoding="utf-8")
    assert "Decision lint: FAILED" in gist


def test_lint_crash_with_secret_bearing_exception_leaks_no_ledger_byte(
        tmp_path, monkeypatch):
    """TM-14 (Finding 1): a lint crash whose exception MESSAGE and
    minted class NAME both embed a corpus secret leaves no secret byte
    in checkpoints.jsonl, the .ctx, any gist, or any other ledger file
    — only lint_status="error" plus the bounded category persist, and
    the checkpoint stays fail-open. RED on parent: the journal stored
    type(exc).__name__ + str(exc) verbatim."""
    import ctxpack.agent.conflict_lint as cl

    secret = "AKIAIOSFODNN7EXAMPLE"
    evil = type(secret, (RuntimeError,), {})

    def boom(*args, **kwargs):
        raise evil(f"crashed while holding {secret}")

    monkeypatch.setattr(cl, "lint_decisions", boom)
    out = tmp_path / "ctx"
    result = run_checkpoint(_session_a(tmp_path), str(out),
                            as_of="2026-07-06")
    assert result.lint_status == "error"        # fail-open, surfaced
    journal = _journal_tail(out)
    assert journal["lint_error"] == "runtime_error"
    for f in out.rglob("*"):
        if f.is_file():
            assert secret not in f.read_text(encoding="utf-8",
                                             errors="replace"), f.name


def test_journal_counts_skipped_unreadable_ledgers(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    # corrupt the banked ledger so the NEXT session's lint can't read it
    (out / "session-aaaa1111.ctx").write_bytes(b"\xff\xfe not utf-8")
    run_checkpoint(_session_b(tmp_path, DRIFT_DECISION), str(out),
                   as_of="2026-07-06")
    journal = _journal_tail(out)
    assert journal["lint_status"] == "ok"
    assert journal["lint_ledgers_skipped"] == 1
    # the skipped ledger's constraints were unreachable: no conflict row,
    # but the coverage gap is on the record instead of silent
    assert not [r for r in _events(out) if r["event"] == "conflict"
                and str(r["session"]).startswith("bbbb2222")]


# ------------------------------------------------- protected subjects


def test_protected_subject_flags_and_overrides(tmp_path):
    out = tmp_path / "ctx"
    out.mkdir()
    (out / "protected.json").write_text(json.dumps({
        "subjects": [{"phrase": "structural floor",
                      "reason": "protected surface changes need review"}],
    }), encoding="utf-8")

    run_checkpoint(_session_b(
        tmp_path, "Decision: add CLAUDE.md to the structural-floor "
        "protected surface for the receipts layer."), str(out),
        as_of="2026-07-06")
    rows = [r for r in _events(out) if r["event"] == "conflict"]
    assert len(rows) == 1
    assert rows[0]["detail"]["case"] == "protected_subject"
    assert rows[0]["detail"]["resolved"] is False

    # explicit override with a reason resolves it
    text = ("Decision: add CLAUDE.md to the structural-floor protected "
            "surface for the receipts layer.\n"
            f"Supersedes: {'0' * 16} — owner-approved change to the "
            "protected surface.")
    c = [_entry("assistant", [{"type": "text", "text": text}],
                sid="cccc3333-session")]
    run_checkpoint(_write(tmp_path, c, "c.jsonl"), str(out),
                   as_of="2026-07-06")
    rows = [r for r in _events(out) if r["event"] == "conflict"
            and str(r["session"]).startswith("cccc3333")]
    assert len(rows) == 1
    assert rows[0]["detail"]["resolved"] is True


# ------------------------------------------------- contract interplay


def test_rebuild_reproduces_conflict_rows(tmp_path):
    # events contract holds with lint rows in the block: journal-order
    # rebuild is byte-identical
    out = tmp_path / "ctx"
    run_checkpoint(_session_a(tmp_path), str(out), as_of="2026-07-06")
    run_checkpoint(_session_b(tmp_path, DRIFT_DECISION), str(out),
                   as_of="2026-07-06")
    original = (out / "events.jsonl").read_bytes()
    (out / "events.jsonl").unlink()
    run_checkpoint(str(tmp_path / "a.jsonl"), str(out), as_of="2026-07-06")
    run_checkpoint(str(tmp_path / "b.jsonl"), str(out), as_of="2026-07-06")
    assert (out / "events.jsonl").read_bytes() == original
