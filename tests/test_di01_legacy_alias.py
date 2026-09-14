"""DI-01 AC3 — rebuildable legacy->exact alias map + one-to-many ambiguity.

Legacy ``fact_id()`` normalizes (lowercases + collapses), so case/punctuation-
distinct literals that DI-01 keeps as DISTINCT 64-hex exact facts share ONE
legacy 16-hex id. AC3: a legacy id stays LOOKUPABLE (resolves to its exact
fact) and a one-to-many legacy id reports EXPLICIT ambiguity computed BEFORE
any result cap — never a guessed successor.

Red-on-parent (a9e8ad2): `why` had no alias resolver, so a legacy id for a
migrated literal returned asserted absence. The DI-R3(d) incident-control test
is a FORWARD GUARD (it already holds on the parent and must keep holding once
aliases exist): `_link_incidents` links only on exactly one candidate, and the
alias map is read-only, so it never invents an incident link.
"""
import json
import re

from ctxpack.agent import session_reader
from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.session_reader import load_session, session_why
from ctxpack.agent.transcript_parser import parse_transcript
from ctxpack.core import factid

CASE_A, CASE_B = "src/Foo/Bar.py", "src/foo/bar.py"          # subtype "path"
# One legacy id (case-folded), two distinct exact ids — the AC3 premise.
LEGACY = factid.fact_id("LITERAL", CASE_A, key="path")
EXP_A = factid.exact_fact_id("LITERAL", CASE_A, key="path")
EXP_B = factid.exact_fact_id("LITERAL", CASE_B, key="path")
_FID16 = re.compile(r"^[0-9a-f]{16}$")


def _entry(etype, content, sid, ts="2026-07-05T09:00:00Z"):
    return {"type": etype, "sessionId": sid, "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _transcript(tmp_path, sid, values, name=None):
    body = " and ".join(values)
    p = tmp_path / (name or f"{sid}.jsonl")
    p.write_text("\n".join(json.dumps(e) for e in [
        _entry("user", f"Please look at {body}.", sid),
        _entry("assistant", [{"type": "text", "text": f"Noted {body}."}], sid),
    ]), encoding="utf-8")
    return str(p)


def _ledger(tmp_path, values, tag="ctx"):
    out = tmp_path / tag
    out.mkdir()
    run_checkpoint(_transcript(tmp_path, f"s{tag}", values, f"s{tag}.jsonl"),
                   str(out), as_of="2026-07-05")
    return str(out)


def _pairs(res):
    """(VALUE, FACT-ID, matched_on) from matches[*].fields — never the blob."""
    out = []
    for m in res.get("matches", []):
        f = {c["key"]: c["value"] for c in m.get("fields", [])}
        if "VALUE" in f:
            out.append((f["VALUE"], f.get("FACT-ID"), m.get("matched_on")))
    return out


# ---- premise the module rests on ---------------------------------------

def test_premise_one_legacy_id_two_distinct_exact_ids():
    assert LEGACY == factid.fact_id("LITERAL", CASE_B, key="path")
    assert _FID16.match(LEGACY)
    assert EXP_A != EXP_B and len(EXP_A) == len(EXP_B) == 64


# ---- AC3: a legacy id stays lookupable (unique) -------------------------

def test_ac3_unique_legacy_id_resolves_to_its_exact_fact(tmp_path):
    ledger = _ledger(tmp_path, [CASE_A], "uniq")           # only one spelling
    res = session_reader.session_why_across(ledger_dir=ledger, key=LEGACY)
    assert res["found"] is True
    assert res.get("matched_via") == "legacy_alias"
    assert res.get("legacy_alias_ambiguous") is not True
    pairs = _pairs(res)
    assert any(v == CASE_A and fid == EXP_A and mo == "legacy_alias"
               for v, fid, mo in pairs), (pairs, res)


# ---- AC3: one-to-many legacy id -> EXPLICIT ambiguity, never a guess ----

def test_ac3_one_to_many_legacy_id_reports_ambiguity(tmp_path):
    ledger = _ledger(tmp_path, [CASE_A, CASE_B], "ambig")   # both spellings
    res = session_reader.session_why_across(ledger_dir=ledger, key=LEGACY)
    assert res.get("legacy_alias_ambiguous") is True, res
    assert res["candidate_count"] == 2, res
    assert res["matches"] == []                       # never a single pick
    got = {c["exact_fact_id"]: c["value"] for c in res["candidates"]}
    assert got == {EXP_A: CASE_A, EXP_B: CASE_B}, got


def test_ac3_ambiguity_survives_a_one_result_cap(tmp_path):
    """The load-bearing reviewer property: a result cap must NOT collapse a
    one-to-many legacy id to one guessed successor. Ambiguity is detected over
    the full literal set, before the cap."""
    ledger = _ledger(tmp_path, [CASE_A, CASE_B], "cap")
    res = session_reader.session_why_across(ledger_dir=ledger, key=LEGACY,
                                            max_matches=1)
    assert res.get("legacy_alias_ambiguous") is True
    assert res["candidate_count"] == 2
    assert {c["exact_fact_id"] for c in res["candidates"]} == {EXP_A, EXP_B}


def test_ac3_ambiguity_is_deterministic_rebuildable(tmp_path):
    ledger = _ledger(tmp_path, [CASE_A, CASE_B], "det")
    r1 = session_reader.session_why_across(ledger_dir=ledger, key=LEGACY)
    r2 = session_reader.session_why_across(ledger_dir=ledger, key=LEGACY)
    assert r1["candidates"] == r2["candidates"]        # stable order + content


# ---- AC3: single-session why resolves aliases too ----------------------

def test_ac3_single_session_why_reports_ambiguity(tmp_path):
    ledger = _ledger(tmp_path, [CASE_A, CASE_B], "scoped")
    doc, sid = load_session(ledger, "sscoped")
    res = session_why(doc, sid, LEGACY, ledger_dir=ledger)
    assert res.get("legacy_alias_ambiguous") is True
    assert res["candidate_count"] == 2


# ---- honesty controls ---------------------------------------------------

def test_ac3_unknown_legacy_id_is_honest_absence_not_alias(tmp_path):
    ledger = _ledger(tmp_path, [CASE_A], "absent")
    res = session_reader.session_why_across(ledger_dir=ledger, key="f" * 16)
    assert res["found"] is False
    assert res.get("legacy_alias_ambiguous") is not True
    assert res.get("matched_via") != "legacy_alias"


def test_ac3_exact_64hex_lookup_is_direct_not_via_alias(tmp_path):
    """A 64-hex exact id resolves directly (value_exact on the FACT-ID field);
    the alias path is only for legacy 16-hex ids and must not shadow it."""
    ledger = _ledger(tmp_path, [CASE_A, CASE_B], "direct")
    res = session_reader.session_why_across(ledger_dir=ledger, key=EXP_A)
    assert res["found"] is True
    assert res.get("matched_via") != "legacy_alias"
    assert any(fid == EXP_A for _v, fid, _m in _pairs(res)), res


def test_ac3_non_hex_query_is_untouched_by_alias(tmp_path):
    """A normal prose query never triggers alias resolution (16-hex-shaped
    only) and never pays the doc-retention cost path incorrectly."""
    ledger = _ledger(tmp_path, [CASE_A], "prose")
    res = session_reader.session_why_across(ledger_dir=ledger, key=CASE_A)
    assert res["found"] is True
    assert res.get("matched_via") != "legacy_alias"


# ---- DI-R3(d): ambiguous incident stays UNLINKED even with aliases ------

def test_dir3d_ambiguous_incident_stays_unlinked(tmp_path):
    """FORWARD GUARD: an incident whose fact= text matches MULTIPLE banked
    facts (two case-distinct literals that normalize alike) stays UNLINKED —
    `_link_incidents` links only on exactly one candidate. The AC3 alias map
    is read-only, so it introduces no retroactive incident link; the SAME
    ambiguity is instead surfaced honestly by the alias resolver."""
    sid = "incidsess"
    entries = [
        _entry("user", f"Please look at {CASE_A} and {CASE_B}.", sid),
        _entry("assistant", [{"type": "text", "text":
            'ctx-incident: stale | fact="src/foo/bar.py" | '
            'expected="x" | got="y" | evidence="z"'}], sid),
    ]
    p = tmp_path / f"{sid}.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

    parsed = parse_transcript(str(p))
    incidents = [e for e in parsed.corpus.entities
                 if e.name.startswith("INCIDENT-")]
    assert incidents, "no incident banked"
    for e in incidents:
        assert not any(f.key == "LINKED-FACT-ID" for f in e.fields), \
            "ambiguous incident gained an invented link"

    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(str(p), str(out), as_of="2026-07-05")
    res = session_reader.session_why_across(ledger_dir=str(out), key=LEGACY,
                                            max_matches=1)
    assert res.get("legacy_alias_ambiguous") is True
    assert res["candidate_count"] == 2
