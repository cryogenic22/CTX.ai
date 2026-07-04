"""Stop-hook debounced checkpoint + cross-session project gist."""

import json

import pytest

from ctxpack.agent.checkpoint import (
    build_project_gist,
    read_startup_context,
    run_checkpoint,
    should_checkpoint_on_stop,
)


def _entry(etype, content, sid, ts="2026-07-04T10:00:00Z"):
    return {
        "type": etype,
        "sessionId": sid,
        "timestamp": ts,
        "isSidechain": False,
        "isMeta": False,
        "message": {"role": etype, "content": content},
    }


def _turn_pair(sid, decision):
    return [
        _entry("user", f"please handle {decision}", sid),
        _entry("assistant",
               [{"type": "text", "text": f"Decision: {decision}."}], sid),
    ]


def _write(tmp_path, sid, decisions, name=None):
    entries = []
    for d in decisions:
        entries.extend(_turn_pair(sid, d))
    path = tmp_path / (name or f"{sid}.jsonl")
    path.write_text("\n".join(json.dumps(e) for e in entries),
                    encoding="utf-8")
    return str(path)


# ── Stop-hook debounce ──


def test_stop_debounce_lifecycle(tmp_path):
    out = str(tmp_path / "ctx")
    sid = "aaaa1111-session"
    transcript = _write(tmp_path, sid, [f"use option {i}" for i in range(3)])

    # No checkpoint yet → pack
    assert should_checkpoint_on_stop(transcript, out, sid) is True
    run_checkpoint(transcript, out, as_of="2026-07-04")

    # Nothing new since → skip
    assert should_checkpoint_on_stop(transcript, out, sid) is False

    # Grow by less than the debounce window → still skip
    transcript = _write(tmp_path, sid,
                        [f"use option {i}" for i in range(4)])  # +2 turns
    assert should_checkpoint_on_stop(transcript, out, sid,
                                     debounce_turns=10) is False

    # ...but an explicit debounce of 0 means every new turn packs
    assert should_checkpoint_on_stop(transcript, out, sid,
                                     debounce_turns=0) is True

    # Grow past the window → pack
    transcript = _write(tmp_path, sid,
                        [f"use option {i}" for i in range(9)])  # +12 turns
    assert should_checkpoint_on_stop(transcript, out, sid,
                                     debounce_turns=10) is True


def test_stop_debounce_env_override(tmp_path, monkeypatch):
    out = str(tmp_path / "ctx")
    sid = "bbbb2222-session"
    transcript = _write(tmp_path, sid, ["use redis"])
    run_checkpoint(transcript, out, as_of="2026-07-04")
    transcript = _write(tmp_path, sid, ["use redis", "add ttl"])  # +2 turns

    monkeypatch.setenv("CTXPACK_STOP_DEBOUNCE_TURNS", "1")
    assert should_checkpoint_on_stop(transcript, out, sid) is True
    monkeypatch.setenv("CTXPACK_STOP_DEBOUNCE_TURNS", "50")
    assert should_checkpoint_on_stop(transcript, out, sid) is False


def test_stop_missing_transcript_never_packs(tmp_path):
    assert should_checkpoint_on_stop(
        str(tmp_path / "nope.jsonl"), str(tmp_path), "x") is False


# ── Cross-session project gist ──


def test_single_session_has_no_project_gist(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, "aaaa1111-s", ["use redis for cache"]),
                   str(out), as_of="2026-07-04")
    assert build_project_gist(str(out), exclude_session="aaaa1111") == ""
    assert not (out / "project-gist.md").exists()


def test_project_gist_rolls_up_earlier_sessions(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, "aaaa1111-s", ["use redis for cache"]),
                   str(out), as_of="2026-07-04")
    run_checkpoint(_write(tmp_path, "bbbb2222-s", ["shard by tenant id"]),
                   str(out), as_of="2026-07-04")

    # After the second checkpoint the rollup exists and covers session A only
    text = (out / "project-gist.md").read_text(encoding="utf-8")
    assert "use redis for cache" in text
    assert "(s:aaaa1111#turn" in text
    assert "shard by tenant id" not in text, (
        "current session must be excluded — its own gist is injected")

    # Third session: rollup now covers A and B
    run_checkpoint(_write(tmp_path, "cccc3333-s", ["adopt uv for installs"]),
                   str(out), as_of="2026-07-04")
    text = (out / "project-gist.md").read_text(encoding="utf-8")
    assert "use redis for cache" in text and "shard by tenant id" in text
    assert "adopt uv for installs" not in text
    assert text.index("use redis") < text.index("shard by"), "oldest first"


def test_project_gist_dedupes_repeated_decisions(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, "aaaa1111-s", ["use redis for cache"]),
                   str(out), as_of="2026-07-04")
    run_checkpoint(_write(tmp_path, "bbbb2222-s", ["use redis for cache"]),
                   str(out), as_of="2026-07-04")
    run_checkpoint(_write(tmp_path, "cccc3333-s", ["something else"]),
                   str(out), as_of="2026-07-04")
    text = (out / "project-gist.md").read_text(encoding="utf-8")
    assert text.count("use redis for cache") == 1


def test_startup_context_combines_project_and_latest(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, "aaaa1111-s", ["use redis for cache"]),
                   str(out), as_of="2026-07-04")
    # One session: startup context == the session gist alone
    ctx1 = read_startup_context(str(out))
    assert "Session memory" in ctx1 and "Project memory" not in ctx1

    run_checkpoint(_write(tmp_path, "bbbb2222-s", ["shard by tenant id"]),
                   str(out), as_of="2026-07-04")
    ctx2 = read_startup_context(str(out))
    assert "Project memory" in ctx2 and "Session memory" in ctx2
    assert ctx2.index("Project memory") < ctx2.index("Session memory")
    assert "use redis for cache" in ctx2      # history via rollup
    assert "shard by tenant id" in ctx2       # last session via its gist


def test_project_gist_is_deterministic(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, "aaaa1111-s", ["use redis"]),
                   str(out), as_of="2026-07-04")
    run_checkpoint(_write(tmp_path, "bbbb2222-s", ["shard by tenant"]),
                   str(out), as_of="2026-07-04")
    a = build_project_gist(str(out), exclude_session="bbbb2222")
    b = build_project_gist(str(out), exclude_session="bbbb2222")
    assert a == b


def test_project_gist_survives_a_corrupt_ledger(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_write(tmp_path, "aaaa1111-s", ["use redis"]),
                   str(out), as_of="2026-07-04")
    (out / "session-deadbeef.ctx").write_text("not a ctx file at all",
                                              encoding="utf-8")
    run_checkpoint(_write(tmp_path, "bbbb2222-s", ["shard by tenant"]),
                   str(out), as_of="2026-07-04")
    text = (out / "project-gist.md").read_text(encoding="utf-8")
    assert "use redis" in text  # good ledger still rolled up
