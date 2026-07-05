"""rank/v1 gist trim is globally salience-ordered, not section-ordered.

Dogfood evidence (KP_SDLC ca35891c): section-ordered trimming evicted
23 real identifiers while keeping six junk decision lines. Under the
fold, a junk inferred decision (2.4 × 0.5 = 1.2) ranks below a git_sha
literal (1.8) — budget pressure must evict the junk first, wherever it
sits in the layout.
"""

import json

import ctxpack.agent.checkpoint as cp
from ctxpack.agent.transcript_parser import decision_marker, parse_transcript
from ctxpack.core import rank


def _entry(etype, content, ts="2026-07-05T09:00:00Z"):
    return {"type": etype, "sessionId": "xsec1234-session", "timestamp": ts,
            "isSidechain": False, "isMeta": False,
            "message": {"role": etype, "content": content}}


def test_junk_decision_evicts_before_identifier(tmp_path, monkeypatch):
    entries = [_entry("assistant", [{"type": "text", "text":
        "Decision: gate merges on the adversarial review because "
        "self-report cannot be trusted.\n"
        "We chose sqlite for the scratch queue.\n"
        "Landed as commit `deadbeef1234`."}])]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries),
                    encoding="utf-8")
    parsed = parse_transcript(str(path))

    def _field(e, key):
        return next((f.value for f in e.fields if f.key == key), "")

    ranks = {}
    for e in parsed.corpus.entities:
        fid = _field(e, "FACT-ID")
        if fid:
            ranks[fid] = rank.prior_for(
                e.name.rsplit("-", 1)[0], basis=_field(e, "BASIS"),
                marker=decision_marker(_field(e, "DECISION")),
                literal_kind=_field(e, "KIND"))

    full = cp.build_gist(parsed, ranks=ranks)
    assert "sqlite" in full and "deadbeef1234" in full

    # Force exactly enough pressure to evict one fact
    monkeypatch.setattr(cp, "GIST_BPE_BUDGET", cp._count_bpe(full) - 1)
    trimmed = cp.build_gist(parsed, ranks=ranks)
    assert "deadbeef1234" in trimmed          # identifier survives
    assert "gate merges" in trimmed           # marker decision survives
    assert "sqlite" not in trimmed            # inferred junk goes first
