"""Trust self-reporting (field reports setu 07-21 / OntoWiz 07-25):
read-path classification, lint armed-vs-silent coverage, checkpoint
receipts, startup-injection telemetry. All fixtures synthetic."""

import io
import json

from ctxpack.agent.checkpoint import _claude_project_dir_name, run_checkpoint
from ctxpack.agent.injection_log import (
    INJECTION_LOG,
    injection_stats,
    record_injection,
)
from ctxpack.agent.scorecard import build_scorecard
from ctxpack.agent.session_reader import classify_read_path, session_stats
from ctxpack.cli.main import main


def _transcript(tmp_path, sid, name="s.jsonl", extra_blocks=()):
    rows = [{"type": "user", "sessionId": sid, "uuid": "u1",
             "message": {"content": "Ship it. Do not skip the review gate."}},
            {"type": "assistant", "sessionId": sid, "uuid": "u2",
             "message": {"content": [
                 {"type": "text", "text":
                  "Decision: retry with backoff because the cap is "
                  "40 req/min."},
                 *extra_blocks]}}]
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return str(path)


# ── read-path classification ──

def test_classify_read_path_separates_zero_recall_from_no_telemetry():
    rows = [
        {"stats": {"ledger_reads": 3, "transcript_greps": 0}},   # queried
        {"stats": {"ledger_reads": 0, "transcript_greps": 0}},   # push only
        {"stats": {"ledger_reads": 0, "transcript_greps": 4}},   # grepped raw
        {"stats": {"ledger_reads": 2, "transcript_greps": 1}},   # both
        {"stats": {"turns": 9}},                                 # pre-feature
        {},                                                       # no stats
    ]
    out = classify_read_path(rows)
    assert out["sessions_explicit_recall"] == 2
    assert out["sessions_zero_recall"] == 2
    assert out["sessions_no_telemetry"] == 2
    assert out["sessions_transcript_fallback"] == 2
    # unmeasured sessions stay OUT of the denominator: not measured is
    # not the same as not used
    assert out["explicit_recall_rate"] == 0.5


def test_zero_recall_splits_by_delivery_receipt():
    """"Zero recall" alone cannot be read as "injection-only".

    Two sessions never queried; only one was handed a gist. Without the
    join they are the same number, and the difference — never queried vs
    never given anything — is the whole finding.
    """
    rows = [
        {"session": "aaaaaaaa11", "stats": {"ledger_reads": 0,
                                            "transcript_greps": 0}},
        {"session": "bbbbbbbb22", "stats": {"ledger_reads": 0,
                                            "transcript_greps": 0}},
        {"session": "cccccccc33", "stats": {"ledger_reads": 5,
                                            "transcript_greps": 0}},
    ]
    out = classify_read_path(rows, {"aaaaaaaa"})
    assert out["sessions_zero_recall"] == 2
    assert out["sessions_zero_recall_with_emission"] == 1
    assert out["sessions_zero_recall_no_emission"] == 1
    assert out["sessions_zero_recall_emission_unmeasured"] == 0


def test_absent_injection_log_reports_unmeasured_not_no_delivery():
    """The absent-vs-zero rule, applied to the join itself."""
    rows = [{"session": "aaaaaaaa11", "stats": {"ledger_reads": 0,
                                                "transcript_greps": 0}}]
    out = classify_read_path(rows, None)
    assert out["sessions_zero_recall_emission_unmeasured"] == 1
    assert out["sessions_zero_recall_no_emission"] == 0
    assert out["sessions_zero_recall_with_emission"] == 0


def test_emitted_sessions_absent_log_is_none_not_empty_set():
    from ctxpack.agent.injection_log import emitted_sessions
    assert emitted_sessions("no/such/dir") is None


def test_dashboard_reports_emission_and_never_claims_use():
    """Receipts prove bytes reached the hook's stdout. The page may not
    upgrade that into delivery, consumption, use or value anywhere."""
    from ctxpack.agent.dashboard import render_markdown

    md = render_markdown({
        "cohort": {"read_path": {"sessions_explicit_recall": 0,
                                 "sessions_zero_recall": 3,
                                 "sessions_zero_recall_with_emission": 3,
                                 "sessions_no_telemetry": 0,
                                 "sessions_transcript_fallback": 0,
                                 "explicit_recall_rate": 0.0},
                   "startup_injection": {"attempted": 3, "injected": 3,
                                         "empty": 0, "failed": 0,
                                         "gap_warnings": 0}},
        "repos": [],
    })
    assert "Emission is not use." in md
    assert "being consumed" not in md
    assert "of which a gist was emitted" in md
    # the page must not upgrade stdout emission into agent delivery
    assert "delivered" not in md.lower()


def test_classify_read_path_empty_ledger_rate_is_none():
    assert classify_read_path([])["explicit_recall_rate"] is None
    assert classify_read_path(
        [{"stats": {"turns": 1}}])["explicit_recall_rate"] is None


def test_zero_recall_session_is_visible_where_the_rate_is_blind(tmp_path):
    """The regression this whole slice exists for: a session that never
    consulted the ledger used to be indistinguishable from no data."""
    out = tmp_path / "ctx"
    run_checkpoint(_transcript(tmp_path, "quiet111-0000"), str(out),
                   as_of="2026-07-25")
    stats = session_stats(str(out))["read_path"]
    assert stats["raw_fallback_rate"] is None        # still blind, as before
    assert stats["sessions_zero_recall"] == 1        # ... but now legible
    assert stats["sessions_no_telemetry"] == 0
    assert stats["explicit_recall_rate"] == 0.0


def test_scorecard_aggregates_session_buckets(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude" / "ctx").mkdir(parents=True)
    out = repo / ".claude" / "ctx"
    run_checkpoint(_transcript(tmp_path, "cohort11-0000"), str(out),
                   as_of="2026-07-25")
    card = build_scorecard([str(repo)])
    rp = card["cohort"]["read_path"]
    assert rp["sessions_zero_recall"] == 1
    assert rp["explicit_recall_rate"] == 0.0


# ── lint armed-vs-silent ──

def _lint(tmp_path, path):
    from ctxpack.agent.conflict_lint import lint_decisions
    from ctxpack.agent.transcript_parser import parse_transcript

    out = tmp_path / "ctx"
    out.mkdir(exist_ok=True)
    parsed = parse_transcript(path)
    meta: dict = {}
    rows = lint_decisions(parsed.corpus.entities, str(out),
                          parsed.session_id, meta=meta)
    return rows, meta


def _multi_turn(tmp_path, sid, name="multi.jsonl"):
    """Constraint stated BETWEEN two decisions.

    The first decision predates the constraint, so that pair is
    turn-gated (same-turn is exposition, later-turn would be a
    retroactive conflict from future text). The second decision sees it.
    """
    rows = [
        {"type": "user", "sessionId": sid, "uuid": "u1",
         "message": {"content": "Start the migration work."}},
        {"type": "assistant", "sessionId": sid, "uuid": "u2",
         "message": {"content": [{"type": "text", "text":
                                  "Decision: use backoff because the "
                                  "cap is 40 req/min."}]}},
        {"type": "user", "sessionId": sid, "uuid": "u3",
         "message": {"content": "Do not widen the migration scope."}},
        {"type": "assistant", "sessionId": sid, "uuid": "u4",
         "message": {"content": [{"type": "text", "text":
                                  "Decision: keep the batch size at 500 "
                                  "because throughput plateaus above it."}]}},
    ]
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    return str(path)


def test_lint_meta_reports_marginals_not_a_product(tmp_path):
    """The false identity this replaces: comparisons == D x C + P.

    It held only in a fixture where nothing was turn-gated, so the test
    encoded the same arithmetic error the gist was rendering. The honest
    denominator is two separate populations, each with its own exact
    identity.
    """
    rows, meta = _lint(tmp_path, _multi_turn(tmp_path, "gated111-0000"))
    assert rows == []                      # precision-first: silent
    assert meta["decisions_linted"] == 2   # ... but demonstrably armed
    assert meta["constraints_in_scope"] >= 1

    # every examined decision is compared against every in-scope
    # constraint, and each such pair is either counted or turn-gated
    assert (meta["constraint_comparisons"]
            + meta["constraint_pairs_turn_gated"]
            == meta["decisions_linted"] * meta["constraints_in_scope"])
    # protected subjects have no turn gate, so this one IS a product
    assert (meta["protected_comparisons"]
            == meta["decisions_linted"] * meta["protected_subjects"])
    assert (meta["comparisons"] == meta["constraint_comparisons"]
            + meta["protected_comparisons"])


def test_turn_gating_makes_the_old_product_identity_false(tmp_path):
    """The adversarial case: without this fixture the bug is invisible."""
    _, meta = _lint(tmp_path, _multi_turn(tmp_path, "gated222-0000"))
    assert meta["constraint_pairs_turn_gated"] >= 1
    old_identity = (meta["decisions_linted"] * meta["constraints_in_scope"]
                    + meta["protected_subjects"])
    assert meta["comparisons"] != old_identity


def test_row_cap_reports_decisions_actually_examined(tmp_path, monkeypatch):
    """Truncation must narrow the coverage claim, not just the row list.

    Reporting len(decisions) as linted after an early break is the same
    class of error as the product identity: a coverage claim wider than
    the work done.
    """
    from ctxpack.agent import conflict_lint

    sid = "trunc111-0000"
    rows = [
        {"type": "user", "sessionId": sid, "uuid": "u1",
         "message": {"content":
                     "Do not run the $60 full pass until cost reporting "
                     "is fixed."}},
        {"type": "assistant", "sessionId": sid, "uuid": "u2",
         "message": {"content": [{"type": "text", "text":
                                  "Decision: run the $60 full pass now "
                                  "because the board asked for numbers."}]}},
        {"type": "assistant", "sessionId": sid, "uuid": "u3",
         "message": {"content": [{"type": "text", "text":
                                  "Decision: run the $60 full pass now "
                                  "because the quarter closes Friday."}]}},
    ]
    path = tmp_path / "trunc.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")

    monkeypatch.setattr(conflict_lint, "MAX_ROWS", 1)
    out_rows, meta = _lint(tmp_path, str(path))
    assert len(out_rows) == 1
    assert meta["truncated"] is True
    assert meta["decisions_in_scope"] == 2
    assert meta["decisions_linted"] == 1        # not 2
    assert meta["decisions_linted"] < meta["decisions_in_scope"]


def test_gist_states_lint_coverage_when_clean(tmp_path):
    out = tmp_path / "ctx"
    run_checkpoint(_transcript(tmp_path, "armed111-0000"), str(out),
                   as_of="2026-07-25")
    gist = (out / "session-armed111-gist.md").read_text(encoding="utf-8")
    assert "Decision lint armed:" in gist
    assert "0 unresolved" in gist
    # the retired render claimed "N comparisons (D x C banked
    # constraints)" — false whenever a pair is turn-gated or a
    # protected subject is checked
    assert "×" not in gist and " x " not in gist
    assert "constraint pairs" in gist and "turn-gated" in gist
    row = json.loads((out / "checkpoints.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    assert row["lint_comparisons"] >= 0
    assert row["lint_decisions_linted"] == 1


def test_gist_says_failed_when_lint_crashes(tmp_path, monkeypatch):
    import ctxpack.agent.conflict_lint as cl

    def boom(*a, **k):
        raise RuntimeError("lint exploded")

    monkeypatch.setattr(cl, "lint_decisions", boom)
    out = tmp_path / "ctx"
    result = run_checkpoint(_transcript(tmp_path, "crash111-0000"), str(out),
                            as_of="2026-07-25")
    gist = (out / "session-crash111-gist.md").read_text(encoding="utf-8")
    assert "Decision lint: FAILED" in gist   # never silently reads as clean
    assert result.lint_status == "error"


# ── checkpoint receipt ──

def test_receipt_reports_new_turns_across_two_checkpoints(tmp_path):
    out = tmp_path / "ctx"
    sid = "growing1-0000"
    path = _transcript(tmp_path, sid)
    first = run_checkpoint(path, str(out), as_of="2026-07-25")
    assert first.turns_new == first.turns    # nothing banked before
    assert len(first.gist_sha256) == 64
    assert first.lint_status == "ok"

    with open(path, "a", encoding="utf-8") as f:
        for i, row in enumerate([
                {"type": "user", "sessionId": sid, "uuid": "u3",
                 "message": {"content": "Now do the second thing."}},
                {"type": "assistant", "sessionId": sid, "uuid": "u4",
                 "message": {"content": [{"type": "text", "text":
                             "Decision: split the writer because the "
                             "lock is contended."}]}}]):
            f.write(json.dumps(row) + "\n")
    second = run_checkpoint(path, str(out), as_of="2026-07-25")
    assert second.turns > first.turns
    assert second.turns_new == second.turns - first.turns
    row = json.loads((out / "checkpoints.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    assert row["turns_new"] == second.turns_new
    assert row["gist_sha256"] == second.gist_sha256


def test_cli_checkpoint_prints_receipt(tmp_path, capsys):
    out = tmp_path / "ctx"
    rc = main(["checkpoint", "--transcript",
               _transcript(tmp_path, "receipt1-0000"),
               "--out", str(out), "--as-of", "2026-07-25"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "Checkpoint receipt:" in printed
    assert "new since this session's last checkpoint" in printed
    assert "lint:     armed" in printed
    assert "sha256" in printed


# ── startup-injection telemetry ──

def test_injection_stats_absent_log_is_unmeasured_not_zero(tmp_path):
    assert injection_stats(str(tmp_path)) == {}


def test_injection_outcomes_and_hash(tmp_path):
    out = tmp_path / "ctx"
    record_injection(str(out), session_id="aaaaaaaa-1", context="hello memory")
    record_injection(str(out), session_id="bbbbbbbb-1", context="")
    record_injection(str(out), session_id="cccccccc-1", context="",
                     outcome="failed", error="LedgerError: boom")
    stats = injection_stats(str(out))
    assert stats == {**stats, "attempted": 3, "injected": 1, "empty": 1,
                     "failed": 1}
    assert stats["emit_success_rate"] == 0.333
    rows = [json.loads(x) for x in
            (out / INJECTION_LOG).read_text(encoding="utf-8").splitlines()]
    assert len(rows[0]["sha256"]) == 64
    assert rows[0]["bytes"] == len("hello memory")
    assert rows[2]["error"].startswith("LedgerError")


def test_session_start_hook_logs_what_it_injected(tmp_path, monkeypatch,
                                                  capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    (home / "projects" / _claude_project_dir_name(str(repo))).mkdir(
        parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    out = repo / ".claude" / "ctx"
    run_checkpoint(_transcript(tmp_path, "prior111-0000"), str(out),
                   as_of="2026-07-25")

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"cwd": str(repo), "session_id": "newone11-0000"})))
    assert main(["hook", "session-start", "--out", str(out)]) == 0
    emitted = json.loads(capsys.readouterr().out)["hookSpecificOutput"][
        "additionalContext"]

    stats = injection_stats(str(out))
    assert stats["attempted"] == 1 and stats["injected"] == 1
    assert stats["failed"] == 0
    # the receipt must describe the bytes the agent actually received
    import hashlib
    row = json.loads((out / INJECTION_LOG).read_text(
        encoding="utf-8").splitlines()[0])
    assert row["sha256"] == hashlib.sha256(
        emitted.encode("utf-8")).hexdigest()
    assert row["bytes"] == len(emitted.encode("utf-8"))
    assert stats["measures"] == "emitted_to_hook_stdout"


def test_a_failed_emit_is_never_recorded_as_a_successful_one(
        tmp_path, monkeypatch, capsys):
    """The receipt is written AFTER the write it attests to.

    Recording first would let a broken pipe or closed stdout be banked
    as `injected` — a receipt that can be true while the thing it
    certifies did not happen is worse than no receipt.
    """
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    (home / "projects" / _claude_project_dir_name(str(repo))).mkdir(
        parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    out = repo / ".claude" / "ctx"
    run_checkpoint(_transcript(tmp_path, "prior222-0000"), str(out),
                   as_of="2026-07-25")

    import builtins
    real_print = builtins.print

    def exploding_print(*a, **k):
        raise BrokenPipeError("stdout closed")

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"cwd": str(repo), "session_id": "brokpipe-0000"})))
    monkeypatch.setattr(builtins, "print", exploding_print)
    try:
        assert main(["hook", "session-start", "--out", str(out)]) == 0
    finally:
        monkeypatch.setattr(builtins, "print", real_print)
    capsys.readouterr()

    stats = injection_stats(str(out))
    assert stats["attempted"] == 1
    assert stats["injected"] == 0      # NOT banked as a success
    assert stats["failed"] == 1
    row = json.loads((out / INJECTION_LOG).read_text(
        encoding="utf-8").splitlines()[0])
    assert "emit failed" in row["error"]


def test_session_start_records_failure_without_breaking_the_session(
        tmp_path, monkeypatch, capsys):
    import ctxpack.agent.checkpoint as cp

    def boom(*a, **k):
        raise RuntimeError("ledger unreadable")

    monkeypatch.setattr(cp, "read_startup_context", boom)
    out = tmp_path / "ctx"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"cwd": str(tmp_path), "session_id": "brokenn1-0000"})))
    assert main(["hook", "session-start", "--out", str(out)]) == 0
    capsys.readouterr()
    stats = injection_stats(str(out))
    assert stats["attempted"] == 1 and stats["failed"] == 1
    assert stats["injected"] == 0


def test_stats_and_scorecard_surface_injection_delivery(tmp_path):
    repo = tmp_path / "repo"
    out = repo / ".claude" / "ctx"
    out.mkdir(parents=True)
    run_checkpoint(_transcript(tmp_path, "surface1-0000"), str(out),
                   as_of="2026-07-25")
    record_injection(str(out), session_id="surface1", context="a gist")
    assert session_stats(str(out))["startup_injection"]["injected"] == 1
    card = build_scorecard([str(repo)])
    assert card["cohort"]["startup_injection"]["attempted"] == 1
