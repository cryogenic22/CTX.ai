"""Authority provenance (Loop 3, preflight backlog PF-03).

Extraction basis is NOT authority: `marker_stated` says how text was
matched, not who wrote it — an assistant emits Decision: markers
routinely. Authority derives from SOURCE-ROLE (stamped at parse) plus
explicit ratification events referencing a fact_id, and from nothing
else: not git presence, not a marker, not a merge.
"""

import json

from ctxpack.agent.ratification import (
    RATIFICATION_LOG,
    RATIFY,
    REJECT,
    is_ratified,
    ratification_state,
    record_ratification,
)
from ctxpack.agent.transcript_parser import parse_transcript
from ctxpack.cli.main import main
from ctxpack.core.factid import Authority, SourceRole, derive_authority


def _write(tmp_path, rows, name="s.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return str(path)


def _transcript(tmp_path, sid="authsess-0000"):
    rows = [
        {"type": "user", "sessionId": sid, "uuid": "u1",
         "message": {"content":
                     "Do not merge the parked branch. Fix cf2753c first."}},
        {"type": "assistant", "sessionId": sid, "uuid": "u2",
         "message": {"content": [
             {"type": "text", "text":
              "Decision: use exponential backoff because the cap is "
              "40 req/min."}]}},
        {"type": "user", "sessionId": sid, "uuid": "u3",
         "message": {"content": [
             {"type": "tool_result", "is_error": True,
              "content": "FileNotFoundError: config.yaml missing"}]}},
    ]
    return _write(tmp_path, rows)


def _facts_by_kind(parsed):
    out = {}
    for e in parsed.corpus.entities:
        fields = {f.key: f.value for f in e.fields}
        if "FACT-ID" in fields:
            kind = e.name.split("-")[0]
            out.setdefault(kind, []).append(fields)
    return out


# ── source-role stamping at parse ──

def test_user_constraint_is_user_role_agent_decision_is_assistant_role(
        tmp_path):
    facts = _facts_by_kind(parse_transcript(_transcript(tmp_path)))
    constraint = facts["CONSTRAINT"][0]
    assert constraint["SOURCE-ROLE"] == "user"
    decision = facts["DECISION"][0]
    assert decision["SOURCE-ROLE"] == "assistant"
    # the load-bearing distinction: the decision IS marker_stated and
    # STILL not user authority — basis never implies who wrote it
    assert decision["BASIS"] == "marker_stated"
    assert derive_authority(
        decision["SOURCE-ROLE"]) is Authority.AGENT_CANDIDATE
    assert derive_authority(
        constraint["SOURCE-ROLE"]) is Authority.USER_STATED


def test_tool_error_is_tool_role(tmp_path):
    facts = _facts_by_kind(parse_transcript(_transcript(tmp_path)))
    err = facts["ERROR"][0]
    assert err["SOURCE-ROLE"] == "tool"
    assert derive_authority(err["SOURCE-ROLE"]) is Authority.TOOL_OBSERVED


def test_extractor_version_bumped_for_the_provenance_change(tmp_path):
    facts = _facts_by_kind(parse_transcript(_transcript(tmp_path)))
    assert facts["DECISION"][0]["EXTRACTOR"] == "tp/1.2"


# ── authority axes (PF-11 v2.1: no ordering, no user_ratified) ──

def test_legacy_fact_without_role_is_legacy_unknown_never_approved():
    assert derive_authority("") is Authority.LEGACY_UNKNOWN
    assert derive_authority(None) is Authority.LEGACY_UNKNOWN
    assert derive_authority("unknown") is Authority.LEGACY_UNKNOWN


def test_tc4_no_path_yields_user_ratified():
    """TC-4: the local CLI is not a human — user_ratified does not
    exist as an authority value, and ratification is a separate axis
    that derive_authority cannot even express."""
    assert not hasattr(Authority, "USER_RATIFIED")
    assert "user_ratified" not in {a.value for a in Authority}
    import inspect
    assert "ratified" not in inspect.signature(derive_authority).parameters


def test_tc5_axes_are_separate_and_owner_approval_is_unavailable():
    """TC-5: no total ordering — provenance, local intent marker and
    owner approval are separate fields; owner approval is always
    unavailable in v1 regardless of every other axis."""
    from ctxpack.core.factid import (
        LOCAL_RATIFIED,
        OWNER_APPROVAL_UNAVAILABLE,
    )
    assert LOCAL_RATIFIED == "local_ratified"
    assert OWNER_APPROVAL_UNAVAILABLE == "unavailable"
    # LOCAL_RATIFIED is not an Authority member: it cannot outrank or
    # even compare with provenance values
    assert LOCAL_RATIFIED not in {a.value for a in Authority}


# ── ratification events ──

def test_ratification_roundtrip_and_last_event_wins(tmp_path):
    ledger = str(tmp_path / "ctx")
    fid = "a" * 16
    record_ratification(ledger, fid)
    assert ratification_state(ledger) == {fid: RATIFY}
    assert is_ratified(ledger, fid)
    record_ratification(ledger, fid, action=REJECT, note="wrong value")
    assert ratification_state(ledger) == {fid: REJECT}
    assert not is_ratified(ledger, fid)
    # append-only: both events remain in the journal
    lines = (tmp_path / "ctx" / RATIFICATION_LOG).read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_malformed_fact_id_is_refused_not_recorded(tmp_path):
    ledger = str(tmp_path / "ctx")
    for bad in ("", "zz", "not-a-fact-id", "A" * 15, "g" * 16):
        try:
            record_ratification(ledger, bad)
            raise AssertionError(f"accepted {bad!r}")
        except ValueError:
            pass
    assert ratification_state(ledger) == {}


def test_malformed_journal_rows_confer_nothing_and_degrade(tmp_path):
    """TC-7: unknown schema, short ids and unknown actions are
    malformed; any malformed row degrades the whole journal."""
    from ctxpack.agent.ratification import read_ratifications
    ledger = tmp_path / "ctx"
    ledger.mkdir()
    (ledger / RATIFICATION_LOG).write_text(
        "{broken\n"
        + json.dumps({"fact_id": "short", "action": "ratify"}) + "\n"
        + json.dumps({"fact_id": "b" * 16, "action": "bless"}) + "\n",
        encoding="utf-8")
    journal = read_ratifications(str(ledger))
    assert journal["state"] == {}
    assert journal["degraded"] is True
    assert journal["malformed_rows"] == 3
    assert ratification_state(str(ledger)) == {}


def test_tc6_truncated_rejection_degrades_instead_of_failing_open(
        tmp_path):
    """TC-6: ratify F, then a truncated reject row — F must NOT read
    as ratified, because the reader cannot know what the lost row
    said."""
    from ctxpack.agent.ratification import read_ratifications
    ledger = str(tmp_path / "ctx")
    fid = "c" * 16
    record_ratification(ledger, fid)
    assert is_ratified(ledger, fid)
    with open(tmp_path / "ctx" / RATIFICATION_LOG, "a",
              encoding="utf-8") as f:
        f.write('{"ts": "2026-08-09", "schema": "ctx-ratifications/v1", '
                '"fact_id": "' + fid + '", "action": "rej')  # truncated
    journal = read_ratifications(ledger)
    assert journal["degraded"] is True
    assert journal["malformed_rows"] >= 1
    assert not is_ratified(ledger, fid)


def test_tc20_recovery_is_quarantine_rotation_not_appending(
        tmp_path, capsys):
    """TC-20: appending a valid row to a corrupted journal restores
    nothing; quarantine rotation + a fresh event does, the quarantined
    file is byte-identical, and the reader reports the count."""
    from ctxpack.agent.checkpoint import run_checkpoint
    from ctxpack.agent.ratification import read_ratifications
    from ctxpack.agent.session_reader import session_why_across

    out = tmp_path / "ctx"
    run_checkpoint(_transcript(tmp_path), str(out), as_of="2026-08-09")
    why = session_why_across(str(out), "exponential backoff")
    fid = next(f["value"] for f in why["matches"][0]["fields"]
               if f["key"] == "FACT-ID")
    assert main(["session", "ratify", fid, "--ledger", str(out)]) == 0
    capsys.readouterr()
    log = out / RATIFICATION_LOG
    with open(log, "a", encoding="utf-8") as f:
        f.write("{truncated garbage\n")
    corrupted_bytes = log.read_bytes()

    # appending a valid event to the corrupted journal restores nothing
    record_ratification(str(out), fid)
    assert not is_ratified(str(out), fid)
    # the CLI refuses to append onto a degraded journal
    assert main(["session", "ratify", fid, "--ledger", str(out)]) == 1
    assert "--rotate-quarantine" in capsys.readouterr().err
    # why surfaces the degradation per fact and at the top level
    why = session_why_across(str(out), "exponential backoff")
    assert why["matches"][0]["local_ratification"] == "degraded"
    assert why["ratification_journal"]["degraded"] is True

    # recovery: rotate + fresh event in a new epoch
    assert main(["session", "ratify", fid, "--rotate-quarantine",
                 "--ledger", str(out)]) == 0
    capsys.readouterr()
    journal = read_ratifications(str(out))
    assert journal["degraded"] is False
    assert journal["quarantined"] == 1
    assert is_ratified(str(out), fid)
    quarantine = out / (RATIFICATION_LOG + ".quarantine-1")
    assert quarantine.read_bytes()[:len(corrupted_bytes)] \
        == corrupted_bytes  # preserved verbatim (plus the append probe)
    # rotating a healthy journal is refused
    assert main(["session", "ratify", fid, "--rotate-quarantine",
                 "--ledger", str(out)]) == 1
    assert "healthy" in capsys.readouterr().err


# ── CLI: explicit event referencing an EXISTING fact ──

def test_cli_ratify_unknown_fact_id_refuses(tmp_path, capsys):
    from ctxpack.agent.checkpoint import run_checkpoint
    out = tmp_path / "ctx"
    run_checkpoint(_transcript(tmp_path), str(out), as_of="2026-08-07")
    rc = main(["session", "ratify", "f" * 16, "--ledger", str(out)])
    assert rc == 1
    assert "must reference an existing fact" in capsys.readouterr().err
    assert ratification_state(str(out)) == {}


def test_cli_ratify_marks_the_axis_without_touching_provenance(
        tmp_path, capsys):
    """A ratification event moves ONLY the local-intent axis: the
    provenance axis stays agent_candidate and owner approval stays
    unavailable — no promotion anywhere (TC-4/TC-5)."""
    from ctxpack.agent.checkpoint import run_checkpoint
    from ctxpack.agent.session_reader import session_why_across

    out = tmp_path / "ctx"
    run_checkpoint(_transcript(tmp_path), str(out), as_of="2026-08-07")
    why = session_why_across(str(out), "exponential backoff")
    match = why["matches"][0]
    assert match["authority"] == "agent_candidate"
    assert match["owner_approval"] == "unavailable"
    assert "local_ratification" not in match
    fid = next(f["value"] for f in match["fields"]
               if f["key"] == "FACT-ID")

    assert main(["session", "ratify", fid, "--ledger", str(out)]) == 0
    capsys.readouterr()
    why = session_why_across(str(out), "exponential backoff")
    match = why["matches"][0]
    assert match["authority"] == "agent_candidate"      # unchanged
    assert match["local_ratification"] == "ratified"
    assert match["owner_approval"] == "unavailable"     # never satisfied

    assert main(["session", "ratify", fid, "--reject", "--ledger",
                 str(out), "--note", "superseded by review"]) == 0
    why = session_why_across(str(out), "exponential backoff")
    match = why["matches"][0]
    assert match["authority"] == "agent_candidate"
    assert match["local_ratification"] == "rejected"


def test_why_reports_user_stated_for_user_constraints(tmp_path):
    from ctxpack.agent.checkpoint import run_checkpoint
    from ctxpack.agent.session_reader import session_why_across

    out = tmp_path / "ctx"
    run_checkpoint(_transcript(tmp_path), str(out), as_of="2026-08-07")
    why = session_why_across(str(out), "parked branch")
    roles = {m["authority"] for m in why["matches"]
             if m["kind"] == "CONSTRAINT"}
    assert roles == {"user_stated"}
