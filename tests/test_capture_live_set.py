"""Capture hygiene (#8) and live-set supersession (#9).

Acceptance is what a caller observes: parsed entities, gist text,
startup context, and events.jsonl. Fact ids of unbulleted inputs stay
on the content hash. A mixed 16-hex/64-hex ledger never guesses.
"""

from __future__ import annotations

import json

from ctxpack.agent.capture_config import (
    commit_subject_excluded,
    default_capture_config,
    load_capture_config,
    prepare_user_turn,
)
from ctxpack.agent.checkpoint import (
    build_brief,
    build_gist,
    build_project_gist,
    read_startup_context,
    run_checkpoint,
)
from ctxpack.agent.live_set import (
    choice_was,
    is_milestone_stale,
    resolve_supersedes_target,
)
from ctxpack.agent.session_reader import load_session, session_decisions, session_why
from ctxpack.agent.transcript_parser import parse_transcript, strip_leading_list_marker
from ctxpack.core import factid


def _entry(role, content, sid="sess0001-a", ts="2026-10-05T10:00:00Z"):
    body = content
    if role == "assistant" and isinstance(content, str):
        body = [{"type": "text", "text": content}]
    return {
        "type": role,
        "sessionId": sid,
        "timestamp": ts,
        "isSidechain": False,
        "isMeta": False,
        "cwd": ".",
        "message": {"role": role, "content": body},
    }


def _write(tmp_path, entries, name="t.jsonl"):
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(row) for row in entries),
        encoding="utf-8",
    )
    return str(path)


def _fields(entity):
    return {field.key: field.value for field in entity.fields}


def _by_kind(parsed, kind):
    return [e for e in parsed.corpus.entities if e.name.startswith(kind)]


def test_briefing_block_and_probe_exchange_bank_nothing(tmp_path):
    outside = "Decision: render pages with a plain string template."
    briefing = (
        "CTX BRIEFING (from the harness). Earlier choices:\n"
        "- Do not use jinja2.\n"
        "- Never write drafts to dist.\n"
        "Recall probe 1: what fallback does build use for the title?"
    )
    path = _write(tmp_path, [
        _entry("user", "build the site generator, milestone 1 and 2"),
        _entry("assistant", outside),
        _entry("user", briefing, ts="2026-10-05T10:01:00Z"),
        _entry("assistant", "Decision: the title fallback is mdsite (recall answer).",
               ts="2026-10-05T10:01:30Z"),
        _entry("user", "now do milestone 3", ts="2026-10-05T10:02:00Z"),
        _entry("assistant", "Decision: drop drafts from dist.",
               ts="2026-10-05T10:03:00Z"),
    ])
    parsed = parse_transcript(path)
    blob = "\n".join(field.value for e in parsed.corpus.entities for field in e.fields)
    assert "jinja2" not in blob
    assert "Never write drafts" not in blob
    assert "mdsite" not in blob
    assert "recall answer" not in blob
    assert outside in blob
    assert "drop drafts from dist" in blob
    decisions = _by_kind(parsed, "DECISION")
    assert len(decisions) == 2


def test_rejected_and_dead_end_markers_are_marker_stated(tmp_path):
    lines = "\n".join([
        "Rejected: jinja2 templates, because they add a runtime dependency.",
        "Rejected: writing drafts to dist, the spec forbids it.",
        "Rejected: a global cache dict; it breaks test isolation.",
        "Dead end: a process-global template cache, it breaks isolation too.",
        "The docs mention `Rejected:` as a marker, not a choice.",
        "Decision: use string.Template for pages.",
    ])
    parsed = parse_transcript(_write(tmp_path, [
        _entry("user", "go"),
        _entry("assistant", lines),
    ]))
    failed = _by_kind(parsed, "FAILED-APPROACH")
    assert len(failed) == 4
    bases = {_fields(e)["BASIS"] for e in failed}
    assert bases == {"marker_stated"}
    notes = {_fields(e)["NOTE"] for e in failed}
    assert all(note.startswith("Rejected:") or note.startswith("Dead end:") for note in notes)
    assert all(not note.startswith("-") for note in notes)
    assert not any("docs mention" in note for note in notes)
    assert _by_kind(parsed, "DECISION")


def test_bullet_strip_keeps_negation_and_unbulleted_fact_id(tmp_path):
    plain = "Decision: use string.Template for pages."
    bulleted = "- Constraint: Do not use jinja2 in the renderer."
    parsed = parse_transcript(_write(tmp_path, [
        _entry("user", "- Do not touch the auth service during this change."),
        _entry("assistant", plain + "\n" + bulleted),
    ]))
    rules = [_fields(e)["RULE"] for e in _by_kind(parsed, "CONSTRAINT")]
    assert any(rule == "Do not touch the auth service during this change." for rule in rules)
    assert any(rule == "Constraint: Do not use jinja2 in the renderer." for rule in rules)
    assert all(not rule.startswith("-") for rule in rules)
    joined = " | ".join(rules)
    assert joined.lower().count("not") == 2
    decision = _fields(_by_kind(parsed, "DECISION")[0])
    assert decision["DECISION"] == plain
    assert decision["FACT-ID"] == factid.fact_id("DECISION", plain)
    assert strip_leading_list_marker("- Never restart auth") == "Never restart auth"
    again = parse_transcript(_write(tmp_path, [
        _entry("user", "- Do not touch the auth service during this change."),
        _entry("assistant", plain + "\n" + bulleted),
    ], name="t2.jsonl"))
    ids_a = sorted(e.name for e in parsed.corpus.entities)
    ids_b = sorted(e.name for e in again.corpus.entities)
    assert ids_a == ids_b


def test_repo_config_and_commit_subject_prefixes(tmp_path):
    (tmp_path / "ctxpack.toml").write_text(
        "\n".join([
            "[capture]",
            'ignore_turn_prefixes = ["recall:", "hooks:", "harness:", "local-probe:"]',
            'ignore_commit_subject_prefixes = ["harness:", "wip:"]',
            'ignore_blocks = ["LOCAL BLOCK:::", "<box>:::</box>"]',
            "capture_tool_bash = false",
            "",
        ]),
        encoding="utf-8",
    )
    cfg = load_capture_config(str(tmp_path))
    assert cfg.capture_tool_bash is False
    assert "local-probe:" in cfg.ignore_turn_prefixes
    mined, skip = prepare_user_turn("local-probe: what did we decide?", cfg)
    assert mined is None and skip is False
    assert commit_subject_excluded("harness: refresh the fixture", cfg)
    assert not commit_subject_excluded("fix the renderer", cfg)
    assert commit_subject_excluded("hooks: regen", default_capture_config())
    text, _skip = prepare_user_turn(
        "keep this.\n<box>\n- Do not leak.\n</box>\nAlways run the tests.",
        cfg,
    )
    assert text is not None
    assert "Do not leak" not in text
    assert "Always run the tests" in text
    assert "keep this" in text


def test_tool_bash_rows_are_switchable(tmp_path):
    entries = [
        _entry("assistant", [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "echo hi", "description": "say hi to the log"},
        }]),
    ]
    # tool_use content is a list already; _entry wraps strings only
    path = _write(tmp_path, entries)
    parsed = parse_transcript(path)
    assert _by_kind(parsed, "TOOL-BASH")
    from ctxpack.agent.capture_config import CaptureConfig
    quiet = parse_transcript(path, capture=CaptureConfig(capture_tool_bash=False))
    assert not _by_kind(quiet, "TOOL-BASH")


def test_superseded_decision_leaves_startup_context(tmp_path):
    old = "Decision: until Milestone 3, build uses the title mdsite as a fallback."
    new = "Decision: when mdsite.toml is present its title replaces the fallback."
    old_id = factid.fact_id("DECISION", old)
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, [
        _entry("user", "build the site generator", sid="11111111-a"),
        _entry("assistant", old + "\nDecision: render pages with a plain string template.",
               sid="11111111-a"),
    ], name="s1.jsonl"), str(out), as_of="2026-10-03")
    run_checkpoint(_write(tmp_path, [
        _entry("user", "now do milestone 3", sid="22222222-b", ts="2026-10-02T10:00:00Z"),
        _entry("assistant",
               f"{new}\nSupersedes: {old_id} — mdsite.toml now owns the title.",
               sid="22222222-b", ts="2026-10-02T10:01:00Z"),
    ], name="s2.jsonl"), str(out), as_of="2026-10-03")
    ctx = read_startup_context(str(out))
    brief = build_brief(str(out))
    assert ctx == brief
    assert "Changed choices" in ctx
    assert new in ctx
    assert old not in ctx
    assert choice_was(old) in ctx
    doc, sid = load_session(str(out), "22222222")
    decisions = session_decisions(doc, sid)
    texts = [row["text"] for row in decisions["decisions"]]
    assert new in texts
    assert old not in texts
    assert decisions["changed_choices"]
    events = (out / "events.jsonl").read_text(encoding="utf-8")
    assert "fact_superseded" in events
    why = session_why(doc, sid, old_id, ledger_dir=str(out))
    assert why["found"] is True


def test_retracted_fact_leaves_the_live_set(tmp_path):
    old = "Decision: keep drafts in the source tree until review."
    old_id = factid.fact_id("DECISION", old)
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, [
        _entry("assistant", old, sid="11111111-a"),
    ], name="a.jsonl"), str(out), as_of="2026-10-03")
    run_checkpoint(_write(tmp_path, [
        _entry("assistant",
               f"Retracted: {old_id} — drafts now stay out of the tree.",
               sid="22222222-b", ts="2026-10-04T10:00:00Z"),
    ], name="b.jsonl"), str(out), as_of="2026-10-04")
    ctx = read_startup_context(str(out))
    assert old not in ctx
    assert "Retracted" in ctx
    assert old_id in ctx
    events = (out / "events.jsonl").read_text(encoding="utf-8")
    assert "fact_retracted" in events
    doc, sid = load_session(str(out), "11111111")
    texts = [row["text"] for row in session_decisions(doc, sid)["decisions"]]
    # The session ledger still holds the fact; why can recover it.
    assert old in texts
    why = session_why(doc, sid, "drafts in the source tree", ledger_dir=str(out))
    assert why["found"] is True


def test_unresolved_fork_is_rendered(tmp_path):
    base = "Decision: keep the title fallback as mdsite until told otherwise."
    base_id = factid.fact_id("DECISION", base)
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, [
        _entry("assistant", base, sid="11111111-a"),
    ], name="a.jsonl"), str(out), as_of="2026-10-03")
    for sid, word in (("22222222-b", "alpha"), ("33333333-c", "beta")):
        text = (
            f"Decision: title ownership moves to the {word} config file.\n"
            f"Supersedes: {base_id} — {word} config landed."
        )
        run_checkpoint(_write(tmp_path, [
            _entry("assistant", text, sid=sid, ts="2026-10-04T10:00:00Z"),
        ], name=f"{sid}.jsonl"), str(out), as_of="2026-10-04")
    ctx = read_startup_context(str(out))
    assert "unresolved fork" in ctx
    assert "alpha config file" in ctx
    assert "beta config file" in ctx
    assert "Changed choices" not in ctx


def test_stale_milestone_scope_drops_only_when_done(tmp_path):
    stale = "Decision: Milestone 4 will drop drafts from dist once it lands."
    kept = "Decision: render pages with a plain string template."
    path = _write(tmp_path, [
        _entry("assistant", stale + "\n" + kept),
    ])
    parsed = parse_transcript(path)
    open_gist = build_gist(parsed, done_milestones=())
    done_gist = build_gist(parsed, done_milestones={"Milestone 4"})
    not_yet = build_gist(parsed, done_milestones={"3"})
    assert stale in open_gist
    assert stale in not_yet
    assert stale not in done_gist
    assert kept in done_gist
    assert "Dropped 1 stale item" in done_gist
    assert not is_milestone_stale(kept, {"4"})
    assert is_milestone_stale(stale, {"4"})
    assert is_milestone_stale(
        "Decision: until Milestone 3, build uses the title mdsite as a fallback.",
        {"m3"},
    )


def test_ledger_without_supersession_omits_new_headings(tmp_path):
    text = "Decision: render pages with a plain string template."
    parsed = parse_transcript(_write(tmp_path, [
        _entry("assistant", text),
    ]))
    gist = build_gist(parsed)
    assert "Changed choices" not in gist
    assert "unresolved fork" not in gist
    assert "Supersession unresolved" not in gist
    assert text in gist
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, [
        _entry("assistant", text, sid="11111111-a"),
    ], name="a.jsonl"), str(out), as_of="2026-10-03")
    run_checkpoint(_write(tmp_path, [
        _entry("assistant", "Decision: keep the drafts next to the source.",
               sid="22222222-b"),
    ], name="b.jsonl"), str(out), as_of="2026-10-03")
    project = build_project_gist(str(out), exclude_session="22222222")
    assert text in project
    assert "Changed choices" not in project


def test_exact_16_and_64_hex_and_ambiguous_mixed_ledger(tmp_path):
    short = "a" * 16
    longer = short + ("b" * 48)
    other = "c" * 64
    assert resolve_supersedes_target(short, {short})["status"] == "matched"
    assert resolve_supersedes_target(other, {other})["status"] == "matched"
    mixed = resolve_supersedes_target(short, {short, longer})
    assert mixed["status"] == "ambiguous"
    assert mixed["matches"] == (short, longer)
    prefix_only = resolve_supersedes_target(short, {longer})
    assert prefix_only["status"] == "ambiguous"
    assert resolve_supersedes_target("ab" * 20, {short})["status"] == "invalid"
    assert resolve_supersedes_target(other, {short})["status"] == "unmatched"

    base = "Decision: keep the cache key stable across processes."
    base_id = factid.fact_id("DECISION", base)
    sibling = base_id + ("d" * 48)
    assert len(sibling) == 64
    out = tmp_path / "ctx"
    out.mkdir()
    (out / "session-ffffeeee.ctx").write_text(
        f"FACT-ID: {sibling}\n", encoding="utf-8")
    run_checkpoint(_write(tmp_path, [
        _entry("assistant",
               base + f"\nDecision: rotate the cache key per process.\n"
               f"Supersedes: {base_id} — mixed ledger must not guess.",
               sid="11111111-a"),
    ], name="a.jsonl"), str(out), as_of="2026-10-05")
    gist = (out / "session-11111111-gist.md").read_text(encoding="utf-8")
    assert "Supersession unresolved" in gist
    assert "not applied" in gist
    assert base in gist
    events = (out / "events.jsonl").read_text(encoding="utf-8")
    assert "fact_supersede_ambiguous" in events
    assert "fact_superseded" not in events

    out64 = tmp_path / "ctx64"
    target = "e" * 64
    run_checkpoint(_write(tmp_path, [
        _entry("assistant",
               "Decision: adopt the exact literal id for this row.\n"
               f"Supersedes: {target} — 64-hex exact match.",
               sid="44444444-d"),
    ], name="d.jsonl"), str(out64), as_of="2026-10-05")
    ev64 = (out64 / "events.jsonl").read_text(encoding="utf-8")
    assert "fact_superseded" in ev64
    assert target in ev64
    gist64 = (out64 / "session-44444444-gist.md").read_text(encoding="utf-8")
    assert "Supersession unresolved" not in gist64

    ignored = parse_transcript(_write(tmp_path, [
        _entry("assistant",
               "Decision: ignore a git sha in the supersedes slot.\n"
               "Supersedes: " + "ab" * 20 + " — not an id.",
               sid="55555555-e"),
    ], name="e.jsonl"))
    decision = _fields(_by_kind(ignored, "DECISION")[0])
    assert "SUPERSEDES-FACT-ID" not in decision


def test_live_set_and_gist_are_byte_stable(tmp_path):
    old = "Decision: keep retry backoff at 250ms for vendor calls."
    new = "Decision: raise retry backoff to 750ms for vendor calls."
    old_id = factid.fact_id("DECISION", old)
    body = f"{old}\n{new}\nSupersedes: {old_id} -- load test replaced 250ms with 750ms."
    path = _write(tmp_path, [_entry("assistant", body)])
    first = build_gist(parse_transcript(path))
    second = build_gist(parse_transcript(path))
    assert first == second
    assert old not in first
    assert new in first
    assert "Changed choices" in first
