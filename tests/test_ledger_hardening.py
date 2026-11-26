"""P0 ledger hardening: atomic writes, corrupt diagnostics, session ids."""

from __future__ import annotations

import json
import os

import pytest

from ctxpack.agent.brief import brief, brief_result
from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.agent.ledger import (
    UnsafeSessionId,
    atomic_write_text,
    existing_ctx_path,
    ledger_stem,
    resolve_explicit,
    stem_on_disk,
)
from ctxpack.agent.session_reader import resolve_session
from ctxpack.core.tokens import count_budget


def _entry(role, content, sid, ts="2026-11-01T10:00:00Z"):
    if role == "assistant" and isinstance(content, str):
        content = [{"type": "text", "text": content}]
    return {
        "type": role,
        "sessionId": sid,
        "timestamp": ts,
        "isSidechain": False,
        "isMeta": False,
        "message": {"role": role, "content": content},
    }


def _transcript(path, sid, text):
    rows = [
        _entry("user", "note the choice", sid),
        _entry("assistant", text, sid),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return str(path)


def test_atomic_write_replaces_and_keeps_lf(tmp_path):
    target = tmp_path / "session-demo.ctx"
    target.write_text("old\n", encoding="utf-8", newline="\n")
    atomic_write_text(str(target), "alpha\r\nbeta\n")
    raw = target.read_bytes()
    assert raw == b"alpha\r\nbeta\n" or raw == b"alpha\nbeta\n"
    # newline="\n" must not introduce CR on its own. A CR that was in the
    # string stays; the writer does not translate \n to \r\n.
    atomic_write_text(str(target), "one\ntwo\n")
    assert target.read_bytes() == b"one\ntwo\n"
    assert not list(tmp_path.glob(".ctxpack-*"))


def test_atomic_write_leaves_the_target_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "ledger.ctx"
    target.write_bytes(b"previous\n")

    def boom(src, dst):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="simulated crash"):
        atomic_write_text(str(target), "truncated")
    assert target.read_bytes() == b"previous\n"
    assert not list(tmp_path.glob(".ctxpack-*"))


def test_shared_prefix_sessions_do_not_overwrite(tmp_path):
    out = tmp_path / "ctx"
    first = _transcript(
        tmp_path / "a.jsonl", "abc12345-run1",
        "Decision: keep the first run's cache in memory.")
    second = _transcript(
        tmp_path / "b.jsonl", "abc12345-run2",
        "Decision: move the second run's cache to redis.")
    run_checkpoint(first, str(out), as_of="2026-11-01")
    run_checkpoint(second, str(out), as_of="2026-11-01")
    stem1 = ledger_stem("abc12345-run1")
    stem2 = ledger_stem("abc12345-run2")
    assert stem1 != stem2
    assert stem1 != "abc12345" and stem2 != "abc12345"
    file1 = (out / f"session-{stem1}.ctx").read_text(encoding="utf-8")
    file2 = (out / f"session-{stem2}.ctx").read_text(encoding="utf-8")
    assert "first run" in file1
    assert "second run" in file2
    assert "second run" not in file1
    assert "first run" not in file2
    sid1, _ = resolve_session(str(out), "abc12345-run1")
    sid2, _ = resolve_session(str(out), "abc12345-run2")
    assert sid1 == stem1 and sid2 == stem2


def test_path_traversal_session_id_is_rejected(tmp_path):
    for bad in ("../etc/passwd", "foo/bar", "..", "a\\b", "foo/../../x"):
        with pytest.raises(UnsafeSessionId):
            ledger_stem(bad)
    rows = _transcript(tmp_path / "evil.jsonl", "../outside",
                       "Decision: do not write this.")
    with pytest.raises(UnsafeSessionId):
        run_checkpoint(rows, str(tmp_path / "ctx"), as_of="2026-11-01")
    assert not (tmp_path / "ctx").exists()


def test_sanitized_ids_do_not_share_a_stem():
    space = ledger_stem("a b")
    colon = ledger_stem("a:b")
    assert space != colon
    assert space.startswith("a-b-")
    assert colon.startswith("a-b-")
    assert ledger_stem("a b") == space
    assert ledger_stem("abc12345-run1") == "abc12345-run1"


def test_legacy_read_does_not_claim_another_sessions_file(tmp_path):
    out = tmp_path / "ctx"
    old = "abc12345-old"
    run_checkpoint(
        _transcript(tmp_path / "old.jsonl", old,
                    "Decision: the old ledger stays with its owner."),
        str(out), as_of="2026-11-01")
    full = out / f"session-{ledger_stem(old)}.ctx"
    legacy = out / "session-abc12345.ctx"
    legacy.write_bytes(full.read_bytes())
    full.unlink()
    assert stem_on_disk(str(out), old) == "abc12345"
    assert stem_on_disk(str(out), "abc12345-new") == "abc12345-new"
    assert existing_ctx_path(str(out), "abc12345-new") == ""
    resolved, path = resolve_explicit(str(out), "abc12345-new")
    assert resolved == "abc12345-new"
    assert not os.path.isfile(path)
    owned, owned_path = resolve_explicit(str(out), old)
    assert owned == "abc12345"
    assert owned_path.endswith("session-abc12345.ctx")


def test_long_ids_get_distinct_hash_suffixes():
    left = "s" * 90 + "alpha"
    right = "s" * 90 + "beta"
    a = ledger_stem(left)
    b = ledger_stem(right)
    assert a != b
    assert len(a) <= 80 and len(b) <= 80
    assert ledger_stem(left) == a


def test_legacy_eight_char_file_is_still_readable(tmp_path):
    out = tmp_path / "ctx"
    sid = "feedbeef-session"
    run_checkpoint(
        _transcript(tmp_path / "t.jsonl", sid,
                    "Decision: the legacy file must still open."),
        str(out), as_of="2026-11-01")
    full = out / f"session-{ledger_stem(sid)}.ctx"
    gist = out / f"session-{ledger_stem(sid)}-gist.md"
    legacy = out / "session-feedbeef.ctx"
    legacy_gist = out / "session-feedbeef-gist.md"
    legacy.write_bytes(full.read_bytes())
    if gist.exists():
        legacy_gist.write_bytes(gist.read_bytes())
    full.unlink()
    if gist.exists():
        gist.unlink()
    resolved, path = resolve_explicit(str(out), sid)
    assert resolved == "feedbeef"
    assert path.endswith("session-feedbeef.ctx")
    text = brief(str(out), budget=4000)
    assert "legacy file must still open" in text


def test_corrupt_ledger_is_warned_and_healthy_session_remains(tmp_path, capsys):
    out = tmp_path / "ctx"
    run_checkpoint(
        _transcript(tmp_path / "ok.jsonl", "healthy1-session",
                    "Decision: the healthy session stays readable."),
        str(out), as_of="2026-11-01")
    (out / "session-corrupt1.json").write_text(
        '{"session": "cut', encoding="utf-8")
    # A truncated JSON blob is not a .ctx ledger. The reader keys off
    # session-*.ctx, so plant the corrupt bytes under that name too.
    (out / "session-corrupt1.ctx").write_text(
        '{"turns": 1, "note": "truncated', encoding="utf-8")
    (out / "session-cutmd.ctx").write_text(
        "## DECISION\nNOTE: cut off mid-sentence", encoding="utf-8")
    result = brief_result(str(out), budget=4000)
    err = capsys.readouterr().err
    assert "corrupt ledger" in err
    assert "session-corrupt1.ctx" in err
    assert "parse_error" in err
    assert any(d["path"] == "session-corrupt1.ctx" and d["kind"] == "corrupt_ledger"
               for d in result.diagnostics)
    assert "healthy session stays readable" in result.text
    assert count_budget(result.text, "chars") <= 4000
