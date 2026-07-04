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


# ── Dogfood day-1 regressions (2026-07-03) ──


def _parse_assistant_text(tmp_path, text):
    entries = [_entry("assistant", [{"type": "text", "text": text}])]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return parse_transcript(str(path))


def _decision_values(parsed):
    return [f.value for e in parsed.corpus.entities
            if e.name.startswith("DECISION") for f in e.fields
            if f.key == "DECISION"]


def test_decision_mention_in_backticks_not_extracted(tmp_path):
    # Talking ABOUT the convention must not trigger it (use vs mention).
    parsed = _parse_assistant_text(tmp_path,
        "Folding it in gives us the first test of the `Decision:` convention.\n"
        "Sessions must state `Decision: ...` lines, which extract trivially.\n"
        "The gist only had 2 decisions since the `Decision:` rule came late.")
    assert _decision_values(parsed) == [], (
        f"backticked mentions extracted as decisions: {_decision_values(parsed)}"
    )
    assert parsed.stats.decisions == 0


def test_decision_marker_must_start_sentence(tmp_path):
    # A list-introducer line that merely ENDS with "verdict:" is not a
    # decision (the real 829-turn gist extracted exactly this line).
    parsed = _parse_assistant_text(tmp_path,
        "Recording the build outcome — including the honest extraction-gate verdict:\n"
        "- structured signals extracted well")
    assert _decision_values(parsed) == []


def test_decision_marker_variants_extracted(tmp_path):
    parsed = _parse_assistant_text(tmp_path,
        "Decision: use exponential backoff with base 750ms.\n"
        "- Decision: scope the eval to Opus-class answerers.\n"
        "**Decision:** keep the ledger append-only.")
    values = _decision_values(parsed)
    assert len(values) == 3, f"marker variant missed: {values}"
    assert parsed.stats.decisions == 3


def test_root_cause_noun_phrase_not_a_decision(tmp_path):
    # "root cause" fires only as an assertion; passing references don't.
    parsed = _parse_assistant_text(tmp_path,
        "The diagnosis session (where I found the root cause) was never packed.\n"
        "That matched via the \"root cause\" verb pattern in the extractor.")
    assert _decision_values(parsed) == []

    asserted = _parse_assistant_text(tmp_path,
        "The root cause was a stale Redis fixture.")
    assert len(_decision_values(asserted)) == 1


def test_failed_approach_mention_in_backticks_not_extracted(tmp_path):
    parsed = _parse_assistant_text(tmp_path,
        "The parser greps for the `didn't work because` pattern in prose.")
    notes = [f.value for e in parsed.corpus.entities
             if e.name.startswith("FAILED") for f in e.fields]
    assert notes == [], f"backticked mention extracted as failed approach: {notes}"


def test_constraint_mention_in_backticks_not_extracted(tmp_path):
    entries = [_entry("user",
        "I like how the guide phrases `never push to main` as an example rule.")]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    rules = [f.value for e in parsed.corpus.entities
             if e.name.startswith("CONSTRAINT") for f in e.fields]
    assert rules == [], f"backticked mention extracted as constraint: {rules}"


def test_read_path_adoption_counters(tmp_path):
    """ledger_reads vs transcript_greps — the raw-fallback telemetry."""
    entries = [_entry("assistant", [
        # ledger reads: CLI + MCP spellings
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "python -m ctxpack.cli.main session decisions",
                   "description": "Read ledger decisions"}},
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "ctxpack session timeline --limit 5",
                   "description": "Read ledger timeline"}},
        {"type": "tool_use", "name": "mcp__ctxpack__ctx/session_recall",
         "input": {"query": "backoff"}},
        # raw-transcript fallbacks: Bash grep + Read tool
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "grep decision "
                              "~/.claude/projects/proj/abc.jsonl",
                   "description": "Grep raw transcript"}},
        {"type": "tool_use", "name": "Read",
         "input": {"file_path": "C:\\Users\\k\\.claude\\projects\\p\\s.jsonl"}},
        # neither: the checkpoint WRITE references the transcript path
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "ctxpack checkpoint --transcript "
                              "~/.claude/projects/proj/abc.jsonl",
                   "description": "Checkpoint the session"}},
        # neither: ordinary bash
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "pytest -q", "description": "Run tests"}},
    ])]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    stats = parse_transcript(str(path)).stats
    assert stats.ledger_reads == 3, f"ledger_reads={stats.ledger_reads}"
    assert stats.transcript_greps == 2, (
        f"transcript_greps={stats.transcript_greps}")


def test_task_notification_not_a_user_request(tmp_path):
    entries = [
        _entry("user", "<task-notification>\n<task-id>bl9o6g0ma</task-id>\n"
                       "<output-file>C:\\tmp\\tasks\\bl9o6g0ma.output</output-file>\n"
                       "<status>completed</status>\n</task-notification>"),
        # unclosed variant (truncated write) must also be dropped
        _entry("user", "<task-notification>\n<task-id>xyz</task-id>\n<status>comp"),
        _entry("user", "what next"),
    ]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    parsed = parse_transcript(str(path))
    requests = [f.value for e in parsed.corpus.entities
                if e.name.startswith("USER-REQUEST") for f in e.fields
                if f.key == "REQUEST"]
    assert requests == ["what next"], (
        f"harness notification leaked into user requests: {requests}"
    )
    assert parsed.stats.requests == 1
    assert parsed.stats.user_turns == 1


# ── Agent-stated constraints (feedback P2-8, 2026-07-04) ──
# Cohort evidence: 49 decisions vs 1 constraint banked across 10 sessions —
# constraints only extracted from user imperatives, but in agent-driven
# sessions the load-bearing rules are stated by the ASSISTANT.


def _constraint_values(parsed):
    return [f.value for e in parsed.corpus.entities
            if e.name.startswith("CONSTRAINT") for f in e.fields
            if f.key == "RULE"]


def test_agent_constraint_marker_extracted(tmp_path):
    parsed = _parse_assistant_text(tmp_path,
        "Constraint: never bank bare numbers as literals.\n"
        "- Constraint: eval results are immutable; write new versioned files.\n"
        "**Invariant:** the checkpoint journal is append-only.")
    values = _constraint_values(parsed)
    assert len(values) == 3, f"marker variant missed: {values}"
    assert parsed.stats.constraints == 3
    assert "never bank bare numbers" in values[0], (
        "constraint must be stored verbatim, negation intact")


def test_agent_constraint_mention_not_extracted(tmp_path):
    # Use-vs-mention guard, same as Decision: — backticked mentions and
    # mid-sentence occurrences must not fire.
    parsed = _parse_assistant_text(tmp_path,
        "Sessions should state `Constraint: ...` lines for operating rules.\n"
        "This constraint: matters only when sentence-leading, so no fire.")
    assert _constraint_values(parsed) == [], (
        f"mention extracted as constraint: {_constraint_values(parsed)}")
    assert parsed.stats.constraints == 0
