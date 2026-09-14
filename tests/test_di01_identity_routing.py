"""DI-01 FUNCTIONAL identity routing — parser -> checkpoint -> stored -> recall.

End-to-end tests (distinct from the helper tests in test_exact_identity.py).
Rewritten per Codex early-review DI-R1/DI-R2: expected values are pinned
INDEPENDENTLY; recall is verified by inspecting `matches[*].fields`
(VALUE/FACT-ID pairs), never a serialized blob that echoes the query; a
negative control proves a wrong query fails; literal-exact recovery is checked
across sessions with a one-result cap; byte-determinism uses read_bytes().

AC1 (case/punctuation-distinct literals survive with original values), AC2
(deterministic). Legacy lookup + one-to-many ambiguity (AC3) is a separate
module. New-behavior functional tests: on the parent the routing did not exist,
so case-distinct literals collapsed to one entity (the defect being fixed).
"""
import glob
import json
import re

from ctxpack.agent import session_reader
from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.session_reader import load_session, session_why
from ctxpack.agent.transcript_parser import parse_transcript
from ctxpack.core import factid

_FID64 = re.compile(r"^[0-9a-f]{64}$")

# Independently pinned expected values (NOT derived from the parser under test).
CASE_A, CASE_B = "src/Foo/Bar.py", "src/foo/bar.py"          # legacy collapses
PUNCT_A, PUNCT_B = "https://example.com/a.b", "https://example.com/a-b"
# expected exact ids: _add_literals bank fact=("LITERAL", subtype, value)
EXP = {
    CASE_A: factid.exact_fact_id("LITERAL", CASE_A, key="path"),
    CASE_B: factid.exact_fact_id("LITERAL", CASE_B, key="path"),
    PUNCT_A: factid.exact_fact_id("LITERAL", PUNCT_A, key="url"),
    PUNCT_B: factid.exact_fact_id("LITERAL", PUNCT_B, key="url"),
}


def _entry(etype, content, sid, ts="2026-07-05T09:00:00Z"):
    return {"type": etype, "sessionId": sid, "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _write(tmp_path, entries, name):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return str(p)


def _transcript(tmp_path, sid, values, name=None):
    body = " and ".join(values)
    return _write(tmp_path, [
        _entry("user", f"Please look at {body}.", sid),
        _entry("assistant", [{"type": "text", "text": f"Noted {body}."}], sid),
    ], name or f"{sid}.jsonl")


def _field(e, key):
    return next((f.value for f in e.fields if f.key == key), "")


def _literal_ids(parsed):
    """{original VALUE -> FACT-ID} for every banked LITERAL entity."""
    return {_field(e, "VALUE"): _field(e, "FACT-ID")
            for e in parsed.corpus.entities if e.name.startswith("LITERAL-")}


def _recovered_pairs(res):
    """(VALUE, FACT-ID, matched_on) read from matches[*].fields — never from
    the top-level echoed key or a serialized blob."""
    out = []
    for m in res.get("matches", []):
        f = {c["key"]: c["value"] for c in m.get("fields", [])}
        if "VALUE" in f:
            out.append((f["VALUE"], f.get("FACT-ID"), m.get("matched_on")))
    return out


# ---- AC1: distinct facts, verbatim, at the parser -----------------------

def test_ac1_case_distinct_literals_distinct_and_verbatim(tmp_path):
    ids = _literal_ids(parse_transcript(_transcript(tmp_path, "casesess", [CASE_A, CASE_B])))
    assert CASE_A in ids and CASE_B in ids, ids            # both verbatim
    assert ids[CASE_A] != ids[CASE_B], "case-distinct ids collapsed"
    assert ids[CASE_A] == EXP[CASE_A] and ids[CASE_B] == EXP[CASE_B]
    assert _FID64.match(ids[CASE_A]) and _FID64.match(ids[CASE_B])


def test_ac1_punctuation_distinct_literals_distinct_and_verbatim(tmp_path):
    ids = _literal_ids(parse_transcript(_transcript(tmp_path, "punctsess", [PUNCT_A, PUNCT_B])))
    assert PUNCT_A in ids and PUNCT_B in ids, ids
    assert ids[PUNCT_A] != ids[PUNCT_B], "punctuation-distinct ids collapsed"
    assert ids[PUNCT_A] == EXP[PUNCT_A] and ids[PUNCT_B] == EXP[PUNCT_B]


# ---- AC1: survive checkpoint -> stored records --------------------------

def test_ac1_survive_checkpoint_to_stored_records(tmp_path):
    t = _transcript(tmp_path, "storesess", [CASE_A, CASE_B])
    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(t, str(out), as_of="2026-07-05")
    raw = open(glob.glob(str(out / "session-*.ctx"))[0], "rb").read().decode("utf-8")
    for val in (CASE_A, CASE_B):
        assert val in raw, f"original value {val!r} not persisted"
        assert EXP[val] in raw, f"exact id for {val!r} not persisted"


# ---- AC1: recover through the real read path (fields, not blob) ---------

def test_ac1_recall_why_recovers_exact_spelling_via_fields(tmp_path):
    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(_transcript(tmp_path, "recallsess", [CASE_A, CASE_B]),
                   str(out), as_of="2026-07-05")
    res = session_reader.session_why_across(ledger_dir=str(out), key=CASE_A)
    pairs = _recovered_pairs(res)
    # the exact spelling is recovered, paired with its 64-hex exact id...
    assert any(v == CASE_A and fid == EXP[CASE_A] and mo == "value_exact"
               for v, fid, mo in pairs), pairs
    # ...and the case variant is NOT returned as the exact match
    assert not any(v == CASE_B and mo == "value_exact" for v, fid, mo in pairs), pairs


def test_ac1_recall_negative_control_wrong_query_recovers_nothing(tmp_path):
    # DI-R1(c): a value that was never banked must NOT be "recovered" just
    # because the response echoes the query key.
    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(_transcript(tmp_path, "negsess", [CASE_A]),
                   str(out), as_of="2026-07-05")
    missing = "src/Totally/Absent/Nope.py"
    res = session_reader.session_why_across(ledger_dir=str(out), key=missing)
    # even if the serialized response echoes `missing`, no returned VALUE is it
    assert missing not in {v for v, _f, _m in _recovered_pairs(res)}, res
    assert not res.get("found", False), res


# ---- DI-R2(a): literal-exact beats recency under a one-result cap -------

def _two_session_ledger(tmp_path, older_val, newer_val, tag):
    out = tmp_path / f"ctx_{tag}"
    out.mkdir()
    # checkpoint order = journal order; the first is the OLDER session
    run_checkpoint(_transcript(tmp_path, f"old{tag}", [older_val], f"old{tag}.jsonl"),
                   str(out), as_of="2026-07-04")
    run_checkpoint(_transcript(tmp_path, f"new{tag}", [newer_val], f"new{tag}.jsonl"),
                   str(out), as_of="2026-07-06")
    return str(out)


def test_dir2_older_exact_spelling_wins_over_newer_variant_one_cap(tmp_path):
    # older session has CASE_A, newer has the case variant CASE_B
    ledger = _two_session_ledger(tmp_path, CASE_A, CASE_B, "fwd")
    res = session_reader.session_why_across(ledger_dir=ledger, key=CASE_A, max_matches=1)
    pairs = _recovered_pairs(res)
    assert pairs and pairs[0][0] == CASE_A and pairs[0][1] == EXP[CASE_A], pairs
    assert pairs[0][2] == "value_exact", pairs


def test_dir2_reversed_control(tmp_path):
    # reverse spellings/order: older has CASE_B, newer has CASE_A; query CASE_B
    ledger = _two_session_ledger(tmp_path, CASE_B, CASE_A, "rev")
    res = session_reader.session_why_across(ledger_dir=ledger, key=CASE_B, max_matches=1)
    pairs = _recovered_pairs(res)
    assert pairs and pairs[0][0] == CASE_B and pairs[0][1] == EXP[CASE_B], pairs
    assert pairs[0][2] == "value_exact", pairs


def test_scoped_why_agrees_on_exact_value(tmp_path):
    # DI-R2(c): scoped (single-session) why also recovers the exact spelling
    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(_transcript(tmp_path, "scopesess", [CASE_A, CASE_B]),
                   str(out), as_of="2026-07-05")
    doc, sid = load_session(str(out), "scopeses")
    res = session_why(doc, sid, CASE_A, ledger_dir=str(out))
    pairs = _recovered_pairs(res)
    assert any(v == CASE_A and fid == EXP[CASE_A] and mo == "value_exact"
               for v, fid, mo in pairs), pairs


# ---- AC2: determinism ---------------------------------------------------

def test_ac2_ids_and_ctx_bytes_deterministic(tmp_path):
    t = _transcript(tmp_path, "detsess", [CASE_A, CASE_B])
    ids1 = _literal_ids(parse_transcript(t))
    ids2 = _literal_ids(parse_transcript(t))
    assert ids1 == ids2 and ids1, "literal ids not deterministic"
    o1, o2 = tmp_path / "c1", tmp_path / "c2"
    o1.mkdir()
    o2.mkdir()
    run_checkpoint(t, str(o1), as_of="2026-07-05")
    run_checkpoint(t, str(o2), as_of="2026-07-05")
    # DI-R1(e): compare raw bytes; text mode would normalize newlines
    b1 = open(glob.glob(str(o1 / "session-*.ctx"))[0], "rb").read()
    b2 = open(glob.glob(str(o2 / "session-*.ctx"))[0], "rb").read()
    assert b1 == b2, "checkpoint .ctx bytes not deterministic"
