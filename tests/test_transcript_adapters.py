"""Transcript adapters: Codex + generic normalization, fail-loud
format detection, and the hollow-transcript checkpoint guard.

All fixtures are synthetic (fictional user ``dev`` only — the fixture
privacy gate forbids real user data).
"""

import json

import pytest

from ctxpack.agent.checkpoint import HollowTranscriptError, run_checkpoint
from ctxpack.agent.transcript_adapters import (
    GenericJSONLAdapter,
    TranscriptFormatError,
    detect_adapter,
    load_transcript,
)
from ctxpack.agent.transcript_parser import parse_transcript
from ctxpack.cli.main import main

TS = "2026-07-13T10:00:00.000Z"


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return str(path)


# ── Codex rollout fixture (synthetic, fictional user) ───────────────


def _codex_rows():
    return [
        {"timestamp": TS, "type": "session_meta", "payload": {
            "id": "0197aaaa-bbbb-7ccc-8ddd-eeeeffff0001",
            "session_id": "0197aaaa-0000-0000-0000-000000000000",
            "cwd": "C:\\Users\\dev\\proj",
            "originator": "codex-tui", "cli_version": "0.144.1"}},
        {"timestamp": TS, "type": "event_msg", "payload": {
            "type": "task_started", "turn_id": "t1"}},
        {"timestamp": TS, "type": "response_item", "payload": {
            "type": "message", "role": "developer", "content": [
                {"type": "input_text",
                 "text": "<permissions instructions>\nsandbox rules"}]}},
        {"timestamp": TS, "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [
                {"type": "input_text",
                 "text": "<user_instructions>\nAGENTS-file boilerplate"}]}},
        {"timestamp": TS, "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [
                {"type": "input_text",
                 "text": "Fix the flaky retry test. "
                         "Do not touch the vendor client."}]}},
        {"timestamp": TS, "type": "response_item", "payload": {
            "type": "reasoning", "id": "rs_1", "summary": [],
            "encrypted_content": "gAAAAopaque"}},
        {"timestamp": TS, "type": "response_item", "payload": {
            "type": "function_call", "name": "exec", "call_id": "c1",
            "arguments": "{\"command\": \"pytest -q\"}"}},
        {"timestamp": TS, "type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "c1",
            "output": [{"type": "input_text", "text": "1 failed"}]}},
        # event_msg agent_message DUPLICATES the response_item stream —
        # consuming both would double-bank every final message
        {"timestamp": TS, "type": "event_msg", "payload": {
            "type": "agent_message",
            "message": "Decision: EVENT-DUPLICATE must not bank."}},
        {"timestamp": TS, "type": "response_item", "payload": {
            "type": "message", "role": "assistant", "content": [
                {"type": "output_text",
                 "text": "Decision: pin the retry base to 750ms because "
                         "the vendor limit is 40 req/min.\n"
                         "Fixed in commit abc1234def56."}]}},
        {"timestamp": TS, "type": "event_msg", "payload": {
            "type": "token_count", "info": {}}},
    ]


def _entity_values(parsed):
    return [f.value for e in parsed.corpus.entities for f in e.fields]


def test_codex_rollout_parses_end_to_end(tmp_path):
    path = _write_jsonl(tmp_path / "rollout.jsonl", _codex_rows())
    parsed = parse_transcript(path)
    assert parsed.adapter == "codex"
    # session id comes from session_meta payload.id (THIS rollout),
    # not the parent thread id
    assert parsed.session_id.startswith("0197aaaa-bbbb")
    assert parsed.stats.cwd == "C:\\Users\\dev\\proj"
    values = " | ".join(_entity_values(parsed))
    assert "Fix the flaky retry test" in values          # USER-REQUEST
    assert "Do not touch the vendor client." in values   # CONSTRAINT
    assert "pin the retry base to 750ms" in values       # DECISION (marker)
    assert "abc1234def56" in values                      # LITERAL (sha)
    assert parsed.stats.decisions == 1


def test_codex_envelopes_and_event_msgs_never_bank(tmp_path):
    path = _write_jsonl(tmp_path / "rollout.jsonl", _codex_rows())
    values = " | ".join(_entity_values(parse_transcript(path)))
    assert "AGENTS-file boilerplate" not in values   # user envelope
    assert "sandbox rules" not in values             # developer role
    assert "EVENT-DUPLICATE" not in values           # event_msg duplicate
    assert "gAAAAopaque" not in values               # encrypted reasoning


def test_codex_tool_calls_map_to_canonical_blocks(tmp_path):
    path = _write_jsonl(tmp_path / "rollout.jsonl", _codex_rows())
    normalized = load_transcript(path)
    kinds = [blk["type"] for e in normalized.entries
             for blk in e["message"]["content"]]
    assert "tool_use" in kinds and "tool_result" in kinds
    tool = next(blk for e in normalized.entries
                for blk in e["message"]["content"]
                if blk["type"] == "tool_use")
    assert tool["name"] == "exec"
    assert tool["input"] == {"command": "pytest -q"}


# ── Generic spec-driven adapter (the no-hardcoding path) ────────────


def _acme_spec(tmp_path):
    spec = {"name": "acme-agent", "role_path": "msg.who",
            "user_values": ["human"], "assistant_values": ["bot"],
            "text_path": "msg.body", "session_id_path": "sid",
            "timestamp_path": "at"}
    p = tmp_path / "acme-spec.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    return str(p)


def test_generic_adapter_maps_any_jsonl(tmp_path):
    rows = [
        {"sid": "s-12345", "at": TS, "msg": {
            "who": "human",
            "body": "Please fix the parser. Never delete the goldens."}},
        {"sid": "s-12345", "at": TS, "msg": {
            "who": "bot",
            "body": "Decision: split the lexer because lookahead "
                    "is ambiguous."}},
        {"sid": "s-12345", "at": TS, "msg": {"who": "system",
                                             "body": "ignored"}},
    ]
    path = _write_jsonl(tmp_path / "acme.jsonl", rows)
    parsed = parse_transcript(path, format_spec=_acme_spec(tmp_path))
    assert parsed.adapter == "acme-agent"
    assert parsed.session_id == "s-12345"
    values = " | ".join(_entity_values(parsed))
    assert "Never delete the goldens." in values
    assert "split the lexer" in values
    assert "ignored" not in values


def test_generic_spec_missing_keys_fails_loud():
    with pytest.raises(TranscriptFormatError, match="missing required"):
        GenericJSONLAdapter({"name": "broken", "role_path": "role"})


def test_generic_spec_unreadable_file_fails_loud(tmp_path):
    rows = [{"role": "user", "content": "hi"}] * 3
    path = _write_jsonl(tmp_path / "x.jsonl", rows)
    with pytest.raises(TranscriptFormatError, match="format spec"):
        parse_transcript(path, format_spec=str(tmp_path / "missing.json"))


# ── Detection: fail-loud, never guess ───────────────────────────────


def test_detection_picks_codex_and_claude_code(tmp_path):
    codex = _write_jsonl(tmp_path / "c.jsonl", _codex_rows())
    assert load_transcript(codex).adapter == "codex"
    cc_rows = [{"type": "user", "sessionId": "abc123", "uuid": "u1",
                "message": {"content": "hello"}}] * 3
    cc = _write_jsonl(tmp_path / "cc.jsonl", cc_rows)
    assert load_transcript(cc).adapter == "claude-code"


def test_unrecognized_format_fails_loud(tmp_path):
    rows = [{"foo": i, "bar": "baz"} for i in range(25)]
    path = _write_jsonl(tmp_path / "foreign.jsonl", rows)
    with pytest.raises(TranscriptFormatError, match="unrecognized"):
        parse_transcript(path)


def test_empty_file_keeps_historical_empty_parse(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    parsed = parse_transcript(str(path))
    assert parsed.last_turn == 0 and parsed.raw_lines == 0


def test_detect_adapter_direct():
    assert detect_adapter(_codex_rows()).name == "codex"
    with pytest.raises(TranscriptFormatError):
        detect_adapter([{"foo": 1}])


# ── Hollow-transcript guard (never shadow a good gist) ──────────────


def _telemetry_only_rollout(tmp_path):
    """Valid Codex format, but nothing normalizable: the exact hollow
    case — detection succeeds, extraction would bank nothing."""
    rows = [{"timestamp": TS, "type": "event_msg",
             "payload": {"type": "token_count", "info": {}}}] * 25
    return _write_jsonl(tmp_path / "telemetry.jsonl", rows)


def test_hollow_transcript_refuses_checkpoint(tmp_path):
    path = _telemetry_only_rollout(tmp_path)
    out = tmp_path / "ctx"
    with pytest.raises(HollowTranscriptError, match="refusing"):
        run_checkpoint(path, str(out), as_of="2026-07-13")
    assert not out.exists()   # nothing written, not even the dir's ledger


def test_hollow_checkpoint_preserves_previous_gist(tmp_path):
    # a good checkpoint first ...
    good = [{"type": "user", "sessionId": "sess-good", "uuid": "u1",
             "message": {"content":
                         "Ship the fix. Do not bump the major version."}}]
    good_path = _write_jsonl(tmp_path / "good.jsonl", good)
    out = tmp_path / "ctx"
    run_checkpoint(good_path, str(out), as_of="2026-07-13")
    gist = (out / "latest-gist.md").read_bytes()
    # ... then a hollow one must leave it byte-identical
    with pytest.raises(HollowTranscriptError):
        run_checkpoint(_telemetry_only_rollout(tmp_path), str(out),
                       as_of="2026-07-13")
    assert (out / "latest-gist.md").read_bytes() == gist


def test_cli_checkpoint_fails_loud_on_foreign_transcript(tmp_path, capsys):
    rows = [{"foo": i} for i in range(25)]
    path = _write_jsonl(tmp_path / "foreign.jsonl", rows)
    rc = main(["checkpoint", "--transcript", path,
               "--out", str(tmp_path / "ctx")])
    assert rc == 1
    assert "unrecognized transcript format" in capsys.readouterr().err
    assert not (tmp_path / "ctx").exists()


def test_hook_mode_stays_fail_open_on_hollow(tmp_path, monkeypatch, capsys):
    import io
    path = _telemetry_only_rollout(tmp_path)
    payload = json.dumps({"transcript_path": path,
                          "cwd": str(tmp_path)})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    rc = main(["hook", "pre-compact", "--out", str(tmp_path / "ctx")])
    assert rc == 0                                   # session unaffected
    assert "checkpoint failed" in capsys.readouterr().err
    assert not (tmp_path / "ctx").exists()           # nothing written


def test_small_or_empty_transcripts_still_checkpoint(tmp_path):
    # under the raw-line threshold the historical behavior stands:
    # a genuinely short session writes its (small) ledger
    rows = [{"type": "user", "sessionId": "sess-tiny", "uuid": "u1",
             "message": {"content": "Rename the flag to --strict."}}]
    path = _write_jsonl(tmp_path / "tiny.jsonl", rows)
    result = run_checkpoint(path, str(tmp_path / "ctx"), as_of="2026-07-13")
    assert result.turns == 1
