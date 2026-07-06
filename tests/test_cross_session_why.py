"""Cross-session `why` (memory feedback #6): a value banked in an earlier
session must be recoverable while resuming on a later one. Single-session
`session_why` only sees the doc it is handed; `session_why_across` folds
the whole ledger. Eval-first — the first test IS the gap.
"""

import json

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.session_reader import (
    load_session,
    session_why,
    session_why_across,
)
from ctxpack.core import factid


def _entry(etype, content, sid, ts="2026-07-06T09:00:00Z"):
    return {"type": etype, "sessionId": sid, "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _bank(tmp_path, out, sid, text, kind="assistant"):
    content = text if kind == "user" else [{"type": "text", "text": text}]
    p = tmp_path / f"{sid}.jsonl"
    p.write_text(json.dumps(_entry(kind, content, sid)), encoding="utf-8")
    run_checkpoint(str(p), str(out), as_of="2026-07-06")


def test_across_recovers_fact_from_an_earlier_session(tmp_path):
    out = tmp_path / "ctx"
    _bank(tmp_path, out, "aaaa1111-s",
          "Decision: route webhooks through the quokka gateway because it "
          "dedupes retries.")
    _bank(tmp_path, out, "bbbb2222-s",
          "Decision: adopt exponential backoff for the vendor client.")

    # the gap: single-session `why` on the latest session (B) can't see A
    docb, sidb = load_session(str(out))
    assert session_why(docb, sidb, "quokka")["found"] is False

    # the fix: cross-session `why` recovers it, tagged with its source
    res = session_why_across(str(out), "quokka")
    assert res["found"] is True and res["count"] >= 1
    assert res["matches"][0]["session"].startswith("aaaa1111")
    assert res["sessions_searched"] >= 2


def test_across_scopes_to_one_session(tmp_path):
    out = tmp_path / "ctx"
    _bank(tmp_path, out, "aaaa1111-s", "Decision: use the quokka gateway.")
    _bank(tmp_path, out, "bbbb2222-s", "Decision: use the quokka gateway too.")

    a = session_why_across(str(out), "quokka", session="aaaa1111")
    assert a["sessions_searched"] == 1
    assert all(m["session"].startswith("aaaa1111") for m in a["matches"])
    b = session_why_across(str(out), "quokka", session="bbbb2222")
    assert all(m["session"].startswith("bbbb2222") for m in b["matches"])


def test_across_ranks_most_recent_session_first(tmp_path):
    out = tmp_path / "ctx"
    _bank(tmp_path, out, "aaaa1111-s",
          "Decision: pin the vendor timeout to 30s for the pipeline.")
    _bank(tmp_path, out, "bbbb2222-s",
          "Decision: pin the vendor timeout to 30s for the pipeline again.")

    res = session_why_across(str(out), "vendor timeout")
    assert res["count"] >= 2                     # matched in both sessions
    assert res["matches"][0]["session"].startswith("bbbb2222")  # recent wins ties


def test_across_absence_is_asserted_over_the_whole_ledger(tmp_path):
    out = tmp_path / "ctx"
    _bank(tmp_path, out, "aaaa1111-s", "Decision: use the quokka gateway.")
    _bank(tmp_path, out, "bbbb2222-s", "Decision: use exponential backoff.")

    res = session_why_across(str(out), "NONEXISTENT-XYZ-THING")
    assert res["found"] is False and res["count"] == 0
    assert res["sessions_searched"] == 2
    assert "not in memory" in res["note"]


_CONSTRAINT = "Do not run the $60 full pass until cost reporting is fixed."
_CFID = factid.fact_id("CONSTRAINT", _CONSTRAINT)


def test_across_surfaces_a_cross_session_fork(tmp_path):
    # a fork whose heads live in DIFFERENT sessions — the whole reason the
    # DAG folds events.jsonl (cross-session) rather than one session's doc
    out = tmp_path / "ctx"
    _bank(tmp_path, out, "aaaa1111-s", f"Plan the run. {_CONSTRAINT}", kind="user")
    for sid, tag in (("bbbb2222-s", "tonight"), ("cccc3333-s", "tomorrow")):
        _bank(tmp_path, out, sid,
              f"Decision: run the $60 full pass {tag} for the numbers.\n"
              f"Supersedes: {_CFID} — cost reporting handled {tag}.")

    res = session_why_across(str(out), "cost reporting")
    assert res.get("has_conflict") is True
    fork = next(m["supersession"] for m in res["matches"] if "supersession" in m)
    assert fork["conflict"] is not None
    assert len(fork["conflict"]["heads"]) == 2


def test_across_empty_key_is_an_error(tmp_path):
    out = tmp_path / "ctx"
    _bank(tmp_path, out, "aaaa1111-s", "Decision: use the quokka gateway.")
    assert session_why_across(str(out), "   ")["error"]


# ------------------ Q1 resolution: `why` defaults to cross-session -----------


def test_cli_why_defaults_to_cross_session(tmp_path, capsys):
    from ctxpack.cli.main import main

    out = tmp_path / "ctx"
    _bank(tmp_path, out, "aaaa1111-s", "Decision: use the quokka gateway.")
    _bank(tmp_path, out, "bbbb2222-s", "Decision: use exponential backoff.")

    # default: no --session → searches the whole ledger, recovers A's fact
    rc = main(["session", "why", "quokka", "--ledger", str(out)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["found"] is True
    assert payload["sessions_searched"] >= 2

    # --session <id> preserves explicit single-session scope: B can't see A
    rc = main(["session", "why", "quokka", "--ledger", str(out),
               "--session", "bbbb2222"])
    assert rc == 0
    scoped = json.loads(capsys.readouterr().out)
    assert scoped["found"] is False
    assert "sessions_searched" not in scoped  # single-session shape


def test_mcp_why_defaults_to_cross_session(tmp_path):
    from ctxpack.integrations import mcp_server as srv

    out = tmp_path / "ctx"
    _bank(tmp_path, out, "aaaa1111-s", "Decision: use the quokka gateway.")
    _bank(tmp_path, out, "bbbb2222-s", "Decision: use exponential backoff.")

    default = json.loads(srv.handle_session_why(
        {"ledger_dir": str(out), "key": "quokka"}))
    assert default["found"] is True and default["sessions_searched"] >= 2

    scoped = json.loads(srv.handle_session_why(
        {"ledger_dir": str(out), "key": "quokka", "session": "bbbb2222"}))
    assert scoped["found"] is False
