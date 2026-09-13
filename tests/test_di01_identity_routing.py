"""DI-01 FUNCTIONAL identity routing — parser -> checkpoint -> stored -> recall.

End-to-end tests (distinct from the helper tests in test_exact_identity.py):
- AC1: case/punctuation-distinct literals survive the whole path with their
  ORIGINAL values intact and DISTINCT exact ids.
- AC2: repeated identical input -> stable ids + deterministic output.

Legacy lookup + one-to-many ambiguity (AC3) live in a separate test module.
These are new-behavior functional tests; on the parent commit the routing does
not exist so case-distinct literals collapse to one entity (the defect).
"""
import glob
import json
import re

from ctxpack.agent import session_reader
from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.transcript_parser import parse_transcript

_FID64 = re.compile(r"^[0-9a-f]{64}$")
# case/punctuation-distinct identifiers the literal extractor captures (paths)
_CASE_PAIR = ("src/Foo/Bar.py", "src/foo/bar.py")


def _entry(etype, content, ts="2026-07-05T09:00:00Z"):
    return {"type": etype, "sessionId": "di01test-session", "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _transcript(tmp_path):
    return _write(tmp_path, [
        _entry("user", f"Please edit {_CASE_PAIR[0]} and also {_CASE_PAIR[1]}."),
        _entry("assistant", [{"type": "text", "text":
                f"Edited {_CASE_PAIR[0]}; {_CASE_PAIR[1]} is a different file."}]),
    ])


def _write(tmp_path, entries, name="session.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return str(p)


def _field(e, key):
    return next((f.value for f in e.fields if f.key == key), "")


def _literals(parsed):
    return [e for e in parsed.corpus.entities if e.name.startswith("LITERAL-")]


def _pair_ids(parsed):
    return {_field(e, "VALUE"): _field(e, "FACT-ID")
            for e in _literals(parsed) if _field(e, "VALUE") in _CASE_PAIR}


def test_ac1_case_distinct_literals_are_distinct_facts_verbatim(tmp_path):
    parsed = parse_transcript(_transcript(tmp_path))
    ids = _pair_ids(parsed)
    # both case-distinct originals banked, verbatim
    assert set(ids) == set(_CASE_PAIR), f"missing a variant: {set(ids)}"
    # distinct entities, distinct exact/v1 (64-hex) ids
    assert ids[_CASE_PAIR[0]] != ids[_CASE_PAIR[1]], "case-distinct ids collapsed"
    for fid in ids.values():
        assert _FID64.match(fid), f"expected 64-hex exact id, got {fid!r}"


def test_ac1_survive_checkpoint_to_stored_records(tmp_path):
    t = _transcript(tmp_path)
    ids = _pair_ids(parse_transcript(t))
    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(t, str(out), as_of="2026-07-05")
    ctx = glob.glob(str(out / "session-*.ctx"))
    assert ctx, "no session .ctx written"
    text = open(ctx[0], encoding="utf-8").read()
    for val, fid in ids.items():
        assert val in text, f"original value {val!r} not persisted"
        assert fid in text, f"exact id {fid} for {val!r} not persisted"


def test_ac1_recall_why_recovers_original_value(tmp_path):
    t = _transcript(tmp_path)
    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(t, str(out), as_of="2026-07-05")
    res = session_reader.session_why_across(ledger_dir=str(out), key=_CASE_PAIR[0])
    # the exact original value is recoverable through the read path
    assert _CASE_PAIR[0] in json.dumps(res), res


def test_ac2_ids_and_output_deterministic(tmp_path):
    t = _transcript(tmp_path)
    ids1 = sorted(_pair_ids(parse_transcript(t)).values())
    ids2 = sorted(_pair_ids(parse_transcript(t)).values())
    assert ids1 == ids2 and len(ids1) == 2, "literal exact ids not deterministic"
    o1, o2 = tmp_path / "c1", tmp_path / "c2"
    o1.mkdir()
    o2.mkdir()
    run_checkpoint(t, str(o1), as_of="2026-07-05")
    run_checkpoint(t, str(o2), as_of="2026-07-05")
    b1 = open(glob.glob(str(o1 / "session-*.ctx"))[0], encoding="utf-8").read()
    b2 = open(glob.glob(str(o2 / "session-*.ctx"))[0], encoding="utf-8").read()
    assert b1 == b2, "checkpoint .ctx output not byte-deterministic"
