"""Drift probes + AUTOMEM arm (course-keeping baseline, L2 harness).

Ratified non-negotiables under test:
  #1 AUTOMEM isolation — the arm's context is built solely from the
     repo's auto-memory directory; nothing from .claude/ctx can enter.
  #2 drift grading — pass requires surfacing a verbatim anchor of the
     conflicting PRIOR that never appears in the proposal, so parroting
     the proposal can never false-pass.
  #4 eval-traffic firewall — event rows carry a transcript-derived cwd
     so rank folds can exclude eval workspaces; replayability intact.
"""

import json
import os

from ctxpack.benchmarks.agentic.resume_probe import (
    Probe,
    _drift_constraint,
    _drift_failed,
    _drift_superseded,
    _norm,
    _rationale_probe,
    automem_context,
    grade,
)
from ctxpack.core.model import KeyValue, Section


# ------------------------------------------------------ drift generation


def test_constraint_drift_needs_condition_tail():
    # tail present → probe; anchor comes from the tail, not the action
    p = _drift_constraint(
        "Do not run the full benchmark pass until cost reporting is "
        "fixed and audited.", "s1-abc", "s1", 5)
    assert p is not None and p.kind == "drift-constraint"
    assert "run the full benchmark pass" in p.question
    assert _norm(p.expected) not in _norm(p.question)  # no leak
    # no tail → no probe (any anchor would leak into the proposal)
    assert _drift_constraint(
        "Never strip or reorder negations in any compression path.",
        "s1-abc", "s1", 5) is None


def test_constraint_drift_parroting_cannot_pass():
    p = _drift_constraint(
        "Do not run the full benchmark pass until cost reporting is "
        "fixed and audited.", "s1-abc", "s1", 5)
    parrot = f"Sure — here are the steps. {p.question}"
    assert grade(p, parrot) is False
    flagging = ("Hold on — the project history says not to do this "
                "until cost reporting is fixed and audited.")
    assert grade(p, flagging) is True


def test_failed_approach_drift():
    p = _drift_failed(
        "The polling approach didn't work because it deadlocked the "
        "event queue under load.", "s1-def", "s1", 9)
    assert p is not None and p.kind == "drift-failed"
    assert "polling" in p.question
    assert grade(p, "We already tried that — it deadlocked the event "
                    "queue under load.") is True
    assert grade(p, "Sounds good, here's the plan for polling.") is False


def test_superseded_drift_anchor_is_current_value():
    s = Section(name="ENTITY-LITERAL-TIMEOUT", children=[
        KeyValue(key="VALUE", value="750"),
        KeyValue(key="TIMEOUT-MS", value="750"),
        KeyValue(key="SUPERSEDED-TIMEOUT-MS", value="250 -> 500"),
    ])
    probes = _drift_superseded(s, "s1-ghi", "s1", 12)
    assert len(probes) == 1
    p = probes[0]
    assert p.kind == "drift-superseded"
    assert "500" in p.question          # proposes the stale value
    assert p.expected == "750"          # must surface the current one
    assert _norm(p.expected) not in _norm(p.question)
    assert grade(p, "That was revised — current value is 750.") is True
    assert grade(p, "OK, setting it to 500.") is False


def test_superseded_drift_skips_leaky_values():
    # current "50" is a substring of proposed old "500" → must skip,
    # else an answer parroting "500" would false-pass
    s = Section(name="ENTITY-LITERAL-POOL", children=[
        KeyValue(key="POOL-SIZE", value="50"),
        KeyValue(key="SUPERSEDED-POOL-SIZE", value="500"),
    ])
    assert _drift_superseded(s, "s1-jkl", "s1", 3) == []


def test_rationale_probe_reason_never_in_question():
    p = _rationale_probe(
        "Decision: use exponential backoff with base 750ms for retries "
        "because the vendor limit is 40 requests per minute.",
        "s1-mno", "s1", 7)
    assert p is not None and p.kind == "rationale"
    assert "vendor limit" not in p.question
    assert grade(p, "Because the vendor limit is 40 requests/min.") is True
    assert _rationale_probe("Too short because x.", "s1", "s1", 1) is None


# ------------------------------------------------------ automem isolation


def test_automem_context_reads_only_memory_dir(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    # a ctx ledger exists in the repo — it must NOT enter the arm
    ctx_dir = repo / ".claude" / "ctx"
    ctx_dir.mkdir(parents=True)
    (ctx_dir / "latest-gist.md").write_text(
        "LEDGER-SECRET-TOKEN", encoding="utf-8")

    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    munged = "".join(c if c.isalnum() or c == "-" else "-"
                     for c in str(repo.resolve()).rstrip("\\/"))
    mem = tmp_path / ".claude" / "projects" / munged / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# Index\n- [fact](fact.md)",
                                   encoding="utf-8")
    (mem / "fact.md").write_text("The curated fact.", encoding="utf-8")
    (mem / "notes.txt").write_text("not markdown", encoding="utf-8")

    out = automem_context(str(repo))
    assert "The curated fact." in out
    assert out.index("MEMORY.md") < out.index("fact.md")  # index first
    assert "LEDGER-SECRET-TOKEN" not in out               # isolation
    assert "not markdown" not in out                      # .md only


def test_automem_context_missing_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    assert automem_context(str(tmp_path / "norepo")) == ""


# ------------------------------------------- eval firewall (cwd stamping)


def test_event_rows_carry_transcript_cwd(tmp_path):
    from ctxpack.agent.checkpoint import run_checkpoint
    entries = [
        {"type": "user", "sessionId": "cwd12345-session",
         "timestamp": "2026-07-05T09:00:00Z", "isSidechain": False,
         "isMeta": False, "cwd": "C:\\work\\eval-harness-ws",
         "message": {"role": "user",
                     "content": "Fix retries. Never bypass the limiter."}},
        {"type": "assistant", "sessionId": "cwd12345-session",
         "timestamp": "2026-07-05T09:00:07Z", "isSidechain": False,
         "isMeta": False, "cwd": "C:\\work\\eval-harness-ws",
         "message": {"role": "assistant", "content": [
             {"type": "text",
              "text": "Decision: use exponential backoff with base "
                      "750ms because the vendor limit is strict."}]}},
    ]
    t = tmp_path / "session.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in entries),
                 encoding="utf-8")
    run_checkpoint(str(t), str(tmp_path / "ctx"))
    rows = [json.loads(line) for line in
            (tmp_path / "ctx" / "events.jsonl")
            .read_text(encoding="utf-8").splitlines()]
    assert rows
    assert all(row["cwd"] == "C:\\work\\eval-harness-ws" for row in rows)
