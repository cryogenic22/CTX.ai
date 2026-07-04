"""ctx-incident: convention — extraction, fail-open grammar, telemetry.

The incident loop is the ledger's own feedback channel, so its failure
modes are held to the same bar as the extractors it reports on: no
silent drops (malformed payloads bank with parse_ok=false), no
use-vs-mention confusion, no leakage of incident payloads into the
other extractors.
"""

import json

import pytest

from ctxpack.agent.checkpoint import build_gist
from ctxpack.agent.transcript_parser import (
    _parse_incident_line,
    parse_transcript,
)


def _entry(etype, content, *, ts="2026-07-04T10:00:00Z"):
    return {"type": etype, "sessionId": "abcd1234-session", "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _write(tmp_path, entries):
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries),
                    encoding="utf-8")
    return str(path)


def _incidents(parsed):
    return [e for e in parsed.corpus.entities
            if e.name.startswith("INCIDENT-")]


def _field(entity, key):
    return next((f.value for f in entity.fields if f.key == key), "")


# ------------------------------------------------------------- grammar


def test_full_payload_parses():
    rec = _parse_incident_line(
        'ctx-incident: stale | fact="CACHE-TTL-S current value" | '
        'expected="25" | got="50" | source=ctx | '
        'evidence="session why returned turn 120"')
    assert rec["parse_ok"] and rec["type"] == "stale"
    assert rec["fields"]["fact"] == "CACHE-TTL-S current value"
    assert rec["fields"]["expected"] == "25"
    assert rec["fields"]["got"] == "50"
    assert rec["fields"]["source"] == "ctx"


def test_minimal_payload_is_enough():
    rec = _parse_incident_line('ctx-incident: saved | fact="commit abc123"')
    assert rec["parse_ok"] and rec["type"] == "saved"


def test_fail_open_on_bad_type_and_missing_fact():
    bad_type = _parse_incident_line('ctx-incident: amazing | fact="x"')
    assert bad_type is not None and not bad_type["parse_ok"]
    no_fact = _parse_incident_line("ctx-incident: stale | got=50")
    assert no_fact is not None and not no_fact["parse_ok"]
    freeform = _parse_incident_line("ctx-incident: the gist was wrong about x")
    assert freeform is not None and not freeform["parse_ok"]


def test_non_incident_lines_return_none():
    assert _parse_incident_line("Decision: use backoff.") is None
    # backticked mention of the convention, not a use of it
    assert _parse_incident_line(
        'state `ctx-incident: stale | fact="..."` lines') is None


def test_bullet_and_bold_anchoring():
    rec = _parse_incident_line(
        '- **ctx-incident**: user-corrected | fact="risk rule"')
    assert rec is not None and rec["parse_ok"]


# ---------------------------------------------------------- extraction


def test_transcript_extraction_and_stats(tmp_path):
    path = _write(tmp_path, [
        _entry("user", "Continue the migration work."),
        _entry("assistant", [{"type": "text", "text":
            'Resuming from the ledger.\n'
            'ctx-incident: saved | fact="vendor limit 40 req/min" | '
            'evidence="gist constraints section"\n'
            'ctx-incident: stale | fact="POOL-SIZE" | expected="250" | '
            'got="1000"\n'
            "Decision: raise POOL-SIZE to 250 per the vendor doc."}]),
        _entry("user", 'ctx-incident: user-corrected | '
                       'fact="deploy window rule"'),
    ])
    parsed = parse_transcript(path)
    incidents = _incidents(parsed)
    assert len(incidents) == 3
    assert parsed.stats.incidents == 3
    assert parsed.stats.incident_types == {
        "saved": 1, "stale": 1, "user-corrected": 1}
    stale = next(e for e in incidents if _field(e, "TYPE") == "stale")
    assert _field(stale, "EXPECTED") == "250"
    assert _field(stale, "PARSE-OK") == "true"
    assert _field(stale, "RAW").startswith("ctx-incident: stale")
    # the surrounding Decision: still extracts normally
    assert any(e.name.startswith("DECISION-")
               for e in parsed.corpus.entities)


def test_malformed_payload_still_banked(tmp_path):
    path = _write(tmp_path, [
        _entry("assistant", [{"type": "text", "text":
            "ctx-incident: gist told me the wrong branch name entirely"}]),
    ])
    parsed = parse_transcript(path)
    incidents = _incidents(parsed)
    assert len(incidents) == 1
    assert _field(incidents[0], "PARSE-OK") == "false"
    assert "wrong branch name" in _field(incidents[0], "RAW")
    assert parsed.stats.incident_types == {"unparsed": 1}


def test_payload_does_not_leak_into_other_extractors(tmp_path):
    # constraint-shaped wording and a sha-like value inside the payload
    # must not bank as CONSTRAINT/LITERAL entities
    path = _write(tmp_path, [
        _entry("assistant", [{"type": "text", "text":
            'ctx-incident: wrong | fact="rule: never deploy on fridays" | '
            'got="deadbeef1234"'}]),
    ])
    parsed = parse_transcript(path)
    assert len(_incidents(parsed)) == 1
    assert not any(e.name.startswith("CONSTRAINT-")
                   for e in parsed.corpus.entities)
    assert not any(e.name.startswith("LITERAL-")
                   for e in parsed.corpus.entities)


def test_fenced_examples_do_not_extract(tmp_path):
    path = _write(tmp_path, [
        _entry("assistant", [{"type": "text", "text":
            "The convention looks like this:\n```\n"
            'ctx-incident: stale | fact="example only"\n```\n'
            "Use it when the ledger fails you."}]),
    ])
    parsed = parse_transcript(path)
    assert _incidents(parsed) == []
    assert parse_transcript(path).stats.incidents == 0


def test_pasted_user_content_not_mined(tmp_path):
    pasted = ("Here is a transcript I found:\n" +
              'ctx-incident: saved | fact="quoted"\n' * 200)
    path = _write(tmp_path, [_entry("user", pasted)])
    assert _incidents(parse_transcript(path)) == []


def test_incidents_render_in_gist(tmp_path):
    path = _write(tmp_path, [
        _entry("assistant", [{"type": "text", "text":
            'ctx-incident: stale | fact="POOL-SIZE" | expected="250" | '
            'got="1000"'}]),
    ])
    gist = build_gist(parse_transcript(path))
    assert "Memory incidents (ctx telemetry)" in gist
    assert 'ctx-incident: stale | fact="POOL-SIZE"' in gist


# ----------------------------------------------------------- telemetry


def test_session_stats_merges_incident_types(tmp_path):
    from ctxpack.agent.session_reader import session_stats
    ledger = tmp_path / "ctx"
    ledger.mkdir()
    rows = [
        {"session": "s1", "stats": {"decisions": 2, "incidents": 2,
                                    "incident_types": {"saved": 1,
                                                       "stale": 1}}},
        {"session": "s2", "stats": {"decisions": 1, "incidents": 1,
                                    "incident_types": {"saved": 1}}},
    ]
    (ledger / "checkpoints.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    stats = session_stats(str(ledger))
    assert stats["captured"]["incidents"] == 3
    assert stats["incident_types"] == {"saved": 2, "stale": 1}
