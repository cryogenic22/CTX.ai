"""Checkpoint engine — pack-on-compact artifacts and determinism."""

import hashlib
import json
import os

import pytest

from ctxpack.agent.checkpoint import (
    GIST_BPE_BUDGET, build_gist, read_latest_gist, run_checkpoint,
)
from ctxpack.agent.transcript_parser import parse_transcript


def _entry(etype, content, ts="2026-07-03T10:00:00Z"):
    return {"type": etype, "sessionId": "feedbeef-session", "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


@pytest.fixture
def transcript(tmp_path):
    entries = [
        _entry("user", "Fix the retry bug. Do not touch the auth service."),
        _entry("assistant", [
            {"type": "text",
             "text": "Decision: use exponential backoff with base 750ms."},
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "src/retry.py"}},
        ]),
        _entry("assistant", [
            {"type": "text",
             "text": "Decision: raise the backoff base to 900ms after the "
                     "burst test."},
        ]),
    ]
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return str(path)


def test_checkpoint_writes_artifacts(transcript, tmp_path):
    out = str(tmp_path / "ctx")
    result = run_checkpoint(transcript, out, as_of="2026-07-03")
    assert os.path.exists(result.ctx_path)
    assert os.path.exists(result.gist_path)
    assert os.path.exists(os.path.join(out, "latest-gist.md"))
    journal = os.path.join(out, "checkpoints.jsonl")
    assert os.path.exists(journal)
    entry = json.loads(open(journal, encoding="utf-8").readline())
    assert entry["session"] == "feedbeef-session"
    assert entry["sha256"] == result.ledger_sha256


def test_checkpoint_is_deterministic(transcript, tmp_path):
    r1 = run_checkpoint(transcript, str(tmp_path / "a"), as_of="2026-07-03")
    r2 = run_checkpoint(transcript, str(tmp_path / "b"), as_of="2026-07-03")
    assert r1.ledger_sha256 == r2.ledger_sha256
    # sha256 recorded matches the bytes on disk
    blob = open(r1.ctx_path, encoding="utf-8", newline="").read()
    assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == r1.ledger_sha256


def test_gist_contains_constraints_and_decisions(transcript, tmp_path):
    out = str(tmp_path / "ctx")
    run_checkpoint(transcript, out, as_of="2026-07-03")
    gist = read_latest_gist(out)
    assert "Do not touch the auth service" in gist
    assert "backoff" in gist.lower()
    assert "(turn " in gist  # provenance visible


def test_gist_respects_budget(transcript):
    parsed = parse_transcript(transcript)
    gist = build_gist(parsed)
    from ctxpack.benchmarks.metrics.cost import count_bpe_tokens
    assert count_bpe_tokens(gist, model="claude") <= GIST_BPE_BUDGET


def test_read_latest_gist_missing_dir(tmp_path):
    assert read_latest_gist(str(tmp_path / "nope")) == ""


def test_rerun_appends_journal(transcript, tmp_path):
    out = str(tmp_path / "ctx")
    run_checkpoint(transcript, out, as_of="2026-07-03")
    run_checkpoint(transcript, out, as_of="2026-07-03")
    journal = os.path.join(out, "checkpoints.jsonl")
    lines = open(journal, encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 2  # append-only, never overwritten
