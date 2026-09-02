"""Capture fidelity (backlog Step 1, C1–C4).

C1 — the full admitted marker sentence is stored, not a 280-char stump
(transcript_parser stored `sentence[:280]` for DECISION/FAILED-APPROACH/
FINDING while identity was already computed on the full sentence). Storing
the full text is therefore a DISPLAY/STORAGE change that changes NO fact_id
— pinned by the golden-hash test below, which passes on the parent too. The
injected gist keeps a negation-safe preview (decisions/findings/failed-
approaches only, never constraints — a truncated constraint could sever a
trailing negation, the D2 failure at the render layer).

Red-on-parent method (board): `git stash push -- ctxpack/agent/
transcript_parser.py` (keeps checkpoint's _preview importable), run this
file → the three storage tests and the gist test go RED; `git stash pop` →
all green. The golden-hash pin and the helper guard are self-identified
below as a regression pin / forward guard (they pass on the parent)."""

import json

from ctxpack.agent.transcript_parser import parse_transcript
from ctxpack.agent.checkpoint import build_gist, _preview, _PREVIEW_CAP
from ctxpack.core import factid

# One sentence each, no internal ". " (which would split it). The DECISION
# and FINDING are marker-led (admitted up to 900 chars); the FAILED-APPROACH
# is marker-led too ("Conclusion:") so it can exceed the 300-char non-marker
# admission cap and still be classified a failed approach by its verb. Each
# places its SENTINEL token so the old `[:280]` truncation drops it.
_DECISION = (
    "Decision: use exponential backoff with base 750ms on the retry path, "
    "because the vendor rate limit is forty requests per minute and the "
    "earlier fixed 250ms delay produced cascading 429 responses under "
    "sustained parallel load, a regression we reproduced end to end by "
    "replaying the captured SENTINEL_TAIL_TOKEN production trace.")
_FAILED = (
    "Conclusion: the in-memory mock-server approach didn't work because the "
    "OS assigned overlapping ephemeral ports across parallel workers and the "
    "teardown routine never released them in time, leaving dozens of sockets "
    "stuck in TIME_WAIT for the whole run, so we dropped it for the "
    "SENTINEL_FAIL_TOKEN fixture.")
_FINDING = (
    "Verdict: the retention plan hash binds the ordered journal and the "
    "delete set but it completely omits the kept-candidate artifacts, so an "
    "accidental swap of a kept file between plan time and apply time would "
    "still pass the verification step entirely undetected, and that is exactly "
    "the SENTINEL_FIND_TOKEN gap the fix must close.")
# a long CONSTRAINT ending in a negation — the gist preview must NOT touch it
_CONSTRAINT = (
    "Constraint: no autonomous-loop work unfreezes before the deterministic "
    "CI floor exists, and paid runs, live prompt hooks and parked merges "
    "stay frozen until the reviewer approves the security preflight, because "
    "agents are never the authority on whether their own work passed and "
    "must not self-ratify.")

# Golden fact_ids — identity is content-addressed on the FULL admitted
# sentence (transcript_parser `_add`: fact=(kind,"",sentence)), which C1
# does not touch. These are frozen so any future change to identity (C4's
# display strip included) that silently broke a supersession chain fails
# here. Regenerate ONLY with an intended identity change + EXTRACTOR bump.
_GOLD = {
    "DECISION": "d04a4343f844b003",
    "FAILED-APPROACH": "f841fecfb7f2014d",
    "FINDING": "e5f1789b4ac9d345",
}


def _entry(etype, content, *, sidechain=False, ts="2026-07-03T10:00:00Z"):
    return {
        "type": etype,
        "sessionId": "cap1feed-session",
        "timestamp": ts,
        "isSidechain": sidechain,
        "isMeta": False,
        "message": {"role": etype, "content": content},
    }


def _transcript(tmp_path):
    entries = [
        _entry("assistant", [
            {"type": "text", "text": _DECISION},
            {"type": "text", "text": _FAILED},
            {"type": "text", "text": _CONSTRAINT},
        ]),
        _entry("assistant", [{"type": "text", "text": _FINDING}],
               sidechain=True),
    ]
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries),
                    encoding="utf-8")
    return str(path)


def _entity(parsed, prefix):
    return next(e for e in parsed.corpus.entities
               if e.name.startswith(prefix))


def _value(parsed, prefix, key):
    ent = _entity(parsed, prefix)
    return next(f.value for f in ent.fields if f.key == key)


def test_c1_full_decision_rationale_survives(tmp_path):
    """RED on parent: the 'because …' tail past char 280 is dropped."""
    value = _value(parse_transcript(_transcript(tmp_path)), "DECISION",
                   "DECISION")
    assert "SENTINEL_TAIL_TOKEN" in value
    assert len(value) > 280


def test_c1_failed_approach_full(tmp_path):
    """RED on parent: the failed-approach note is truncated at 280."""
    value = _value(parse_transcript(_transcript(tmp_path)),
                   "FAILED-APPROACH", "NOTE")
    assert "SENTINEL_FAIL_TOKEN" in value


def test_c1_subagent_finding_full(tmp_path):
    """RED on parent: the subagent finding is truncated at 280."""
    value = _value(parse_transcript(_transcript(tmp_path)), "FINDING",
                   "FINDING")
    assert "SENTINEL_FIND_TOKEN" in value


def test_c1_identity_unchanged_golden_pin(tmp_path):
    """Regression pin (passes on parent AND fix): C1 changes the stored
    display value only; identity is computed on the full sentence, so the
    fact_id is frozen. A break here means a supersession chain silently
    moved."""
    parsed = parse_transcript(_transcript(tmp_path))
    for prefix, gold in _GOLD.items():
        fid = next(f.value for f in _entity(parsed, prefix).fields
                   if f.key == "FACT-ID")
        assert fid == gold, f"{prefix} identity changed: {fid} != {gold}"


def test_c1_gist_preview_bounds_decision_but_never_constraint(tmp_path):
    """RED on parent (via storage): with the full sentence stored, the
    injected gist caps the decision with an ellipsis (so full rationale
    cannot blow the budget) while the constraint renders whole with its
    trailing negation intact."""
    gist = build_gist(parse_transcript(_transcript(tmp_path)))
    assert "…" in gist                         # decision preview is bounded
    assert "SENTINEL_TAIL_TOKEN" not in gist    # its tail is not injected
    assert "must not self-ratify" in gist       # constraint whole, negation kept


def test_c1_preview_helper_is_bounded_and_lossless_below_cap():
    """Forward guard on the helper: short text untouched; long text cut at
    the cap with an ellipsis. It is only ever applied to non-constraint
    kinds (see _entity_line / build_project_gist), so it never severs a
    constraint's negation."""
    assert _preview("keep this whole") == "keep this whole"
    out = _preview("x" * (_PREVIEW_CAP + 50))
    assert out.endswith("…") and len(out) <= _PREVIEW_CAP + 1
