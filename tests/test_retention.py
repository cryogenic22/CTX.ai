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
