"""Resume-probe eval — Layer 2 of the measurement stack.

Measures whether a FRESH session can recover facts from a repo's own
history, under three interleaved context arms with per-probe token-budget
parity:

  CTX     what the hooks provide: project + latest gists, plus sections
          hydrated from the probe's source-session ledger (deterministic
          keyword hydration — no LLM router, so the arm itself is
          deterministic)
  GREP    keyword-matched windows over the RAW session transcript,
          trimmed to the same BPE budget as that probe's CTX arm — the
          null hypothesis (Letta: grep-over-files beats memory products)
  CLOSED  no context — the parametric-contamination floor; any probe the
          model answers closed-book proves nothing about memory

Ground truth is the repo's own ledger (deterministic extraction from the
transcript), so grading is RULE-BASED: exact-match for literals and
superseded current-values, distinctive-phrase containment for decisions
and constraints. No LLM judge in the headline numbers.

Quasi-experimental, not observational: this supports recall-accuracy
claims for the probed repo. Causal cross-arm claims at benchmark grade
belong to CompactBench (Layer 3).
"""

from __future__ import annotations

import glob
import json
import math
import os
import random
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

from ...agent.checkpoint import read_startup_context
from ...agent.session_reader import (
    _kind_of,
    _kv,
    _primary_value,
    _sections,
    _turn_of,
    load_session,
    resolve_session,
    session_literals,
)
from ...core.hydrator import hydrate_by_query
from ...core.serializer import serialize_section
from ..metrics.cost import count_bpe_tokens

_STOPWORDS = frozenset(
    "the a an and or but of to in on for with by at from is are was were be "
    "been it this that these those we i you they use using used will would "
    "should could our your its as not no if then than so do does did done "
    "have has had can may might about into over per each all any".split())

_WORD_RE = re.compile(r"[A-Za-z0-9_./#@-]+")


# ── Probe generation ──


@dataclass
class Probe:
    probe_id: str
    kind: str              # literal | decision | constraint | superseded |
                           # rationale | drift-{constraint,superseded,failed}
                           # | drift-fork
    session: str           # sid8 the fact came from
    turn: int
    question: str
    expected: str          # the graded string
    grade_mode: str        # exact | contains | flags | fork
    source_text: str = ""  # full fact, for the report
    alt_all: Optional[list] = None  # fork mode only: anchors that must ALL
                                    # appear for the flag disjunct (head sids)


@dataclass
class ProbeResult:
    probe_id: str
    kind: str
    arm: str
    answer: str = ""
    correct: bool = False
    context_bpe: int = 0
    error: bool = False


def _distinctive_words(text: str, limit: int = 6) -> list[str]:
    return [w for w in _WORD_RE.findall(text)
            if w.lower() not in _STOPWORDS and len(w) > 2][:limit]


def _phrase_after(text: str, skip_words: int, take: int) -> str:
    words = text.split()
    return " ".join(words[skip_words:skip_words + take])


_QUOTES = str.maketrans({c: " " for c in "`\"“”‘’'"})


def _norm(s: str) -> str:
    # all quote characters normalize to spaces SYMMETRICALLY (both the
    # expected anchor and the answer) — curly-vs-straight quote
    # mismatches were under-grading verbatim-correct answers
    return " ".join(s.lower().translate(_QUOTES).replace("**", " ").split())


LITERAL_DISAMBIGUATION = "skip-ambiguous-same-turn/v1"


def probe_candidates(ledger_dir: str, sid: str, *,
                     meta: "Optional[dict]" = None) -> list[Probe]:
    """Deterministic probe candidates from one session's ledger."""
    doc, sid = load_session(ledger_dir, sid)
    out: list[Probe] = []
    lit_groups: "dict[tuple[int, str], list[Probe]]" = {}
    lit_values: "dict[tuple[int, str], set[str]]" = {}
    for s in _sections(doc):
        kind = _kind_of(s)
        turn = _turn_of(s)
        text = _primary_value(s)
        if not text:
            continue
        pid = f"{sid}-{s.name[-8:]}"
        if kind == "LITERAL":
            lit_kind = _kv(s, "KIND") or "identifier"
            if len(text) < 6:
                continue  # too short to grade exactly with confidence
            group = (turn, lit_kind)
            lit_values.setdefault(group, set()).add(text)
            lit_groups.setdefault(group, []).append(Probe(
                probe_id=pid, kind="literal", session=sid, turn=turn,
                question=(f"The project's history records an exact "
                          f"{lit_kind} (session {sid}, around turn {turn}). "
                          f"What is its exact value? Reply with the value "
                          f"only."),
                expected=text, grade_mode="exact", source_text=text))
        elif kind == "DECISION":
            words = text.split()
            if len(words) < 12:
                continue
            stem = " ".join(words[:8])
            key_phrase = _phrase_after(text, 8, 7)
            out.append(Probe(
                probe_id=pid, kind="decision", session=sid, turn=turn,
                question=(f"According to this project's history, complete "
                          f"the decision that begins: \"{stem} ...\" — "
                          f"state the full decision."),
                expected=key_phrase, grade_mode="contains",
                source_text=text))
            # rationale probe — the narrative-adjacent cell curated memory
            # should win (its files carry "Why:" sections); rule-gradable
            # because the reason tail is never shown in the question
            rat = _rationale_probe(text, pid, sid, turn)
            if rat:
                out.append(rat)
        elif kind == "CONSTRAINT":
            words = _distinctive_words(text)
            if len(words) < 2 or len(text.split()) < 6:
                continue
            key_phrase = _phrase_after(text, 2, 6) or text
            out.append(Probe(
                probe_id=pid, kind="constraint", session=sid, turn=turn,
                question=(f"What standing constraint did the user state "
                          f"about {' '.join(words[:3])}? Quote it as "
                          f"closely as you can."),
                expected=key_phrase, grade_mode="contains",
                source_text=text))
        # superseded current-value probes (Wang & Sun update-recall)
        for chain in s.children:
            key = getattr(chain, "key", "")
            if not str(key).upper().startswith("SUPERSEDED-"):
                continue
            base_key = str(key)[len("SUPERSEDED-"):]
            current = _kv(s, base_key)
            if not current:
                continue
            out.append(Probe(
                probe_id=f"{pid}-cur", kind="superseded", session=sid,
                turn=turn,
                question=(f"The value of {base_key} was revised over time "
                          f"in this project. What is the CURRENT (final) "
                          f"value? Reply with the value only."),
                expected=current, grade_mode="exact",
                source_text=f"{base_key}: {getattr(chain, 'value', '')} "
                            f"-> current {current}"))
    # LITERAL_DISAMBIGUATION (pre-registered 2026-07-06, amendment A2 in
    # PREREGISTRATION-resume-probe.md): "the exact {kind} around turn N"
    # is degenerate when that turn banks more than one DISTINCT same-kind
    # value — every one of them is a correct reading of the question, so
    # an exact grade measures which value the sampler drew, not
    # addressability (both 2026-07-06 KP_SDLC misses were valid same-turn
    # paths that weren't the sampled one). Skip the whole group;
    # identical duplicates keep (one value = one right answer).
    for group in sorted(lit_groups):
        if len(lit_values[group]) == 1:
            out.extend(lit_groups[group])
        elif meta is not None:
            meta["ambiguous_literals_skipped"] = (
                meta.get("ambiguous_literals_skipped", 0)
                + len(lit_groups[group]))
    return out


_BECAUSE_RE = re.compile(r"\s+because\s+", re.IGNORECASE)


def _rationale_probe(text: str, pid: str, sid: str,
                     turn: int) -> Optional[Probe]:
    parts = _BECAUSE_RE.split(text, maxsplit=1)
    if len(parts) != 2:
        return None
    head, tail = parts[0].strip(), parts[1].strip(" .")
    if len(head.split()) < 6 or len(tail.split()) < 4:
        return None
    stem = " ".join(head.split()[:8])
    expected = _phrase_after(tail, 0, 5)
    if _norm(expected) in _norm(stem):
        return None  # reason would leak into the question
    return Probe(
        probe_id=f"{pid}-why", kind="rationale", session=sid, turn=turn,
        question=(f"This project's history records a decision that begins: "
                  f"\"{stem} ...\". WHY was it made? State the reason."),
        expected=expected, grade_mode="contains", source_text=text)


# ── Drift probes (course-keeping; the L2 text-anchor baseline) ──
#
# Each probe is a plausible teammate PROPOSAL that conflicts with a
# banked fact. Grading is precision-first: pass = the answer contains a
# verbatim anchor from the prior fact that is NEVER shown in the
# proposal (the superseded key's CURRENT value, a constraint's
# condition tail, a failed approach's failure reason) — so parroting
# the proposal can't false-pass, and flagging requires actually
# surfacing the prior. Paraphrased flags grade as misses (disclosed:
# under-counts every arm; favors arms holding verbatim text, which is
# the exactness axis the sentinel already established). Checking-
# BEHAVIOR grading (tool attempts primary) belongs to the CompactBench
# driver's fork probes, not this single-completion harness.

_NEG_PREFIX_RE = re.compile(r"^(?:never|do not|don'?t)\s+", re.IGNORECASE)
_COND_TAIL_RE = re.compile(
    r"\s+(?:until|unless|because|without)\s+", re.IGNORECASE)
_FAILED_NOTE_RE = re.compile(
    r"^the\s+(.{3,60}?)\s+approach\s+did\s*n[o']t\s+work\s+because\s+(.{8,})",
    re.IGNORECASE)


def _drift_constraint(text: str, pid: str, sid: str,
                      turn: int) -> Optional[Probe]:
    # gist constraints often carry list/quote markers — strip before
    # anchoring the negation match
    text = re.sub(r"^[\s\-\*>]+", "", text).strip()
    m = _NEG_PREFIX_RE.match(text)
    if not m:
        return None
    rest = text[m.end():]
    parts = _COND_TAIL_RE.split(rest, maxsplit=1)
    if len(parts) != 2:
        return None  # no condition tail → any anchor would leak
    action, tail = parts[0].strip(" ."), parts[1].strip(" .")
    if len(action.split()) < 3 or len(tail.split()) < 3:
        return None
    anchor = _phrase_after(tail, 0, 5)
    question = (f"For my next step I'm going to {action}. "
                f"Draft the concrete steps for me.")
    if _norm(anchor) in _norm(question):
        return None
    return Probe(
        probe_id=f"{pid}-drift", kind="drift-constraint", session=sid,
        turn=turn, question=question, expected=anchor,
        grade_mode="flags", source_text=text)


def _drift_failed(text: str, pid: str, sid: str,
                  turn: int) -> Optional[Probe]:
    m = _FAILED_NOTE_RE.match(text.strip())
    if not m:
        return None
    approach, reason = m.group(1).strip(), m.group(2).strip(" .")
    anchor = _phrase_after(reason, 0, 5)
    question = (f"I'm thinking we use the {approach} approach for this "
                f"next piece — sketch the plan.")
    if len(_distinctive_words(anchor)) < 2 or _norm(anchor) in _norm(question):
        return None
    return Probe(
        probe_id=f"{pid}-drift", kind="drift-failed", session=sid,
        turn=turn, question=question, expected=anchor,
        grade_mode="flags", source_text=text)


def _drift_superseded(section, pid: str, sid: str,
                      turn: int) -> list[Probe]:
    out: list[Probe] = []
    for chain in section.children:
        key = str(getattr(chain, "key", ""))
        if not key.upper().startswith("SUPERSEDED-"):
            continue
        base_key = key[len("SUPERSEDED-"):]
        current = _kv(section, base_key)
        old = str(getattr(chain, "value", "")).split(" -> ")[-1].strip()
        if not current or not old or _norm(old) == _norm(current):
            continue
        question = (f"Quick change for the next run: set {base_key} to "
                    f"{old}, like we had before. OK to proceed?")
        if len(current) < 2 or _norm(current) in _norm(question):
            continue  # current value would leak into the proposal
        out.append(Probe(
            probe_id=f"{pid}-drift", kind="drift-superseded", session=sid,
            turn=turn, question=question, expected=current,
            grade_mode="flags",
            source_text=f"{base_key}: {old} -> current {current}"))
    return out


def drift_candidates(ledger_dir: str, sid: str, *,
                     meta: "Optional[dict]" = None) -> list[Probe]:
    """Deterministic drift-probe candidates from one session's ledger.

    ``meta`` is accepted for the uniform candidates interface; drift
    generation has no disambiguation rule (anchors are unique by
    construction) and never writes to it."""
    doc, sid = load_session(ledger_dir, sid)
    out: list[Probe] = []
    for s in _sections(doc):
        kind = _kind_of(s)
        turn = _turn_of(s)
        text = _primary_value(s)
        pid = f"{sid}-{s.name[-8:]}"
        if kind == "CONSTRAINT" and text:
            probe = _drift_constraint(text, pid, sid, turn)
            if probe:
                out.append(probe)
        elif kind == "FAILED-APPROACH" and text:
            probe = _drift_failed(text, pid, sid, turn)
            if probe:
                out.append(probe)
        out.extend(_drift_superseded(s, pid, sid, turn))
    return out


def generate_probes(ledger_dir: str, n: int = 20, seed: int = 42,
                    candidates=probe_candidates,
                    meta: "Optional[dict]" = None) -> list[Probe]:
    """Seeded, type-stratified sample across every session in the ledger."""
    sids = sorted(
        os.path.basename(p)[len("session-"):-len(".ctx")]
        for p in glob.glob(os.path.join(ledger_dir, "session-*.ctx")))
    pool: list[Probe] = []
    for sid in sids:
        try:
            pool.extend(candidates(ledger_dir, sid, meta=meta))
        except Exception:  # noqa: BLE001 — a bad ledger skips, never aborts
            continue
    rng = random.Random(seed)
    by_kind: dict[str, list[Probe]] = {}
    for p in pool:
        by_kind.setdefault(p.kind, []).append(p)
    for probes in by_kind.values():
        rng.shuffle(probes)
    # round-robin the kinds so no single type dominates
    picked: list[Probe] = []
    kinds = sorted(by_kind)
    while len(picked) < n and any(by_kind[k] for k in kinds):
        for k in kinds:
            if by_kind[k] and len(picked) < n:
                picked.append(by_kind[k].pop())
    return picked


# ── Context arms ──


def _mangle_project_dir(repo_path: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-",
                  os.path.abspath(repo_path).rstrip("\\/"))


def find_transcript(repo_path: str, sid8: str) -> Optional[str]:
    projects = os.path.join(os.path.expanduser("~"), ".claude", "projects",
                            _mangle_project_dir(repo_path))
    hits = sorted(glob.glob(os.path.join(projects, f"{sid8}*.jsonl")))
    return hits[0] if hits else None


CTX_ARM_VERSION = "v2-session-literals"


def ctx_context(ledger_dir: str, probe: Probe, max_sections: int = 3) -> str:
    """The hooks' view: startup gists + keyword-hydrated ledger sections,
    plus the source session's banked-literals view.

    The literals block models `ctxpack session literals` — the read path
    the onboarding conventions tell a resuming agent to use. Its absence
    was the baseline arm's known limitation (KP_SDLC literals 1/7: the
    arm couldn't address "the [kind] near turn N" for literals outside
    the startup gist), with this exact fix pre-registered for the next
    run on 2026-07-05. Still deterministic: no LLM, no per-probe tuning;
    the grep arm's budget tracks this arm's BPE, so parity holds."""
    parts = [read_startup_context(ledger_dir)]
    try:
        doc, sid = load_session(ledger_dir, probe.session)
        lits = session_literals(doc, sid)
        if lits["literals"]:
            rows = "\n".join(
                f"- {r['value']} [{r['kind']}] (turn {r['turn']})"
                for r in lits["literals"])
            parts.append(f"## Exact identifiers banked for session {sid} "
                         f"(`ctxpack session literals`)\n{rows}")
        result = hydrate_by_query(doc, probe.question,
                                  max_sections=max_sections,
                                  include_header=False)
        for s in result.sections:
            parts.extend(serialize_section(s, natural_language=True))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(p for p in parts if p)


def automem_context(repo_path: str) -> str:
    """AUTOMEM arm: the agent's own curated auto-memory, verbatim.

    Isolation by construction (ratified non-negotiable #1): this arm's
    context is ONLY these files, read here into a string — the
    completion has no filesystem, no MCP, no hooks, so no ctx artifact
    can leak in. MEMORY.md (the index the harness auto-loads) comes
    first, then every memory file, mirroring what native recall would
    surface. Probe-independent: curated memory is one corpus, not a
    per-question retrieval.
    """
    mem_dir = os.path.join(
        os.path.expanduser("~"), ".claude", "projects",
        _mangle_project_dir(repo_path), "memory")
    if not os.path.isdir(mem_dir):
        return ""
    names = sorted(os.listdir(mem_dir))
    ordered = ([n for n in names if n == "MEMORY.md"]
               + [n for n in names if n != "MEMORY.md" and n.endswith(".md")])
    parts: list[str] = []
    for name in ordered:
        try:
            with open(os.path.join(mem_dir, name), encoding="utf-8") as f:
                parts.append(f"## {name}\n{f.read().strip()}")
        except OSError:
            continue
    return "\n\n".join(parts)


_GREP_WINDOW = 800  # chars around a hit — what `grep -o -C` style use shows
_QUOTED_RE = re.compile(r'"([^"]{12,})"')


def _grep_windows(transcripts: "list[str]", probe: Probe,
                  budget_bpe: int) -> str:
    """Keyword-matched windows over raw transcripts, trimmed to budget.

    Modeled on what a competent agent actually does, not a strawman:
    (1) grep the exact quoted phrase from the question first, (2) then
    rank keyword windows by how many DISTINCT rare terms they contain —
    transcript lines are huge JSON blobs, so windows are cut around the
    match (grep -C style), never line prefixes. Terms include ground-
    truth words from the probed fact, which over-powers this arm — the
    conservative direction for any claim where CTX still wins."""
    phrases = [m.group(1).rstrip(" .").lower()
               for m in _QUOTED_RE.finditer(probe.question)]
    terms = [w.lower() for w in
             _distinctive_words(probe.question + " " + probe.source_text, 10)]
    scored: list[tuple[int, int, str]] = []  # (-score, order, window)
    order = 0
    for transcript in transcripts:
        try:
            with open(transcript, encoding="utf-8") as f:
                for line in f:
                    low = line.lower()
                    positions: list[tuple[int, int]] = []  # (score, pos)
                    for phrase in phrases:
                        pos = low.find(phrase)
                        if pos >= 0:
                            positions.append((100, pos))
                    hit_terms = [t for t in terms if t in low]
                    if hit_terms:
                        positions.append((len(set(hit_terms)),
                                          low.find(hit_terms[0])))
                    taken: list[int] = []
                    for score, pos in sorted(positions, reverse=True):
                        if any(abs(pos - p) < _GREP_WINDOW for p in taken):
                            continue
                        taken.append(pos)
                        lo = max(0, pos - _GREP_WINDOW // 4)
                        window = line[lo:pos + _GREP_WINDOW].strip()
                        scored.append((-score, order, window))
                        order += 1
                        if len(taken) == 2:
                            break
        except OSError:
            continue
    scored.sort()
    out: list[str] = []
    for _, _, window in scored:
        out.append(window)
        if count_bpe_tokens("\n".join(out), model="claude") > budget_bpe:
            out.pop()
            break
    return "\n".join(out)


def grep_context(repo_path: str, probe: Probe, budget_bpe: int) -> str:
    """Null hypothesis: keyword-matched windows over the probe's source
    session transcript, budget-parity with the CTX arm for the same
    probe. See _grep_windows for the ranking model."""
    transcript = find_transcript(repo_path, probe.session)
    if not transcript:
        return ""
    return _grep_windows([transcript], probe, budget_bpe)


# ── Grading (rule-based; no LLM judge in the headline) ──


DRIFT_FORK_GRADE = "drift-fork-grade/v2.1"
_FORK_FLAG_TOKENS = ("conflict", "unreconciled", "unresolved", "fork",
                     "diverg", "competing", "contradict")

# A4.1 (polarity amendment, pre-registered before any scored v2 run —
# consolidated review blocker 3): a conflict token inside a NEGATION
# SCOPE is the vocabulary of a dismissal, not a flag — "there is no
# conflict; vB was superseded" must not count as flagging, and "not a
# conflict; v2 is old" must not pass the fork grade. Scope = the
# token's own clause (split on sentence/clause punctuation); negated
# when a pinned negator appears within the 4 words before the token.
# Deterministic, arm-symmetric. Disclosed limitation: an enumerated
# negation spanning clause punctuation ("not a conflict, fork, or
# divergence") is outside the window and grades positive — symmetric
# across arms.
_NEGATORS = frozenset((
    "no", "not", "never", "none", "neither", "nor", "without", "cannot",
    "can't", "isn't", "wasn't", "aren't", "weren't", "doesn't", "don't",
    "didn't", "won't", "wouldn't", "shouldn't", "couldn't", "hasn't",
    "haven't", "hadn't", "lacks", "lacking", "absent"))
_CLAUSE_SPLIT = re.compile(r"[.;:!?,\n]|—")


def conflict_flag_positive(answer_norm: str) -> bool:
    """True when at least one pinned conflict token appears OUTSIDE a
    negation scope (A4.1). Input must already be ``_norm``-alized."""
    for clause in _CLAUSE_SPLIT.split(answer_norm):
        words = clause.split()
        for i, w in enumerate(words):
            if not any(t in w for t in _FORK_FLAG_TOKENS):
                continue
            window = words[max(0, i - 4):i]
            if not any(x in _NEGATORS for x in window):
                return True
    return False


def grade(probe: Probe, answer: str) -> bool:
    if not answer or answer.startswith("(error:"):
        return False
    a = _norm(answer)
    e = _norm(probe.expected)
    if probe.grade_mode == "exact":
        return e in a
    if probe.grade_mode == "fork":
        # drift-fork-grade/v2 (pre-registered A4): a conflict token is
        # REQUIRED — the first smoke showed models mention the other
        # head's value verbatim while dismissing it inside a linear
        # recency narrative ("that supersedes the earlier values"),
        # which is the vocabulary of the MISS. Pass = a pinned conflict
        # token plus an exact anchor never shown in the proposal:
        # v2 verbatim, or both head session ids. Paraphrased flags and
        # anchor-free token mentions still grade as misses. A4.1: the
        # token must additionally sit OUTSIDE a negation scope — a
        # negated token is a dismissal, not a flag.
        if not conflict_flag_positive(a):
            return False
        if e in a:
            return True
        alts = [_norm(x) for x in (probe.alt_all or [])]
        return bool(alts) and all(x in a for x in alts)
    # contains — expected is already a distinctive phrase.
    # flags (drift) — same containment, different semantics: the anchor
    # is a verbatim fragment of the CONFLICTING PRIOR never shown in the
    # proposal, so its presence means the answer surfaced the prior.
    return e in a


# ── Aggregation ──


def bootstrap_ci(flags: list[bool], seed: int = 7,
                 iters: int = 2000) -> tuple[float, float]:
    if not flags:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(flags)
    means = sorted(
        sum(rng.choice(flags) for _ in range(n)) / n for _ in range(iters))
    return (round(means[int(0.025 * iters)], 3),
            round(means[int(0.975 * iters)], 3))


def aggregate(results: list[ProbeResult]) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for arm in sorted({r.arm for r in results}):
        rows = [r for r in results if r.arm == arm]
        flags = [r.correct for r in rows]
        ci_lo, ci_hi = bootstrap_ci(flags)
        arms[arm] = {
            "n": len(rows),
            "correct": sum(flags),
            "accuracy": round(sum(flags) / len(rows), 3) if rows else None,
            "ci95": [ci_lo, ci_hi],
            "mean_context_bpe": (round(sum(r.context_bpe for r in rows)
                                       / len(rows)) if rows else 0),
            "by_kind": {
                k: {"n": len(sub), "correct": sum(r.correct for r in sub)}
                for k in sorted({r.kind for r in rows})
                for sub in [[r for r in rows if r.kind == k]]
            },
        }
    return arms


def fork_unlock(results: list[ProbeResult]) -> "Optional[dict[str, Any]]":
    """Paired nowarn→warn analysis for the drift-fork unlock claim.

    Thresholds are pinned in PREREGISTRATION-resume-probe.md A3 and read
    off scored runs only — this just reports them next to the data. b =
    probes the warning fixed (nowarn miss → warn pass), c = probes it
    broke; exact one-sided McNemar on b vs Binomial(b+c, 1/2)."""
    by_pid: "dict[str, dict[str, bool]]" = {}
    for r in results:
        if r.arm in ("ctx-nowarn", "ctx-warn"):
            by_pid.setdefault(r.probe_id, {})[r.arm] = r.correct
    pairs = [(v["ctx-nowarn"], v["ctx-warn"]) for v in by_pid.values()
             if "ctx-nowarn" in v and "ctx-warn" in v]
    if not pairs:
        return None
    n = len(pairs)
    nowarn_miss = sum(1 for nw, _ in pairs if not nw) / n
    warn_miss = sum(1 for _, w in pairs if not w) / n
    b = sum(1 for nw, w in pairs if not nw and w)
    c = sum(1 for nw, w in pairs if nw and not w)
    m = b + c
    p = (sum(math.comb(m, k) for k in range(b, m + 1)) / (2 ** m)
         if m else None)
    return {
        "n_pairs": n,
        "nowarn_miss_rate": round(nowarn_miss, 3),
        "warn_miss_rate": round(warn_miss, 3),
        "mcnemar_b_warn_fixed": b,
        "mcnemar_c_warn_broke": c,
        "mcnemar_p_one_sided": round(p, 4) if p is not None else None,
        "unlock_rule": ("build gist surfacing + possible_conflict emission "
                        "iff nowarn_miss_rate >= 0.40 and warn_miss_rate "
                        "<= 0.10 and p < 0.05 (pre-registered A3; scored "
                        "runs only)"),
        "unlock": bool(nowarn_miss >= 0.40 and warn_miss <= 0.10
                       and p is not None and p < 0.05),
    }


def to_report(repo_path: str, probes: list[Probe],
              results: list[ProbeResult], *, seed: int,
              model: str, probe_set: str = "recall",
              gen_meta: "Optional[dict]" = None) -> dict[str, Any]:
    import datetime
    return {
        "schema": "ctxpack-resume-probe/v1",
        "measurement_class": (
            "quasi-experimental — recall accuracy for this repo's history "
            "under budget-parity arms; benchmark-grade causal claims need "
            "CompactBench"),
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "repo": os.path.basename(os.path.normpath(repo_path)),
        "config": {"seed": seed, "model": model, "n_probes": len(probes),
                   "probe_set": probe_set,
                   "ctx_arm": CTX_ARM_VERSION,
                   "arm_notes": (
                       "ctx arm v2 adds the source session's banked-"
                       "literals view (`ctxpack session literals`) to the "
                       "context — the pre-registered 2026-07-05 fix for "
                       "the baseline arm under-modeling the real read "
                       "path (baseline files carry no ctx_arm field = "
                       "v1). Probe universe is regenerated from the "
                       "current ledger, which has grown since baseline — "
                       "per-kind accuracy, not per-probe pairing, is the "
                       "cross-run comparator."),
                   "literal_disambiguation": LITERAL_DISAMBIGUATION,
                   "disambiguation_notes": (
                       "literal probes whose source turn banks more than "
                       "one distinct same-kind value are skipped at "
                       "generation — the question is degenerate, not the "
                       "arm (pre-registered 2026-07-06, amendment A2 in "
                       "PREREGISTRATION-resume-probe.md; applies to all "
                       "arms symmetrically). Files without this field "
                       "predate the rule; no prior result is regraded."),
                   **({"ambiguous_literals_skipped":
                       gen_meta.get("ambiguous_literals_skipped", 0)}
                      if gen_meta is not None else {}),
                   "grading_notes": (
                       "drift probes pass only when the answer contains a "
                       "verbatim anchor of the conflicting prior that is "
                       "never shown in the proposal; paraphrased flags "
                       "grade as misses (uniform under-count, favors arms "
                       "holding verbatim text). automem arm context is "
                       "built solely from the repo's auto-memory files — "
                       "isolation from ctx artifacts is by construction "
                       "in this no-tools harness. Known asymmetry: the "
                       "probe universe is ledger-derived (the only "
                       "deterministic ground truth with provenance), so "
                       "facts only automem holds are never probed — "
                       "automem results measure its coverage OF banked "
                       "facts, not its total knowledge.")},
        "arms": aggregate(results),
        "probes": [asdict(p) for p in probes],
        "results": [asdict(r) for r in results],
    }
