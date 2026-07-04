"""Literals ledger — verbatim-identifier fidelity across compaction folds.

The GIPR trust primitive ctxpack lacked: a summary that says "saved the
table" is useless when you later need its exact id. The parser must capture
every load-bearing IDENTIFIER verbatim (UUID, git sha, PR #, version, path,
URL, domain id, number+unit) with turn provenance, so after a compaction
fold the agent writes correct identifiers FROM the ledger instead of
reconstructing them from a paraphrase.

Deterministic (no LLM), stdlib-only, verbatim (never truncated) — the same
discipline the CONSTRAINT extractor applies to negations.
"""

import json

import pytest

from ctxpack.agent.transcript_parser import parse_transcript


def _entry(etype, content, *, sidechain=False, meta=False,
           ts="2026-07-04T10:00:00Z"):
    return {
        "type": etype,
        "sessionId": "abcd1234-session",
        "timestamp": ts,
        "isSidechain": sidechain,
        "isMeta": meta,
        "message": {"role": etype, "content": content},
    }


def _parse_assistant(tmp_path, text):
    entries = [_entry("assistant", [{"type": "text", "text": text}])]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return parse_transcript(str(path))


def _literals(parsed):
    """(value, kind) pairs for every LITERAL entity."""
    out = []
    for e in parsed.corpus.entities:
        if not e.name.startswith("LITERAL"):
            continue
        value = next((f.value for f in e.fields if f.key == "VALUE"), "")
        kind = next((f.value for f in e.fields if f.key == "KIND"), "")
        out.append((value, kind))
    return out


def _values(parsed):
    return {v for v, _ in _literals(parsed)}


# ── Extraction: the high-value identifier classes ──

def test_extracts_common_identifiers(tmp_path):
    parsed = _parse_assistant(tmp_path,
        "Decision: pin the fix in `services/llm.py:42`. Merged as commit "
        "`b1dda66` in PR #305, bumped to v0.5.0. Ref https://example.com/a/b "
        "for the frequency. Variant rs1800437 and PMID 34210852 confirmed. "
        "Backoff base is 750ms and the gist budget is 2000 BPE. Session "
        "508e5733-56aa-46e7-975b-ed2be637d643 pinned.")
    vals = _values(parsed)
    for expected in (
        "services/llm.py:42", "b1dda66", "#305", "v0.5.0",
        "https://example.com/a/b", "rs1800437", "PMID 34210852",
        "750ms", "2000 BPE", "508e5733-56aa-46e7-975b-ed2be637d643",
    ):
        assert expected in vals, f"missing literal {expected!r} in {sorted(vals)}"


def test_literal_kinds_labelled(tmp_path):
    parsed = _parse_assistant(tmp_path,
        "Session 508e5733-56aa-46e7-975b-ed2be637d643 shipped `abc1234` in PR #7.")
    kinds = {v: k for v, k in _literals(parsed)}
    assert kinds["508e5733-56aa-46e7-975b-ed2be637d643"] == "uuid"
    assert kinds["#7"] == "pr"
    assert kinds["abc1234"] == "git_sha"


def test_literal_value_is_verbatim_not_truncated(tmp_path):
    # A >300-char sentence would truncate a DECISION at 280; a literal's exact
    # bytes must survive regardless of where it sits.
    long_prefix = "We spent a while reasoning about the tradeoffs here " * 8
    parsed = _parse_assistant(tmp_path,
        long_prefix + "and finally pinned session "
        "508e5733-56aa-46e7-975b-ed2be637d643 as canonical.")
    assert "508e5733-56aa-46e7-975b-ed2be637d643" in _values(parsed)


def test_literal_turn_provenance(tmp_path):
    entries = [
        _entry("user", "start"),
        _entry("assistant", [{"type": "text",
                              "text": "Merged `b1dda66`."}]),
    ]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    lit = next(e for e in parsed.corpus.entities if e.name.startswith("LITERAL"))
    assert lit.sources[0].turn == 1
    assert str(lit.sources[0]) == "session:abcd1234#turn1"


def test_literals_deduped_first_wins(tmp_path):
    entries = [
        _entry("assistant", [{"type": "text", "text": "Pinned `b1dda66`."}]),
        _entry("assistant", [{"type": "text", "text": "Still on `b1dda66`."}]),
    ]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    shas = [v for v, k in _literals(parsed) if v == "b1dda66"]
    assert len(shas) == 1, f"literal not deduped: {shas}"


def test_deterministic(tmp_path):
    text = ("Shipped `b1dda66` in PR #305, v0.5.0, "
            "508e5733-56aa-46e7-975b-ed2be637d643, PMID 34210852.")
    a = _parse_assistant(tmp_path, text)
    b = _parse_assistant(tmp_path, text)
    assert [e.name for e in a.corpus.entities] == [e.name for e in b.corpus.entities]


def test_stats_literals_counter(tmp_path):
    parsed = _parse_assistant(tmp_path,
        "Shipped `b1dda66` in PR #305 to v0.5.0.")
    assert parsed.stats.literals == 3


# ── Precision: over-firing is the failure mode the repo guards against ──

def test_english_words_not_extracted_as_sha(tmp_path):
    # cafe/decaf/facade/deadbeef are hex-ish but not identifiers: no backtick,
    # no commit-context word, and pure-letter or too-short.
    parsed = _parse_assistant(tmp_path,
        "The cafe served decaf; the facade was a dead end and we deadbeef "
        "our way through the feed.")
    assert _values(parsed) == set(), f"prose extracted as literals: {_values(parsed)}"


def test_bare_number_without_unit_not_extracted(tmp_path):
    parsed = _parse_assistant(tmp_path,
        "There are 28035 homozygotes and 466 residues in the protein.")
    assert _values(parsed) == set()


def test_markdown_heading_not_a_pr(tmp_path):
    parsed = _parse_assistant(tmp_path,
        "## Section 3 covers the plan. Step 3.2 is done.")
    assert _values(parsed) == set()


def test_ip_address_not_extracted_as_version(tmp_path):
    # A dotted-numeric quad is an IP, not semver — must not be banked.
    parsed = _parse_assistant(tmp_path,
        "The service listens on 192.168.0.1 and the gateway is 10.0.0.138.")
    assert _values(parsed) == set(), f"IP mined as version: {_values(parsed)}"
    # but a real 3-part version still lands
    assert "v0.5.0" in _values(_parse_assistant(tmp_path, "Bumped to v0.5.0."))


def test_pasted_user_material_not_mined(tmp_path):
    # A long pasted user message (logs/articles) full of ids must not flood the
    # ledger — same guard as constraints.
    blob = ("commit deadbee1 in PR #999 version v1.2.3 " * 200)
    entries = [_entry("user", "Here is the log I pulled:\n" + blob)]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    assert _values(parsed) == set(), "pasted material mined for literals"


def test_user_request_line_is_mined(tmp_path):
    # A short user instruction that names an id is load-bearing.
    entries = [_entry("user", "Please re-verify PR #305 before merging.")]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    assert "#305" in _values(parse_transcript(str(path)))


# ── Gist: the literals block survives re-injection ──

def test_gist_carries_literals_block(tmp_path):
    from ctxpack.agent.checkpoint import build_gist
    parsed = _parse_assistant(tmp_path,
        "Pinned session 508e5733-56aa-46e7-975b-ed2be637d643 and shipped "
        "`b1dda66`.")
    gist = build_gist(parsed)
    assert "508e5733-56aa-46e7-975b-ed2be637d643" in gist
    assert "b1dda66" in gist
    assert "identifier" in gist.lower()


def test_gist_literal_cap_is_signalled_not_silent(tmp_path):
    # >cap literals: the gist shows the most-recent slice AND says so — never a
    # silent truncation (the full set stays in the ledger).
    from ctxpack.agent.checkpoint import build_gist, _GIST_LITERAL_CAP
    shas = " ".join(f"`deadb{i:02d}`" for i in range(_GIST_LITERAL_CAP + 5))
    parsed = _parse_assistant(tmp_path, "Touched commits " + shas + ".")
    assert parsed.stats.literals == _GIST_LITERAL_CAP + 5  # no extraction cap
    gist = build_gist(parsed)
    assert f"of {_GIST_LITERAL_CAP + 5}" in gist, "gist truncated literals silently"
    assert "full set in the ledger" in gist


# ── The benchmark axis: identifier fidelity ACROSS A FOLD ──

def test_identifier_fidelity_across_fold(tmp_path):
    """Force a checkpoint (the compaction fold), then confirm every planted
    identifier is recoverable VERBATIM from the ledger read path — GIPR's
    identifier-fidelity-across-folds benchmark axis, in test form."""
    from ctxpack.agent.checkpoint import run_checkpoint
    from ctxpack.agent.session_reader import load_session, session_why

    planted = {
        "508e5733-56aa-46e7-975b-ed2be637d643": "uuid",
        "b1dda66": "git_sha",
        "#305": "pr",
        "v0.5.0": "version",
        "services/llm.py:42": "path",
        "PMID 34210852": "domain_id",
    }
    text = ("Decision: pin session 508e5733-56aa-46e7-975b-ed2be637d643. "
            "Shipped `b1dda66` in PR #305, bumped v0.5.0, fixed "
            "`services/llm.py:42`, cited PMID 34210852.")
    entries = [_entry("assistant", [{"type": "text", "text": text}])]
    tp = tmp_path / "session.jsonl"
    tp.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

    out = tmp_path / "ctx"
    run_checkpoint(str(tp), str(out), as_of="2026-07-04")

    doc, sid = load_session(str(out))
    for value in planted:
        res = session_why(doc, sid, value)
        assert res["count"] >= 1, (
            f"literal {value!r} not recoverable from the ledger after the fold")
