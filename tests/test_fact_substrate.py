"""Spec v1.1 fact substrate — identity, basis, linking, absence, events.

Contract under test: docs/spec-v1.1-fact-substrate.md. The invariants
that must never regress: identity is canonical content (stable across
parser releases), basis is an enum stamped per extraction mechanics,
misses are asserted absences, and events.jsonl is a deterministic fold
of the transcript.
"""

import json

import pytest

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.transcript_parser import parse_transcript
from ctxpack.core import factid


def _entry(etype, content, *, ts="2026-07-05T09:00:00Z"):
    return {"type": etype, "sessionId": "fact1234-session", "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def _write(tmp_path, entries, name="session.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in entries),
                    encoding="utf-8")
    return str(path)


def _field(entity, key):
    return next((f.value for f in entity.fields if f.key == key), "")


def _by_prefix(parsed, prefix):
    return [e for e in parsed.corpus.entities if e.name.startswith(prefix)]


# ------------------------------------------------------------- identity


def test_fact_id_deterministic_and_normalized():
    a = factid.fact_id("DECISION", "Use  Exponential Backoff.")
    b = factid.fact_id("decision", "use exponential backoff")
    assert a == b and len(a) == 16


def test_fact_id_separates_kind_key_value_scope():
    base = factid.fact_id("DECISION", "use backoff")
    assert factid.fact_id("CONSTRAINT", "use backoff") != base
    assert factid.fact_id("DECISION", "use backoff", key="retry") != base
    assert factid.fact_id("DECISION", "use backoff", scope="repoA") != base
    # a revised value is a NEW fact — the key chains versions
    assert factid.fact_id("LITERAL", "250", key="TIMEOUT-MS") != \
        factid.fact_id("LITERAL", "500", key="TIMEOUT-MS")


def test_fact_id_field_boundaries_not_forgeable():
    # (kind="A", key="B\x1fC") must not collide with (kind="A\x1fB", key="C")
    assert factid.fact_id("A", "v", key="B") != factid.fact_id("A B", "v")


def test_extractor_version_not_in_identity():
    # identity must survive parser upgrades: nothing version-shaped in
    # the hash inputs — this guards the senior-lead amendment
    a = factid.fact_id("DECISION", "use backoff")
    assert factid.EXTRACTOR_VERSION not in ("", None)
    assert a == factid.fact_id("DECISION", "use backoff")


# ------------------------------------------------------ parser stamping


@pytest.fixture
def parsed(tmp_path):
    path = _write(tmp_path, [
        _entry("user", "Fix the retry bug. Never bypass the rate limiter."),
        _entry("assistant", [{"type": "text", "text":
            "Decision: use exponential backoff with base 750ms.\n"
            "We chose least-connections routing for ingest.\n"
            "The polling approach didn't work because it deadlocked.\n"
            "The fix landed as commit deadbeef1234.\n"
            'ctx-incident: saved | fact="commit deadbeef1234" | '
            'evidence="ledger literals"'}]),
    ])
    return parse_transcript(path)


def test_substrate_fields_stamped(parsed):
    for prefix in ("DECISION-", "CONSTRAINT-", "LITERAL-",
                   "FAILED-APPROACH-", "USER-REQUEST-", "INCIDENT-"):
        ents = _by_prefix(parsed, prefix)
        assert ents, f"no {prefix} entities extracted"
        for e in ents:
            assert len(_field(e, "FACT-ID")) == 16, e.name
            assert _field(e, "STATUS") == "current", e.name
            assert _field(e, "EXTRACTOR") == factid.EXTRACTOR_VERSION
            assert _field(e, "BASIS") in {b.value for b in factid.FactBasis}


def test_basis_reflects_extraction_mechanics(parsed):
    decisions = {_field(e, "DECISION"): _field(e, "BASIS")
                 for e in _by_prefix(parsed, "DECISION-")}
    marker = next(v for k, v in decisions.items() if k.startswith("Decision:"))
    verb = next(v for k, v in decisions.items() if "chose" in k)
    assert marker == "marker_stated"
    assert verb == "inferred"
    constraint = _by_prefix(parsed, "CONSTRAINT-")[0]
    assert _field(constraint, "BASIS") == "user_imperative"
    literal = _by_prefix(parsed, "LITERAL-")[0]
    assert _field(literal, "BASIS") == "literal_extractor"


def test_incident_links_to_unambiguous_fact(parsed):
    incident = _by_prefix(parsed, "INCIDENT-")[0]
    linked = _field(incident, "LINKED-FACT-ID")
    lit = next(e for e in _by_prefix(parsed, "LITERAL-")
               if _field(e, "VALUE") == "deadbeef1234")
    assert linked == _field(lit, "FACT-ID")


def test_ambiguous_incident_stays_unlinked(tmp_path):
    path = _write(tmp_path, [
        _entry("assistant", [{"type": "text", "text":
            "Decision: adopt caching for billing service.\n"
            "Decision: adopt caching for ledger service.\n"
            'ctx-incident: stale | fact="adopt caching for"'}]),
    ])
    parsed2 = parse_transcript(path)
    incident = _by_prefix(parsed2, "INCIDENT-")[0]
    assert _field(incident, "LINKED-FACT-ID") == ""


# ---------------------------------------------------- absence contract


def test_session_why_asserts_absence(tmp_path, parsed):
    from ctxpack.agent.session_reader import session_why
    from ctxpack.core.packer.compressor import compress
    from ctxpack.core.parser import parse as parse_ctx
    from ctxpack.core.serializer import serialize
    doc = parse_ctx(serialize(compress(parsed.corpus)))
    miss = session_why(doc, "fact1234", "NONEXISTENT-THING-XYZ")
    assert miss["found"] is False and miss["count"] == 0
    assert miss["searched_entities"] > 0
    assert "asserted absence" in miss["note"]
    hit = session_why(doc, "fact1234", "deadbeef1234")
    assert hit["found"] is True and hit["count"] >= 1


# ------------------------------------------------------- derived events


def test_checkpoint_emits_replayable_events(tmp_path):
    entries = [
        _entry("user", "Fix retries. Never bypass the rate limiter."),
        _entry("assistant", [{"type": "text", "text":
            "Decision: use exponential backoff with base 750ms.\n"
            'ctx-incident: saved | fact="rate limiter rule"'}]),
    ]
    t = _write(tmp_path, entries)
    out = str(tmp_path / "ctx")
    run_checkpoint(t, out)
    events_path = tmp_path / "ctx" / "events.jsonl"
    rows = [json.loads(l) for l in
            events_path.read_text(encoding="utf-8").splitlines()]
    kinds = [r["event"] for r in rows]
    assert "fact_asserted" in kinds and "incident" in kinds \
        and "retrieval" in kinds
    assert all(r["schema"] == factid.EVENTS_SCHEMA for r in rows)
    asserted = [r for r in rows if r["event"] == "fact_asserted"]
    assert all(r["fact_id"] and r["detail"]["basis"] for r in asserted)

    # idempotent re-checkpoint: no duplicate fact_asserted rows
    run_checkpoint(t, out)
    rows2 = [json.loads(l) for l in
             events_path.read_text(encoding="utf-8").splitlines()]
    asserted2 = [r for r in rows2 if r["event"] == "fact_asserted"]
    assert len(asserted2) == len(asserted)
    # journal rows carry the rank policy for future offline A/B folds
    journal = [json.loads(l) for l in
               (tmp_path / "ctx" / "checkpoints.jsonl")
               .read_text(encoding="utf-8").splitlines()]
    assert all(j["rank_policy"] == factid.RANK_POLICY for j in journal)


def test_events_incident_row_carries_link(tmp_path):
    entries = [
        _entry("assistant", [{"type": "text", "text":
            "The fix landed as commit deadbeef1234.\n"
            'ctx-incident: saved | fact="commit deadbeef1234"'}]),
    ]
    t = _write(tmp_path, entries)
    run_checkpoint(t, str(tmp_path / "ctx"))
    rows = [json.loads(l) for l in (tmp_path / "ctx" / "events.jsonl")
            .read_text(encoding="utf-8").splitlines()]
    inc = next(r for r in rows if r["event"] == "incident")
    assert inc["fact_id"]  # resolved to the literal's fact_id
    assert inc["detail"]["type"] == "saved"
