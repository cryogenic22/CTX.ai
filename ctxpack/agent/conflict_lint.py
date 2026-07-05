"""Checkpoint-time decision-conflict lint — drift governance.

Ratified contract: precision-first — deterministic, checkpoint-time,
SILENT unless the match is exact, because a lint that cries wolf gets
ignored, and an ignored governance signal is worse than none. The goal
is "never change decisions silently", not "never change decisions":
the override path is a sentence-leading ``Supersedes: <fact_id> —
<reason>`` line directly after the Decision: line (parsed into
SUPERSEDES-FACT-ID / SUPERSEDES-REASON by the transcript parser).

Ratified scope, generic cases only — ctx stays domain-blind:

1. ``constraint_collision`` — a canonical ``Decision:`` in the current
   session shares an exact contiguous content phrase (5-word n-gram
   containing at least one content token) with a banked CONSTRAINT.
   Full-text containment was rejected: the flagship drift case
   ("Decision: run the $60 full pass now" vs "Do not run the $60 full
   pass until cost reporting is fixed") contains neither text in the
   other — the shared phrase is the exact evidence.
2. ``protected_subject`` — the decision touches a subject the REPO
   declared protected in ``.claude/ctx/protected.json`` (KP_SDLC
   declares "structural floor"; ctx only matches declared phrases).
3. same-key/different-value is ratified but has NO PRODUCER yet: fact
   keys today are only literal kinds (git_sha, path, ...), where
   same-key/different-value is normal, and unkeyed prose facts revise
   through the future supersession DAG (spec §4). The case lands with
   the first keyed producer (``tool_observed`` knobs).

Comparison base: constraints banked by sessions that first-checkpointed
EARLIER in journal order, plus the current session's own earlier turns —
so a session's conflict rows are stable no matter when its events block
is re-materialized. Same-turn pairs are skipped: a decision stated in
the same message as its constraint is exposition, not drift.

Lint scope guard: only canonical ``Decision:``-marked facts are linted.
Verb-inferred decisions are the measured junk class and alias markers
(Verdict:/Conclusion:) are self-assessments — linting them would cry
wolf.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from .transcript_parser import decision_marker

NGRAM_WORDS = 5
MIN_PHRASE_CHARS = 18
MAX_ROWS = 24  # sanity bound; the gist renders fewer

_TOKEN_RE = re.compile(r"[a-z0-9$%.]+")

# Tokens that carry meaning on their own — a shared n-gram made only of
# glue words is not evidence
_GLUE = frozenset(
    "the a an and or of to in for on with is are was were be been being "
    "it this that these those as at by from into over under after before "
    "we i you they he she our your their its not no do does did done "
    "will would should could can may might must have has had if then "
    "than so such only also just because until unless".split())


def _tokens(text: str) -> "list[str]":
    return _TOKEN_RE.findall(str(text).lower())


def _content_token(tok: str) -> bool:
    if tok in _GLUE:
        return False
    return len(tok) >= 5 or any(c.isdigit() for c in tok) or "$" in tok


def _shared_phrase(a: "list[str]", b: "list[str]") -> str:
    """First contiguous NGRAM_WORDS-gram present in both token streams
    that carries a content token and enough characters — '' if none.
    Deterministic: b is scanned left to right."""
    n = NGRAM_WORDS
    if len(a) < n or len(b) < n:
        return ""
    grams_a = {tuple(a[i:i + n]) for i in range(len(a) - n + 1)}
    for i in range(len(b) - n + 1):
        g = tuple(b[i:i + n])
        if g not in grams_a:
            continue
        if not any(_content_token(t) for t in g):
            continue
        phrase = " ".join(g)
        if len(phrase) >= MIN_PHRASE_CHARS:
            return phrase
    return ""


def load_protected_subjects(out_dir: str) -> "list[dict]":
    """Repo-declared protected subjects (.claude/ctx/protected.json).
    Accepts {"subjects": [{"phrase": ..., "reason": ...}, ...]} or a
    bare list; unparseable file → no subjects (never crash a hook)."""
    path = os.path.join(out_dir, "protected.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    raw = data.get("subjects", []) if isinstance(data, dict) else data
    subjects: "list[dict]" = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            phrase, reason = item, ""
        elif isinstance(item, dict) and item.get("phrase"):
            phrase, reason = str(item["phrase"]), str(item.get("reason", ""))
        else:
            continue
        toks = _tokens(phrase)
        if toks and (len(toks) >= 2 or len(phrase) >= 8):
            subjects.append({"phrase": phrase, "tokens": toks,
                             "reason": reason[:200]})
    return subjects


def _field(entity, key: str) -> str:
    return next((f.value for f in entity.fields if f.key == key), "")


def _contains(haystack: "list[str]", needle: "list[str]") -> bool:
    n = len(needle)
    return any(haystack[i:i + n] == needle
               for i in range(len(haystack) - n + 1))


def _banked_constraints(out_dir: str,
                        current_sid8: str) -> "list[tuple[str, str, str]]":
    """(fact_id, src, text) for constraints of sessions that
    first-checkpointed earlier than the current one (journal order)."""
    from ..core.parser import parse as _parse_ctx
    from .checkpoint import _journal_session_order
    from .session_reader import _kind_of, _kv, _primary_value, _sections, \
        _turn_of

    order = _journal_session_order(out_dir)
    if current_sid8 in order:
        order = order[:order.index(current_sid8)]
    rows: "list[tuple[str, str, str]]" = []
    for sid in order:
        path = os.path.join(out_dir, f"session-{sid}.ctx")
        try:
            with open(path, encoding="utf-8") as f:
                doc = _parse_ctx(f.read(), level=2)
        except Exception:  # noqa: BLE001 — one bad ledger must not kill the lint
            continue
        for section in _sections(doc):
            if _kind_of(section) != "CONSTRAINT":
                continue
            text = _primary_value(section)
            if not text:
                continue
            rows.append((_kv(section, "FACT-ID"),
                         f"s:{sid}#turn{_turn_of(section)}", text))
    return rows


def lint_decisions(corpus_entities, out_dir: str,
                   current_session_id: str,
                   protected: "Optional[list[dict]]" = None) -> "list[dict]":
    """Lint the current session's canonical decisions against durable
    memory. Returns conflict rows (resolved ones included, flagged) —
    deterministic for a given (corpus, earlier ledgers, protected.json).
    """
    sid8 = (current_session_id or "")[:8]
    if protected is None:
        protected = load_protected_subjects(out_dir)

    decisions = []
    for e in corpus_entities:
        if not e.name.startswith("DECISION-"):
            continue
        value = _field(e, "DECISION")
        if _field(e, "BASIS") != "marker_stated" \
                or decision_marker(value) != "decision":
            continue
        decisions.append(e)

    constraints = _banked_constraints(out_dir, sid8)
    # ... plus the current session's own earlier constraints (drift
    # across an in-session compaction is the CompactBench axis)
    for e in corpus_entities:
        if e.name.startswith("CONSTRAINT-"):
            turn = e.sources[0].turn if e.sources else -1
            constraints.append((_field(e, "FACT-ID"),
                                f"s:{sid8}#turn{turn}",
                                _field(e, "RULE")))

    rows: "list[dict]" = []
    seen: set = set()
    for e in decisions:
        value = _field(e, "DECISION")
        d_fid = _field(e, "FACT-ID")
        d_turn = e.sources[0].turn if e.sources else -1
        d_tokens = _tokens(value)
        sup_target = _field(e, "SUPERSEDES-FACT-ID")
        sup_reason = _field(e, "SUPERSEDES-REASON")

        for c_fid, c_src, c_text in constraints:
            if c_src == f"s:{sid8}#turn{d_turn}":
                continue  # same message: exposition, not drift
            phrase = _shared_phrase(_tokens(c_text), d_tokens)
            if not phrase:
                continue
            key = (d_fid, "constraint_collision", c_fid)
            if key in seen:
                continue
            seen.add(key)
            resolved = bool(sup_reason) and sup_target == c_fid
            rows.append({
                "case": "constraint_collision",
                "decision_fact_id": d_fid, "decision_turn": d_turn,
                "decision": value[:160],
                "against_fact_id": c_fid, "against_src": c_src,
                "against": c_text[:160], "phrase": phrase[:120],
                "resolved": resolved,
                "reason": sup_reason if resolved else "",
            })

        for subject in protected:
            if not _contains(d_tokens, subject["tokens"]):
                continue
            key = (d_fid, "protected_subject", subject["phrase"])
            if key in seen:
                continue
            seen.add(key)
            # protected subjects need not map to a fact — any explicit
            # Supersedes override WITH a reason resolves the row
            resolved = bool(sup_reason)
            rows.append({
                "case": "protected_subject",
                "decision_fact_id": d_fid, "decision_turn": d_turn,
                "decision": value[:160],
                "against_fact_id": "", "against_src": "protected.json",
                "against": subject["phrase"],
                "phrase": subject["phrase"][:120],
                "resolved": resolved,
                "reason": sup_reason if resolved else "",
            })

        if len(rows) >= MAX_ROWS:
            break
    return rows[:MAX_ROWS]
