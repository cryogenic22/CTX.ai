"""Capture-coverage reconciliation (setu field gap 2026-07-21):
classification, backfill archive semantics, gap warning, CLI + hook
surfaces. All fixtures synthetic."""

import json
import os
import time

from ctxpack.agent.backfill import (
    capture_coverage,
    format_gap_warning,
    run_backfill,
)
from ctxpack.agent.checkpoint import _claude_project_dir_name, run_checkpoint
from ctxpack.agent.session_reader import resolve_session
from ctxpack.cli.main import main

OLD = -86400  # seconds relative to now: safely past the active slack


def _setup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    tdir = home / "projects" / _claude_project_dir_name(str(repo))
    tdir.mkdir(parents=True)
    out = repo / ".claude" / "ctx"
    return repo, home, tdir, out


def _cc_transcript(tdir, sid, text="Ship the fix. Do not break the API.",
                   age_s=OLD):
    rows = [{"type": "user", "sessionId": sid, "uuid": "u1",
             "message": {"content": text}},
            {"type": "assistant", "sessionId": sid, "uuid": "u2",
             "message": {"content": [{"type": "text", "text":
                         "Decision: patch the retry path because the "
                         "cap is 40 req/min."}]}}]
    path = tdir / f"{sid}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    when = time.time() + age_s
    os.utime(path, (when, when))
    return path


def test_coverage_classification(tmp_path):
    repo, home, tdir, out = _setup(tmp_path)
    _cc_transcript(tdir, "unpacked1-0000-0000-0000-000000000000")
    _cc_transcript(tdir, "active11-0000-0000-0000-000000000000", age_s=0)
    packed = _cc_transcript(tdir, "packed11-0000-0000-0000-000000000000")
    run_checkpoint(str(packed), str(out), as_of="2026-07-21")
    stale = _cc_transcript(tdir, "stale111-0000-0000-0000-000000000000")
    run_checkpoint(str(stale), str(out), as_of="2026-07-21")
    # transcript kept growing long after its last checkpoint
    when = time.time() + OLD
    os.utime(out / "session-stale111.ctx", (when - 7200, when - 7200))

    cov = capture_coverage(str(repo), str(out), claude_home=str(home))
    by = {s.session[:8]: s.status for s in cov.sessions}
    assert by == {"unpacked": "unpacked", "active11": "active",
                  "packed11": "packed", "stale111": "stale"}
    assert not cov.worktree_local_ledger


def test_exclude_session_marks_own_transcript_active(tmp_path):
    repo, home, tdir, out = _setup(tmp_path)
    _cc_transcript(tdir, "selfsess-0000-0000-0000-000000000000")
    cov = capture_coverage(str(repo), str(out), claude_home=str(home),
                           exclude_session="selfsess")
    assert cov.sessions[0].status == "active"


def test_gap_warning_only_for_unpacked(tmp_path):
    repo, home, tdir, out = _setup(tmp_path)
    _cc_transcript(tdir, "gapsess1-0000-0000-0000-000000000000")
    cov = capture_coverage(str(repo), str(out), claude_home=str(home))
    warning = format_gap_warning(cov)
    assert "[ctx capture gap]" in warning
    assert "gapsess1" in warning and "ctxpack backfill" in warning
    # once packed, silence
    run_backfill(str(repo), str(out), as_of="2026-07-21",
                 claude_home=str(home))
    cov2 = capture_coverage(str(repo), str(out), claude_home=str(home))
    assert format_gap_warning(cov2) == ""


def test_backfill_packs_and_is_idempotent(tmp_path):
    repo, home, tdir, out = _setup(tmp_path)
    _cc_transcript(tdir, "backfil1-0000-0000-0000-000000000000")
    _cc_transcript(tdir, "backfil2-0000-0000-0000-000000000000")
    rows = run_backfill(str(repo), str(out), as_of="2026-07-21",
                        claude_home=str(home))
    assert [r.outcome for r in rows] == ["packed", "packed"]
    assert (out / "session-backfil1.ctx").exists()
    assert (out / "session-backfil2.ctx").exists()
    # journal rows carry the archive flag
    journal = (out / "checkpoints.jsonl").read_text(encoding="utf-8")
    assert all(json.loads(l).get("archive") is True
               for l in journal.splitlines() if l.strip())
    # second sweep: nothing left
    assert run_backfill(str(repo), str(out), as_of="2026-07-21",
                        claude_home=str(home)) == []


def test_backfill_never_touches_latest_gist_or_default_session(tmp_path):
    repo, home, tdir, out = _setup(tmp_path)
    live = _cc_transcript(tdir, "livesess-0000-0000-0000-000000000000",
                          text="Live work. Never skip the review gate.")
    run_checkpoint(str(live), str(out), as_of="2026-07-21")  # the live pack
    latest = (out / "latest-gist.md").read_bytes()
    _cc_transcript(tdir, "oldsess1-0000-0000-0000-000000000000")
    rows = run_backfill(str(repo), str(out), as_of="2026-07-21",
                        claude_home=str(home))
    assert [r.outcome for r in rows] == ["packed"]
    # a Jul-15-style backfill must never become "latest" on Jul-21
    assert (out / "latest-gist.md").read_bytes() == latest
    sid, _ = resolve_session(str(out))
    assert sid == "livesess"
    # ... but the backfilled session's own artifacts exist
    assert (out / "session-oldsess1.ctx").exists()
    assert (out / "session-oldsess1-gist.md").exists()


def test_backfill_hollow_transcript_reported_not_fatal(tmp_path):
    repo, home, tdir, out = _setup(tmp_path)
    # valid Codex format, nothing normalizable: skipped, loudly
    telemetry = [{"timestamp": "2026-07-20T10:00:00Z", "type": "event_msg",
                  "payload": {"type": "token_count", "info": {}}}] * 25
    hollow = tdir / "hollow11-0000-0000-0000-000000000000.jsonl"
    hollow.write_text("\n".join(json.dumps(r) for r in telemetry) + "\n",
                      encoding="utf-8")
    when = time.time() + OLD
    os.utime(hollow, (when, when))
    _cc_transcript(tdir, "goodsess-0000-0000-0000-000000000000")
    rows = run_backfill(str(repo), str(out), as_of="2026-07-21",
                        claude_home=str(home))
    outcomes = {r.session[:8]: r.outcome for r in rows}
    assert outcomes["hollow11"] == "skipped_hollow"
    assert outcomes["goodsess"] == "packed"     # the sweep continued


def test_worktree_local_ledger_flag(tmp_path):
    repo, home, tdir, out = _setup(tmp_path)
    (repo / ".git").write_text("gitdir: ../main/.git/worktrees/x\n",
                               encoding="utf-8")
    cov = capture_coverage(str(repo), str(out), claude_home=str(home))
    assert cov.worktree_local_ledger


def test_cli_backfill_dry_run_then_real(tmp_path, monkeypatch, capsys):
    repo, home, tdir, out = _setup(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    _cc_transcript(tdir, "clisess1-0000-0000-0000-000000000000")
    rc = main(["backfill", "--project-dir", str(repo), "--out", str(out),
               "--dry-run", "--as-of", "2026-07-21"])
    assert rc == 0
    assert "planned" in capsys.readouterr().out
    assert not (out / "session-clisess1.ctx").exists()
    rc = main(["backfill", "--project-dir", str(repo), "--out", str(out),
               "--as-of", "2026-07-21"])
    assert rc == 0
    assert (out / "session-clisess1.ctx").exists()
    assert "latest-gist untouched" in capsys.readouterr().out


def test_session_start_hook_injects_gap_warning(tmp_path, monkeypatch,
                                                capsys):
    import io
    repo, home, tdir, out = _setup(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    _cc_transcript(tdir, "gonesess-0000-0000-0000-000000000000")
    payload = json.dumps({"cwd": str(repo),
                          "session_id": "newsess1-0000"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    rc = main(["hook", "session-start", "--out", str(out)])
    assert rc == 0
    stdout = capsys.readouterr().out
    assert "[ctx capture gap]" in stdout
    assert "gonesess" in stdout


def test_resolve_session_skips_archive_tail(tmp_path):
    out = tmp_path / "ctx"
    out.mkdir()
    (out / "session-livesess.ctx").write_text("CTX/1.1\n", encoding="utf-8")
    (out / "session-archsess.ctx").write_text("CTX/1.1\n", encoding="utf-8")
    rows = [{"session": "livesess-1", "turns": 5},
            {"session": "archsess-1", "turns": 3, "archive": True}]
    (out / "checkpoints.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert resolve_session(str(out))[0] == "livesess"
    # all-archive journal: fall back to the tail rather than nothing
    (out / "checkpoints.jsonl").write_text(
        json.dumps({"session": "archsess-1", "archive": True}) + "\n",
        encoding="utf-8")
    assert resolve_session(str(out))[0] == "archsess"
