"""Session-ledger read path (P4) — recall / timeline / decisions / why."""

import json

import pytest

from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.session_reader import (
    LedgerError,
    load_session,
    resolve_session,
    session_decisions,
    session_recall,
    session_timeline,
    session_why,
)
from ctxpack.core.packer.compressor import compress
from ctxpack.core.packer.entity_resolver import resolve_entities
from ctxpack.core.packer.ir import IRCorpus, IREntity, IRField, IRSource
from ctxpack.core.parser import parse
from ctxpack.core.serializer import serialize


def _entry(etype, content, sid, ts="2026-07-03T10:00:00Z"):
    return {
        "type": etype,
        "sessionId": sid,
        "timestamp": ts,
        "isSidechain": False,
        "isMeta": False,
        "message": {"role": etype, "content": content},
    }


def _write_transcript(tmp_path, sid, name="session.jsonl"):
    entries = [
        _entry("user", "Please fix the retry bug. "
                       "Do not touch the auth service while doing this.", sid),
        _entry("assistant", [
            {"type": "text",
             "text": "Decision: use exponential backoff with base 750ms.\n"
                     "The mock-server approach didn't work because ports "
                     "clashed with the fixture."},
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "src/retry.py",
                       "old_string": "a", "new_string": "b"}},
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "pytest -q",
                       "description": "Run test suite"}},
        ], sid),
        _entry("user", [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
             "content": "AssertionError: expected 750, got 250"},
        ], sid),
    ]
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in entries),
                    encoding="utf-8")
    return str(path)


@pytest.fixture
def ledger(tmp_path):
    """A real ledger dir produced by the write path (run_checkpoint)."""
    out = tmp_path / "ctx"
    transcript = _write_transcript(tmp_path, "feedbeef-session")
    run_checkpoint(transcript, str(out), as_of="2026-07-03")
    return str(out)


def test_resolve_explicit_and_latest(ledger, tmp_path):
    sid, path = resolve_session(ledger)
    assert sid == "feedbeef"
    assert path.endswith("session-feedbeef.ctx")

    # A later checkpoint for a different session becomes the new latest
    t2 = _write_transcript(tmp_path, "cafebabe-session", name="s2.jsonl")
    run_checkpoint(t2, ledger, as_of="2026-07-03")
    sid_latest, _ = resolve_session(ledger)
    assert sid_latest == "cafebabe"

    # ...but the first session is still addressable explicitly
    sid_old, _ = resolve_session(ledger, "feedbeef-session")
    assert sid_old == "feedbeef"


def test_resolve_missing_ledger_raises(tmp_path):
    with pytest.raises(LedgerError):
        resolve_session(str(tmp_path / "nowhere"))


def test_recall_index_lists_kinds_and_turns(ledger):
    doc, sid = load_session(ledger)
    result = session_recall(doc, sid)
    assert result["sections_available"] == len(result["index"]) > 0
    kinds = {r["kind"] for r in result["index"]}
    assert {"USER-REQUEST", "CONSTRAINT", "DECISION",
            "FAILED-APPROACH", "ERROR", "FILE"} <= kinds
    assert all(isinstance(r["turn"], int) for r in result["index"])


def test_recall_by_section_returns_prose(ledger):
    doc, sid = load_session(ledger)
    index = session_recall(doc, sid)["index"]
    decision_name = next(r["name"] for r in index if r["kind"] == "DECISION")
    # Both spellings must resolve: with and without the ENTITY- prefix
    for name in (decision_name, decision_name.replace("ENTITY-", "", 1)):
        result = session_recall(doc, sid, section=name)
        assert result["sections_matched"] == 1
        assert "exponential backoff" in result["text"]
        assert result["tokens_injected"] > 0


def test_recall_by_query(ledger):
    doc, sid = load_session(ledger)
    result = session_recall(doc, sid, query="exponential backoff retry")
    assert result["sections_matched"] >= 1
    assert "backoff" in result["text"].lower()


def test_timeline_is_turn_ordered_and_filterable(ledger):
    doc, sid = load_session(ledger)
    full = session_timeline(doc, sid)
    turns = [r["turn"] for r in full["timeline"]]
    assert turns == sorted(turns)
    assert full["events"] == len(full["timeline"])

    only = session_timeline(doc, sid, kinds=["DECISION", "ERROR"])
    assert {r["kind"] for r in only["timeline"]} == {"DECISION", "ERROR"}

    last1 = session_timeline(doc, sid, limit=1)
    assert len(last1["timeline"]) == 1
    assert last1["timeline"][0]["turn"] == turns[-1]
    assert last1["events"] == full["events"]  # total unaffected by limit


def test_decisions_trio(ledger):
    doc, sid = load_session(ledger)
    result = session_decisions(doc, sid)
    assert result["counts"]["decisions"] == 1
    assert result["counts"]["constraints"] == 1
    assert result["counts"]["failed_approaches"] == 1
    assert "exponential backoff" in result["decisions"][0]["text"]
    assert "Do not touch the auth service" in result["constraints"][0]["text"]
    assert result["decisions"][0]["turn"] == 1


def test_why_value_substring(ledger):
    doc, sid = load_session(ledger)
    result = session_why(doc, sid, "exponential backoff")
    assert result["count"] >= 1
    hit = result["matches"][0]
    assert hit["kind"] == "DECISION"
    assert hit["matched_on"] == "value_substring"
    assert hit["turn"] == 1


def test_why_empty_key_is_an_error(ledger):
    doc, sid = load_session(ledger)
    assert session_why(doc, sid, "  ")["error"]


def test_mcp_handlers_json_contract(ledger):
    """The MCP handlers return valid JSON for both happy and error paths."""
    from ctxpack.integrations import mcp_server as srv

    ok = json.loads(srv.handle_session_decisions({"ledger_dir": ledger}))
    assert ok["counts"]["decisions"] == 1

    missing = json.loads(srv.handle_session_recall({"ledger_dir": "nowhere"}))
    assert missing["error"]["code"] == "ledger_not_found"

    why = json.loads(srv.handle_session_why(
        {"ledger_dir": ledger, "key": "exponential backoff"}))
    assert why["count"] >= 1

    graph_text = (
        "§CTX v1.0 L2 DOMAIN:test\n\n"
        "±ENTITY-A\nDEPENDS-ON:@ENTITY-B\n\n"
        "±ENTITY-B\nIDENTIFIER:b\n"
    )
    parents = json.loads(srv.handle_graph_query(
        {"text": graph_text, "entity": "b", "op": "parents"}))
    assert parents["parents"] == ["ENTITY-A"]


def _superseded_doc():
    """A ledger where one key was revised twice — the supersession case
    the dogfood ledger doesn't exercise yet."""
    corpus = IRCorpus(domain="session-supetest")
    for turn, value in [(0, "250"), (2, "500"), (4, "750")]:
        entity = IREntity(
            name="CONFIG-BACKOFF",
            sources=[IRSource(file="session:supetest", turn=turn)],
        )
        entity.fields.append(IRField(
            key="BACKOFF-BASE-MS", value=value, raw_value=value,
            source=IRSource(file="session:supetest", turn=turn),
        ))
        corpus.entities.append(entity)
    resolve_entities(corpus, supersede_by_recency=True)
    return parse(serialize(compress(corpus, as_of="2026-07-03")), level=2)


def test_why_surfaces_supersession_chain():
    doc = _superseded_doc()
    result = session_why(doc, "supetest", "BACKOFF-BASE-MS")
    assert result["count"] == 1
    hit = result["matches"][0]
    assert hit["matched_on"] == "field_key"
    current = next(f["value"] for f in hit["fields"]
                   if f["key"].upper() == "BACKOFF-BASE-MS")
    assert current == "750", "latest value must win"
    assert hit["superseded_chains"], "chain missing from why()"
    chain = hit["superseded_chains"][0]["chain"]
    assert "250" in chain and "500" in chain
    assert result["note"], "supersession note missing"
