"""Subagent/workflow verdict capture (feedback #5).

The main parse drops every sidechain, so review verdicts (APPROVE_WITH_NITS
/ BLOCK) never bank. Marker-GATED capture: only a marker-led sentence
(`Verdict:`/`Decision:`/…) in a sidechain banks, as a FINDING tagged
source=subagent. Unmarked sidechain chatter and isMeta harness lines stay
filtered.
"""

import json

from ctxpack.agent.transcript_parser import parse_transcript


def _entry(etype, text, *, sidechain=False, meta=False, sid="abcd1234-session"):
    return {"type": etype, "sessionId": sid,
            "timestamp": "2026-07-06T10:00:00Z",
            "isSidechain": sidechain, "isMeta": meta,
            "message": {"role": etype,
                        "content": [{"type": "text", "text": text}]}}


def _write(tmp_path, entries):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return str(p)


def _findings(parsed):
    out = []
    for e in parsed.corpus.entities:
        if e.name.startswith("FINDING"):
            val = next((f.value for f in e.fields if f.key == "FINDING"), "")
            src = next((f.value for f in e.fields if f.key == "SOURCE"), "")
            out.append((val, src))
    return out


def test_marker_led_sidechain_verdict_banks_as_finding(tmp_path):
    path = _write(tmp_path, [
        _entry("user", "Review the migration."),
        _entry("assistant", "Running the review subagent."),
        _entry("assistant",
               "Verdict: BLOCK the merge because the migration drops a "
               "not-null column without a backfill.", sidechain=True),
    ])
    findings = _findings(parse_transcript(path))
    assert len(findings) == 1
    val, src = findings[0]
    assert "BLOCK the merge" in val and src == "subagent"


def test_unmarked_sidechain_text_is_not_banked(tmp_path):
    path = _write(tmp_path, [
        _entry("assistant", "Main thread work."),
        _entry("assistant", "I looked at the diff and it seems fine overall.",
               sidechain=True),
    ])
    assert _findings(parse_transcript(path)) == []


def test_ismeta_is_never_banked(tmp_path):
    # isMeta is harness chatter — never a subagent verdict, even if marked
    path = _write(tmp_path, [
        _entry("assistant", "Main thread work."),
        _entry("assistant", "Verdict: APPROVE.", meta=True),
    ])
    assert _findings(parse_transcript(path)) == []


def test_finding_carries_fact_id_and_marker_basis(tmp_path):
    path = _write(tmp_path, [
        _entry("assistant", "spawning reviewer"),
        _entry("assistant", "Verdict: APPROVE_WITH_NITS — fix the typo in "
               "the docstring before merge.", sidechain=True),
    ])
    e = next(e for e in parse_transcript(path).corpus.entities
             if e.name.startswith("FINDING"))
    assert next(f.value for f in e.fields if f.key == "FACT-ID")
    assert next(f.value for f in e.fields if f.key == "BASIS") == "marker_stated"
    assert next(f.value for f in e.fields if f.key == "MARKER") == "verdict"


def test_verdict_recoverable_and_on_gist_end_to_end(tmp_path):
    from ctxpack.agent.checkpoint import run_checkpoint
    from ctxpack.agent.session_reader import load_session, session_why

    path = _write(tmp_path, [
        _entry("user", "Audit the auth change."),
        _entry("assistant", "Delegating to the security reviewer."),
        _entry("assistant",
               "Verdict: BLOCK — the token check is bypassable via a null "
               "algorithm header.", sidechain=True),
    ])
    out = tmp_path / "ctx"
    run_checkpoint(path, str(out), as_of="2026-07-06")

    doc, sid = load_session(str(out))
    assert session_why(doc, sid, "null algorithm header")["found"] is True

    gist = (out / "latest-gist.md").read_text(encoding="utf-8")
    assert "Subagent verdicts" in gist and "BLOCK" in gist


def test_verdicts_do_not_pollute_the_decision_lint(tmp_path):
    # a subagent FINDING is not a DECISION, so it never enters the conflict
    # lint (which only lints DECISION facts) — no conflict rows from it
    from ctxpack.agent.checkpoint import run_checkpoint

    path = _write(tmp_path, [
        _entry("user", "Do not run the $60 full pass until cost reporting "
                       "is fixed."),
        _entry("assistant",
               "Decision: run the $60 full pass now for the numbers.",
               sidechain=True),
    ])
    out = tmp_path / "ctx"
    run_checkpoint(path, str(out), as_of="2026-07-06")
    events = [json.loads(l) for l in
              (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert not [r for r in events if r["event"] == "conflict"]
    # ...but it DID bank as a finding
    assert any(r["event"] == "fact_asserted"
               and r["detail"].get("kind") == "FINDING" for r in events)
