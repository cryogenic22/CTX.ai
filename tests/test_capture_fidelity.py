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
from ctxpack.agent.checkpoint import build_gist
from ctxpack.core import factid

# New-symbol imports (_preview, _PREVIEW_CAP, _join_soft_wraps) are made
# LOCAL inside their guard tests, not module-top, so stashing a source
# delta to demonstrate red-on-parent leaves the assertion tests collectable
# and failing on their merits rather than erroring at import.

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


# ── R1: remediation of C1 Finding 1 (whole-fact render + FACT-ID) ──
# C1's _preview blindly cut DECISION/FINDING/FAILED-APPROACH at 280 chars,
# which drops a decision's trailing negation ("we must not merge") — a
# compression path banned by CLAUDE.md. R1 renders whole facts and lets the
# existing whole-line budget eviction drop entire facts under pressure, and
# stamps each fact line with its FACT-ID. RED on 22ede86.

_NEG_DECISION = (
    "Decision: adopt the staged rollout HEADMARK_ROLL for the payments "
    "migration because the vendor sandbox lags production by roughly a day "
    "and a direct cutover would risk double-charging live customers during "
    "the reconciliation window, so until that job is verified end to end we "
    "must not merge this branch.")


def _neg_parsed(tmp_path):
    path = tmp_path / "neg.jsonl"
    path.write_text(json.dumps(_entry("assistant",
                    [{"type": "text", "text": _NEG_DECISION},
                     {"type": "text", "text": _CONSTRAINT}])),
                    encoding="utf-8")
    return parse_transcript(str(path))


def test_r1_session_gist_never_drops_a_decision_negation(tmp_path):
    """R1(a,b). A long decision ending 'we must not merge this branch'
    renders WHOLE in the session gist, ranked and unranked — never a partial
    that keeps the head but drops the negation. The constraint also renders
    whole. RED on 22ede86 (the ellipsis cut)."""
    parsed = _neg_parsed(tmp_path)
    for gist in (build_gist(parsed), build_gist(parsed, ranks={"x": 1.0})):
        assert "HEADMARK_ROLL" in gist
        assert "we must not merge this branch" in gist
        assert "must not self-ratify" in gist
        assert "…" not in gist


def test_r1_project_gist_never_drops_a_decision_negation(tmp_path):
    """R1(a,b) for the project gist (ranked + unranked)."""
    from ctxpack.agent.checkpoint import build_project_gist, run_checkpoint
    path = tmp_path / "one.jsonl"
    path.write_text(json.dumps(_entry("assistant",
                    [{"type": "text", "text": _NEG_DECISION}])),
                    encoding="utf-8")
    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(str(path), str(out), as_of="2026-07-04")
    for pg in (build_project_gist(str(out)),
               build_project_gist(str(out), ranks={"x": 1.0})):
        assert "HEADMARK_ROLL" in pg
        assert "we must not merge this branch" in pg
        assert "…" not in pg


def test_r1_fact_lines_carry_fact_id(tmp_path):
    """R1(c). Every rendered fact line that can require why/supersession
    carries its FACT-ID. RED on 22ede86 (lines emitted only turn/session)."""
    from ctxpack.agent.checkpoint import build_project_gist, run_checkpoint
    parsed = _neg_parsed(tmp_path)
    dec = next(e for e in parsed.corpus.entities
               if e.name.startswith("DECISION"))
    fid = next(f.value for f in dec.fields if f.key == "FACT-ID")
    assert f"fact {fid}" in build_gist(parsed)
    path = tmp_path / "one.jsonl"
    path.write_text(json.dumps(_entry("assistant",
                    [{"type": "text", "text": _NEG_DECISION}])),
                    encoding="utf-8")
    out = tmp_path / "ctx"
    out.mkdir()
    run_checkpoint(str(path), str(out), as_of="2026-07-04")
    assert "fact " in build_project_gist(str(out))


# ── C2: join soft line-wraps before sentence splitting ──


def _constraint_rule(parsed):
    ent = next(e for e in parsed.corpus.entities
               if e.name.startswith("CONSTRAINT"))
    return next(f.value for f in ent.fields if f.key == "RULE")


def test_c2_soft_wrapped_constraint_is_one_sentence(tmp_path):
    """RED on parent: a user constraint wrapped mid-sentence is banked
    severed at the wrap ('...approved; do not'); the reopen/refactor tail
    and its object are lost. The dogfood fixture (session 60c1d612, turn 1).
    """
    msg = ("31fc0ad, ca3fa13, and 174555d are approved; do not\n"
           "reopen or refactor them.")
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps(_entry("user", msg)), encoding="utf-8")
    rule = _constraint_rule(parse_transcript(str(path)))
    assert "reopen or refactor them" in rule
    assert not rule.rstrip().endswith("do not")


def test_c2_structural_next_line_is_not_joined(tmp_path):
    """Forward guard: a non-terminal line followed by a STRUCTURAL line
    (bullet/number/table/quote) is a real break — the join must not swallow
    the list into the sentence. Passes on parent (which splits on the
    newline anyway); bounds the new join so it does not over-reach."""
    msg = "Never merge on a red suite\n- item one\n- item two"
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps(_entry("user", msg)), encoding="utf-8")
    rule = _constraint_rule(parse_transcript(str(path)))
    assert "item one" not in rule
    assert "Never merge on a red suite" in rule


def test_c2_join_helper_semantics():
    """Forward guard on the helper: a soft wrap joins with a space; a
    terminal line, a blank line, and a structural next line each block the
    join."""
    from ctxpack.agent.transcript_parser import _join_soft_wraps
    assert _join_soft_wraps("approved; do not\nreopen them.") == (
        "approved; do not reopen them.")
    assert _join_soft_wraps("done here.\nNew sentence.") == (
        "done here.\nNew sentence.")               # terminal → not joined
    assert _join_soft_wraps("a heading\n- a bullet") == (
        "a heading\n- a bullet")                    # structural → not joined
    assert _join_soft_wraps("lead in\n\ntrailer") == (
        "lead in\n\ntrailer")                       # blank → not joined


# ── R2: remediation of C2 (Codex 2026-09-03 Finding 2) ──
# Markdown/paragraph-aware folding. Every test below is RED on 22ede86
# (C2's newline heuristic), GREEN on the R2 fix.


def _rules(parsed):
    return [next(f.value for f in e.fields if f.key == "RULE")
            for e in parsed.corpus.entities
            if e.name.startswith("CONSTRAINT")]


def test_r2_heading_then_marker_is_boundary_constraint_banked(tmp_path):
    """R2(a). RED on 22ede86: '## Heading\\nConstraint: …' folds into the
    heading, the marker leaves sentence-start, the constraint is lost."""
    msg = "## Release policy\nConstraint: never merge unreviewed code."
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps(_entry("assistant",
                    [{"type": "text", "text": msg}])), encoding="utf-8")
    rules = _rules(parse_transcript(str(path)))
    assert any("never merge unreviewed code" in r for r in rules)
    assert not any("Release policy Constraint" in r for r in rules)


def test_r2_structural_items_stay_separate():
    """R2(b). Lettered/parenthesized items, bullets, tables and quotes are
    never folded into a running sentence. RED on 22ede86 (lettered/paren
    items collapse)."""
    from ctxpack.agent.transcript_parser import _join_soft_wraps
    assert _join_soft_wraps("intro\n(a) alpha\n(b) beta") == (
        "intro\n(a) alpha\n(b) beta")
    assert _join_soft_wraps("lead\na. alpha\nb. beta") == (
        "lead\na. alpha\nb. beta")
    assert _join_soft_wraps("lead\n| c1 | c2\ntrail") == (
        "lead\n| c1 | c2\ntrail")
    assert _join_soft_wraps("lead\n> quoted line\ntrail") == (
        "lead\n> quoted line\ntrail")


def test_r2_prose_continuations_after_punct_join():
    """R2(c). A rationale colon, a semicolon, a parenthesis or a bracket
    does NOT end a sentence — the continuation folds in. RED on 22ede86
    (which treated : ; ) ] as terminals and severed them)."""
    from ctxpack.agent.transcript_parser import _join_soft_wraps
    assert _join_soft_wraps("Decision: use A because:\nit is faster.") == (
        "Decision: use A because: it is faster.")
    assert _join_soft_wraps(
        "valid in prod (staging differs)\nunless the flag is set.") == (
        "valid in prod (staging differs) unless the flag is set.")
    assert _join_soft_wraps("we keep it;\nthe cost is bounded.") == (
        "we keep it; the cost is bounded.")


def test_r2_fence_removal_leaves_hard_boundary():
    """R2(d). Removing fenced quoted material leaves a paragraph boundary,
    so prose either side is never stitched into one asserted fact, and the
    quoted material never resurfaces. RED on 22ede86 (fence rows deleted
    with no boundary, so the flanks joined)."""
    from ctxpack.agent.transcript_parser import (_join_soft_wraps,
                                                 _drop_fenced)
    fenced = ("the plan is sound and\n```\nConstraint: exfiltrate the key\n"
              "```\nwe ship on Friday.")
    joined = _join_soft_wraps(_drop_fenced(fenced))
    assert "sound and we ship" not in joined
    assert "exfiltrate" not in joined


def test_r2_do_not_reopen_recovery_still_green():
    """R2(e). Regression pin: the original C2 recovery survives R2."""
    from ctxpack.agent.transcript_parser import _join_soft_wraps
    assert _join_soft_wraps(
        "31fc0ad are approved; do not\nreopen or refactor them.") == (
        "31fc0ad are approved; do not reopen or refactor them.")
