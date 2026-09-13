"""PF-15 retention/deletion safety (TM-15-bound; TC-18/TC-19).

Green-field unit: every test here is red on the parent commit because
the module and CLI command do not exist there; tests whose docstrings
say *forward guard* bound the new behavior (there is no prior behavior
to pin)."""

import json
import os

import pytest

from ctxpack.agent.retention import (
    ERR_JOURNAL_DEGRADED,
    ERR_NO_JOURNAL,
    ERR_PLAN_MISMATCH,
    ERR_ROOT_INVALID,
    ERR_ROOT_LINK,
    RETENTION_LOG,
    SKIP_AMBIGUOUS,
    SKIP_LINK,
    SKIP_ORPHAN,
    SKIP_REASONS,
    UPSTREAM_NOTE,
    RetentionError,
    _unsafe_reason,
    apply_retention,
    plan_retention,
)
from ctxpack.cli.main import main

S1 = "aaaaaaaa-0000-0000-0000-000000000001"   # oldest
S2 = "bbbbbbbb-0000-0000-0000-000000000002"
S3 = "cccccccc-0000-0000-0000-000000000003"   # newest


def _ledger(tmp_path, sessions=(S1, S2, S3)):
    out = tmp_path / "ctx"
    out.mkdir(exist_ok=True)
    with open(out / "checkpoints.jsonl", "w", encoding="utf-8") as f:
        for sid in sessions:
            f.write(json.dumps({"ts": "2026-08-22T00:00:00+00:00",
                                "session": sid, "turns": 1}) + "\n")
    for sid in sessions:
        p = sid[:8]
        (out / f"session-{p}.ctx").write_text(f"ctx {p}", encoding="utf-8")
        (out / f"session-{p}-gist.md").write_text(f"gist {p}",
                                                  encoding="utf-8")
    # protected surface — must be invisible to retention's vocabulary
    (out / "latest-gist.md").write_text("latest", encoding="utf-8")
    (out / "project-gist.md").write_text("project", encoding="utf-8")
    (out / "events.jsonl").write_text("", encoding="utf-8")
    (out / "injections.jsonl").write_text("", encoding="utf-8")
    (out / "ratifications.jsonl.quarantine-1").write_text(
        "quarantined", encoding="utf-8")
    return out


def _make_dir_link(link, target):
    """Symlink if permitted, else a Windows junction (no privilege
    needed), else skip the test — TC-18 needs a real reparse point."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    except Exception:
        pytest.skip("cannot create symlink or junction on this host")


# ── plan scope and determinism ──

def test_plan_keeps_last_n_and_touches_only_session_artifacts(tmp_path):
    """Forward guard: keep-window = last N by journal order; only the
    oldest session's two artifacts are candidates; the protected
    surface never enters the plan in any role."""
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=2)
    assert sorted(e.path for e in plan.delete) == [
        "session-aaaaaaaa-gist.md", "session-aaaaaaaa.ctx"]
    assert plan.kept_sessions == [S2, S3]
    named = {e.path for e in plan.delete} | {p for p, _ in plan.skipped}
    for protected in ("latest-gist.md", "project-gist.md", "events.jsonl",
                      "checkpoints.jsonl", "injections.jsonl",
                      "ratifications.jsonl.quarantine-1"):
        assert protected not in named


def test_plan_is_deterministic(tmp_path):
    """Forward guard: same ledger bytes, same plan hash — twice."""
    out = _ledger(tmp_path)
    a, b = plan_retention(str(out), keep=1), plan_retention(str(out), keep=1)
    assert a.plan_hash == b.plan_hash
    assert [e.path for e in a.delete] == [e.path for e in b.delete]


def test_keep_at_least_session_count_plans_nothing(tmp_path):
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=10)
    assert plan.delete == []
    result = apply_retention(str(out), 10, plan.plan_hash)
    assert result.deleted == [] and result.receipt_written


# ── fail-closed ordering (a destructive op never guesses) ──

def test_plan_refuses_without_journal(tmp_path):
    """Can-fail: no checkpoints.jsonl means no trustworthy ordering —
    refuse, never fall back to mtime or filenames."""
    out = tmp_path / "ctx"
    out.mkdir()
    (out / "session-aaaaaaaa.ctx").write_text("x", encoding="utf-8")
    with pytest.raises(RetentionError) as err:
        plan_retention(str(out), keep=1)
    assert err.value.code == ERR_NO_JOURNAL


def test_plan_refuses_on_malformed_journal_row(tmp_path):
    """Can-fail: one undecodable/garbage row degrades the WHOLE journal
    for deletion purposes (TM-3 discipline) and nothing is planned."""
    out = _ledger(tmp_path)
    with open(out / "checkpoints.jsonl", "ab") as f:
        f.write(b"{not json \xff\n")
    with pytest.raises(RetentionError) as err:
        plan_retention(str(out), keep=1)
    assert err.value.code == ERR_JOURNAL_DEGRADED
    assert (out / "session-aaaaaaaa.ctx").exists()


def test_invalid_keep_refuses(tmp_path):
    out = _ledger(tmp_path)
    for bad in (0, -3):
        with pytest.raises(RetentionError):
            plan_retention(str(out), keep=bad)


# ── unattributable artifacts are never deleted ──

def test_orphan_artifact_is_reported_never_deleted(tmp_path):
    """Can-fail: a session file no journal row claims has unknown
    provenance — skip + report through plan AND apply."""
    out = _ledger(tmp_path)
    orphan = out / "session-ffffffff.ctx"
    orphan.write_text("who wrote me?", encoding="utf-8")
    plan = plan_retention(str(out), keep=1)
    assert ("session-ffffffff.ctx", SKIP_ORPHAN) in plan.skipped
    assert "session-ffffffff.ctx" not in {e.path for e in plan.delete}
    apply_retention(str(out), 1, plan.plan_hash)
    assert orphan.exists()


def test_ambiguous_prefix_is_reported_never_deleted(tmp_path):
    """Can-fail: two full ids sharing an 8-char prefix cannot be told
    apart at the file layer — the file is skipped even though one of
    the ids is outside the keep-window."""
    d1 = "dddddddd-1111-0000-0000-000000000001"     # old
    d2 = "dddddddd-2222-0000-0000-000000000002"     # newest, kept
    out = _ledger(tmp_path, sessions=(d1, S1, d2))
    plan = plan_retention(str(out), keep=1)
    assert ("session-dddddddd.ctx", SKIP_AMBIGUOUS) in plan.skipped
    assert {e.path for e in plan.delete} == {
        "session-aaaaaaaa.ctx", "session-aaaaaaaa-gist.md"}
    apply_retention(str(out), 1, plan.plan_hash)
    assert (out / "session-dddddddd.ctx").exists()


# ── TC-18: links/junctions never followed, never deleted ──

def test_tc18_junction_in_ledger_is_reported_and_untouched(tmp_path):
    """TC-18 (TM-15): a junction/symlink inside the ledger named like a
    deletable session artifact and pointing OUTSIDE it is reported and
    left untouched by plan AND apply; the outside target survives."""
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "canary.txt"
    canary.write_text("do not delete", encoding="utf-8")
    out = _ledger(tmp_path)
    link = out / "session-aaaaaaaa.ctx"
    link.unlink()                       # replace the real artifact
    _make_dir_link(link, outside)

    plan = plan_retention(str(out), keep=1)
    assert ("session-aaaaaaaa.ctx", SKIP_LINK) in plan.skipped
    assert "session-aaaaaaaa.ctx" not in {e.path for e in plan.delete}
    apply_retention(str(out), 1, plan.plan_hash)
    assert os.path.lexists(link)        # the link itself survives too
    assert canary.read_text(encoding="utf-8") == "do not delete"


def test_unlink_guard_refuses_link_as_last_line(tmp_path):
    """Can-fail (defense in depth): the shared unsafe-path guard —
    re-run immediately before every os.remove — refuses a reparse
    point even if a plan somehow carried one."""
    outside = tmp_path / "outside2"
    outside.mkdir()
    out = _ledger(tmp_path)
    link = out / "session-zzzzzzzz.ctx"
    _make_dir_link(link, outside)
    assert _unsafe_reason(str(link), str(out)) == SKIP_LINK


# ── Finding 2 (2026-08-23): the ledger ROOT itself is never a link ──

def test_f2_linked_ledger_root_is_refused_and_target_preserved(tmp_path):
    """Finding 2 (P1): a ledger root that is a junction/symlink is
    refused BEFORE the journal is read — plan and apply through the
    link both abort and the link target's artifacts survive untouched.
    RED on 5a0d96c: the reviewer's junction probe deleted the target's
    old session artifact through a linked root."""
    real = _ledger(tmp_path)
    link = tmp_path / "ctx-link"
    _make_dir_link(link, real)
    before = sorted(os.listdir(real))
    with pytest.raises(RetentionError) as err:
        plan_retention(str(link), keep=1)
    assert err.value.code == ERR_ROOT_LINK
    with pytest.raises(RetentionError) as err2:
        apply_retention(str(link), 1, "0" * 64)
    assert err2.value.code == ERR_ROOT_LINK
    assert sorted(os.listdir(real)) == before      # target intact
    assert plan_retention(str(real), keep=1).delete   # real root works


def test_f2_missing_or_nondir_root_is_refused(tmp_path):
    """Finding 2 companion: a root that is absent or a plain file is
    `ledger_root_invalid` — never treated as an empty ledger."""
    with pytest.raises(RetentionError) as err:
        plan_retention(str(tmp_path / "nowhere"), keep=1)
    assert err.value.code == ERR_ROOT_INVALID
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(RetentionError) as err2:
        plan_retention(str(f), keep=1)
    assert err2.value.code == ERR_ROOT_INVALID


def test_f2_root_rechecked_immediately_before_each_unlink(
        tmp_path, monkeypatch):
    """Finding 2 acceptance (b), loop wiring: a root that turns bad
    AFTER apply's replan check stops every remaining deletion with the
    root reason. The guard is flipped by monkeypatch because the
    public API cannot race the filesystem deterministically."""
    import ctxpack.agent.retention as rmod

    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=1)
    assert len(plan.delete) >= 2
    real = rmod._root_reason
    calls = {"n": 0}

    def flip(root):
        calls["n"] += 1
        # call 1 = plan-time check inside apply's replan; call 2 = the
        # first unlink's recheck; every later unlink sees a bad root
        return real(root) if calls["n"] <= 2 else rmod.ERR_ROOT_LINK

    monkeypatch.setattr(rmod, "_root_reason", flip)
    result = apply_retention(str(out), 1, plan.plan_hash)
    assert len(result.deleted) == 1
    assert len(result.skipped) == len(plan.delete) - 1
    assert all(r == ERR_ROOT_LINK for _p, r in result.skipped)


# ── TC-19: TOCTOU between plan and apply ──

def test_tc19_file_added_between_plan_and_apply_aborts(tmp_path):
    """TC-19 (TM-15): a session checkpointed after the plan shifts the
    keep-window; apply against the stale hash aborts controlled and
    deletes NOTHING."""
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=2)
    before = sorted(os.listdir(out))
    new_sid = "eeeeeeee-0000-0000-0000-000000000009"
    with open(out / "checkpoints.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-08-22T01:00:00+00:00",
                            "session": new_sid}) + "\n")
    (out / "session-eeeeeeee.ctx").write_text("new", encoding="utf-8")
    with pytest.raises(RetentionError) as err:
        apply_retention(str(out), 2, plan.plan_hash)
    assert err.value.code == ERR_PLAN_MISMATCH
    assert sorted(os.listdir(out)) == sorted(before + [
        "session-eeeeeeee.ctx"])        # nothing deleted


def test_tc19_content_swap_between_plan_and_apply_aborts(tmp_path):
    """TC-19 variant: same file SET but swapped bytes in a candidate —
    the plan hash covers content sha256, so the confirmation no longer
    describes what would be destroyed; abort, delete nothing."""
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=2)
    (out / "session-aaaaaaaa.ctx").write_text("swapped!", encoding="utf-8")
    with pytest.raises(RetentionError) as err:
        apply_retention(str(out), 2, plan.plan_hash)
    assert err.value.code == ERR_PLAN_MISMATCH
    assert (out / "session-aaaaaaaa.ctx").read_text(
        encoding="utf-8") == "swapped!"


def test_f3_orphan_added_between_plan_and_apply_aborts(tmp_path):
    """Finding 3 (P1): an orphan appearing after the plan leaves the
    DELETE set unchanged but changes the plan state — the v2 hash
    binds skipped candidate-shaped rows, so apply aborts and deletes
    nothing. RED on 5a0d96c: ORPHAN_DRIFT_HASH_UNCHANGED=True and the
    old candidates were deleted anyway."""
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=2)
    (out / "session-ffffffff.ctx").write_text("orphan", encoding="utf-8")
    with pytest.raises(RetentionError) as err:
        apply_retention(str(out), 2, plan.plan_hash)
    assert err.value.code == ERR_PLAN_MISMATCH
    assert (out / "session-aaaaaaaa.ctx").exists()


def test_f3_link_appearing_among_skipped_rows_aborts(tmp_path):
    """Finding 3: a reparse point appearing after the plan (a skipped
    row, not a delete row) also invalidates the confirmation."""
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=2)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    _make_dir_link(out / "session-zzzzzzzz.ctx", outside)
    with pytest.raises(RetentionError) as err:
        apply_retention(str(out), 2, plan.plan_hash)
    assert err.value.code == ERR_PLAN_MISMATCH
    assert (out / "session-aaaaaaaa.ctx").exists()


def test_f3_ledger_a_hash_cannot_authorize_ledger_b(tmp_path):
    """Finding 3 acceptance (c): two ledgers with byte-identical
    content produce DIFFERENT plan hashes (ledger identity is bound),
    so a confirmation minted against A never applies to B. RED on
    5a0d96c: identical content hashed identically across ledgers."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ledger_a = _ledger(tmp_path / "a")
    ledger_b = _ledger(tmp_path / "b")
    plan_a = plan_retention(str(ledger_a), keep=2)
    plan_b = plan_retention(str(ledger_b), keep=2)
    assert plan_a.plan_hash != plan_b.plan_hash
    with pytest.raises(RetentionError) as err:
        apply_retention(str(ledger_b), 2, plan_a.plan_hash)
    assert err.value.code == ERR_PLAN_MISMATCH
    assert (ledger_b / "session-aaaaaaaa.ctx").exists()


def test_rf5_kept_artifact_drift_between_plan_and_apply_aborts(tmp_path):
    """RF5 (Codex Finding 5, P2): a KEPT session's .ctx replaced,
    removed, or a new kept artifact added after the plan invalidates the
    confirmation — the hash binds every candidate by disposition, so the
    "WHOLE plan" contract holds for kept artifacts, not just deletions.
    RED on 5a0d96c/b36e8e0: kept artifacts were skipped before the hash,
    so kept-drift left plan_hash unchanged and apply proceeded."""
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=2)      # S2,S3 kept; S1 deleted
    assert plan.kept, "kept artifacts must be recorded in the plan"
    # replace a KEPT artifact's bytes after planning
    kept_ctx = out / "session-cccccccc.ctx"      # S3, kept
    assert kept_ctx.exists()
    kept_ctx.write_text("rewritten kept content", encoding="utf-8")
    with pytest.raises(RetentionError) as err:
        apply_retention(str(out), 2, plan.plan_hash)
    assert err.value.code == ERR_PLAN_MISMATCH
    assert (out / "session-aaaaaaaa.ctx").exists()   # nothing deleted


def test_rf5_kept_artifact_removed_aborts(tmp_path):
    """RF5: removing a kept artifact between plan and apply also
    invalidates (the kept set no longer matches)."""
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=2)
    (out / "session-bbbbbbbb-gist.md").unlink()   # a kept artifact
    with pytest.raises(RetentionError) as err:
        apply_retention(str(out), 2, plan.plan_hash)
    assert err.value.code == ERR_PLAN_MISMATCH
    assert (out / "session-aaaaaaaa.ctx").exists()


def test_rf5_kept_artifacts_recorded_with_content_digest(tmp_path):
    """RF5: the plan records kept artifacts with path+size+sha, and the
    clean apply (no drift) still succeeds and deletes only the delete
    set."""
    out = _ledger(tmp_path)
    plan = plan_retention(str(out), keep=2)
    kept_paths = {e.path for e in plan.kept}
    assert "session-bbbbbbbb.ctx" in kept_paths
    assert "session-cccccccc.ctx" in kept_paths
    assert all(len(e.sha256) == 64 for e in plan.kept)
    result = apply_retention(str(out), 2, plan.plan_hash)   # no drift
    assert result.deleted == ["session-aaaaaaaa-gist.md",
                              "session-aaaaaaaa.ctx"]
    assert (out / "session-bbbbbbbb.ctx").exists()


def test_apply_with_wrong_or_empty_hash_deletes_nothing(tmp_path):
    out = _ledger(tmp_path)
    for bad in ("0" * 64, ""):
        with pytest.raises(RetentionError):
            apply_retention(str(out), 2, bad)
    assert (out / "session-aaaaaaaa.ctx").exists()


# ── receipts ──

def test_apply_writes_receipt_after_deletion_with_stable_codes(tmp_path):
    """Forward guard: the receipt row carries ledger-relative paths and
    fixed reason codes only — no absolute paths, no exception text."""
    out = _ledger(tmp_path)
    orphan = out / "session-ffffffff.ctx"
    orphan.write_text("orphan", encoding="utf-8")
    plan = plan_retention(str(out), keep=2)
    result = apply_retention(str(out), 2, plan.plan_hash)
    assert result.receipt_written
    raw = (out / RETENTION_LOG).read_text(encoding="utf-8")
    row = json.loads(raw.splitlines()[-1])
    assert row["schema"] == "ctx-retention/v1"
    assert row["plan_hash"] == plan.plan_hash
    assert row["deleted"] == ["session-aaaaaaaa-gist.md",
                              "session-aaaaaaaa.ctx"]
    for skip in row["skipped"]:
        assert skip["reason"] in SKIP_REASONS
    assert str(tmp_path) not in raw     # never an absolute path


# ── CLI: explicit confirm, honest reporting ──

def test_cli_plan_apply_roundtrip_and_upstream_honesty(tmp_path, capsys):
    """Forward guard: plan prints the hash + the upstream non-claim;
    apply with that hash deletes the candidates; a SECOND apply with
    the same hash refuses (the world changed) — and --apply without
    --plan-hash never runs at all."""
    out = _ledger(tmp_path)
    assert main(["retention", "--keep", "2", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert UPSTREAM_NOTE in printed
    plan_hash = next(line.split()[-1] for line in printed.splitlines()
                     if line.startswith("plan sha256:"))

    assert main(["retention", "--keep", "2", "--out", str(out),
                 "--apply"]) == 2      # no hash, no deletion
    capsys.readouterr()
    assert (out / "session-aaaaaaaa.ctx").exists()

    assert main(["retention", "--keep", "2", "--out", str(out),
                 "--apply", "--plan-hash", plan_hash]) == 0
    printed = capsys.readouterr().out
    assert UPSTREAM_NOTE in printed
    assert not (out / "session-aaaaaaaa.ctx").exists()
    assert not (out / "session-aaaaaaaa-gist.md").exists()
    assert (out / "session-bbbbbbbb.ctx").exists()
    assert (out / "latest-gist.md").exists()

    assert main(["retention", "--keep", "2", "--out", str(out),
                 "--apply", "--plan-hash", plan_hash]) == 1
    assert "refused (plan_mismatch)" in capsys.readouterr().err


def test_cli_refusal_is_controlled_nonzero_not_traceback(tmp_path, capsys):
    """TC-19's 'controlled nonzero': a refusal is exit 1 + a stderr
    line, never an uncaught exception."""
    out = tmp_path / "ctx"
    out.mkdir()
    assert main(["retention", "--keep", "1", "--out", str(out)]) == 1
    assert "refused (no_journal)" in capsys.readouterr().err
