"""Transcript parser — deterministic extraction from Claude Code JSONL."""

import json

import pytest

from ctxpack.agent.transcript_parser import parse_transcript


def _entry(etype, content, *, sidechain=False, meta=False, ts="2026-07-03T10:00:00Z"):
    return {
        "type": etype,
        "sessionId": "abcd1234-session",
        "timestamp": ts,
        "isSidechain": sidechain,
        "isMeta": meta,
        "message": {"role": etype, "content": content},
    }


@pytest.fixture
def transcript(tmp_path):
    entries = [
        _entry("user", "Please fix the retry bug. Do not touch the auth service "
                       "while doing this. Always run the tests before finishing."),
        _entry("assistant", [
            {"type": "text",
             "text": "Decision: use exponential backoff with base 750ms. "
                     "The root cause was a stale Redis fixture. "
                     "The mock-server approach didn't work because ports clashed."},
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "src/retry.py", "old_string": "a", "new_string": "b"}},
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "pytest -q", "description": "Run test suite"}},
            {"type": "tool_use", "name": "TodoWrite",
             "input": {"todos": [{"content": "Fix retry bug", "status": "in_progress"}]}},
        ]),
        _entry("user", [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
             "content": "AssertionError: expected 750, got 250"},
        ]),
        # pasted material: imperative sentences must NOT become constraints
        _entry("user", "Look at this article I found. " + (
            "You should not use global variables. Never mix tabs and spaces. "
            "Always write docstrings. " * 40)),
        # sidechain (subagent) chatter must be ignored entirely
        _entry("assistant", [{"type": "text", "text": "Decision: sidechain noise."}],
               sidechain=True),
    ]
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return str(path)


def test_structured_extraction(transcript):
    parsed = parse_transcript(transcript)
    names = {e.name.rsplit("-", 1)[0] if e.name[-1].isdigit() is False else e.name
             for e in parsed.corpus.entities}
    kinds = {e.name.split("-")[0] for e in parsed.corpus.entities}
    assert {"USER", "CONSTRAINT", "DECISION", "FAILED", "ERROR", "TASK",
            "FILE", "TOOL"} <= kinds, f"missing kinds in {kinds}"
    assert parsed.stats.constraints == 2          # do-not-touch + always-run-tests
    assert parsed.stats.decisions >= 2            # Decision: + root cause
    assert parsed.stats.failed_approaches == 1
    assert parsed.stats.errors == 1
    assert parsed.stats.files_changed == 1
    assert parsed.stats.tasks == 1
    assert parsed.session_id == "abcd1234-session"


def test_constraints_keep_negations_verbatim(transcript):
    parsed = parse_transcript(transcript)
    rules = [f.value for e in parsed.corpus.entities
             if e.name.startswith("CONSTRAINT") for f in e.fields
             if f.key == "RULE"]
    joined = " | ".join(rules)
    assert "Do not touch the auth service" in joined
    assert "not" in joined.lower()


def test_pasted_material_not_mined_for_constraints(transcript):
    parsed = parse_transcript(transcript)
    rules = [f.value for e in parsed.corpus.entities
             if e.name.startswith("CONSTRAINT") for f in e.fields]
    assert not any("global variables" in r for r in rules), (
        "imperative sentences inside pasted material were extracted as constraints"
    )


def test_sidechain_ignored(transcript):
    parsed = parse_transcript(transcript)
    all_values = " ".join(f.value for e in parsed.corpus.entities for f in e.fields)
    assert "sidechain noise" not in all_values


def test_turn_provenance(transcript):
    parsed = parse_transcript(transcript)
    decision = next(e for e in parsed.corpus.entities
                    if e.name.startswith("DECISION"))
    assert decision.sources[0].turn == 1
    assert str(decision.sources[0]) == "session:abcd1234#turn1"


def test_deterministic(transcript):
    a = parse_transcript(transcript)
    b = parse_transcript(transcript)
    names_a = [e.name for e in a.corpus.entities]
    names_b = [e.name for e in b.corpus.entities]
    assert names_a == names_b


def test_since_turn_incremental(transcript):
    full = parse_transcript(transcript)
    tail = parse_transcript(transcript, since_turn=full.last_turn)
    assert len(tail.corpus.entities) == 0
    assert tail.last_turn == full.last_turn


def test_todo_status_updates_are_not_frozen(tmp_path):
    entries = [
        _entry("assistant", [
            {"type": "tool_use", "name": "TodoWrite",
             "input": {"todos": [{"content": "Fix retry bug",
                                  "status": "in_progress"}]}}]),
        _entry("assistant", [
            {"type": "tool_use", "name": "TodoWrite",
             "input": {"todos": [{"content": "Fix retry bug",
                                  "status": "completed"}]}}]),
    ]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    task = next(e for e in parsed.corpus.entities if e.name.startswith("TASK"))
    status = next(f.value for f in task.fields if f.key == "STATUS")
    assert status == "completed", "later TodoWrite status must win"


def test_mixed_message_text_not_lost(tmp_path):
    entries = [_entry("user", [
        {"type": "tool_result", "tool_use_id": "t1", "is_error": False,
         "content": "ok"},
        {"type": "text",
         "text": "Also, never commit directly to main from now on."},
    ])]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    rules = [f.value for e in parsed.corpus.entities
             if e.name.startswith("CONSTRAINT") for f in e.fields]
    assert any("never commit directly to main" in r for r in rules), (
        "text in a mixed tool_result+text message was dropped"
    )


def test_error_block_list_content_not_repred(tmp_path):
    entries = [_entry("user", [
        {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
         "content": [{"type": "text", "text": "Timeout after 30s"}]},
    ])]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    err = next(e for e in parsed.corpus.entities if e.name.startswith("ERROR"))
    msg = next(f.value for f in err.fields if f.key == "MESSAGE")
    assert msg == "Timeout after 30s"
    assert "{" not in msg, f"repr garbage in error message: {msg!r}"


def test_bullet_list_constraints_split(tmp_path):
    entries = [_entry("user",
        "Ground rules for this work:\n"
        "- Do not modify the database schema.\n"
        "- Never push directly to the release branch.\n"
        "- Always run the linter before committing.")]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    rules = [f.value for e in parsed.corpus.entities
             if e.name.startswith("CONSTRAINT") for f in e.fields
             if f.key == "RULE"]
    assert len(rules) == 3, f"bullet list merged or dropped: {rules}"
