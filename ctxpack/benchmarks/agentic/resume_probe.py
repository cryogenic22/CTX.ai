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
    kind: str              # literal | decision | constraint | superseded
    session: str           # sid8 the fact came from
    turn: int
    question: str
    expected: str          # the graded string
    grade_mode: str        # exact | contains
    source_text: str = ""  # full fact, for the report


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


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("`", " ").replace('"', " ")
                    .replace("**", " ").split())


def probe_candidates(ledger_dir: str, sid: str) -> list[Probe]:
    """Deterministic probe candidates from one session's ledger."""
    doc, sid = load_session(ledger_dir, sid)
    out: list[Probe] = []
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
            out.append(Probe(
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
    return out


def generate_probes(ledger_dir: str, n: int = 20,
                    seed: int = 42) -> list[Probe]:
    """Seeded, type-stratified sample across every session in the ledger."""
    _, latest_path = resolve_session(ledger_dir)
    sids = sorted(
        os.path.basename(p)[len("session-"):-len(".ctx")]
        for p in glob.glob(os.path.join(ledger_dir, "session-*.ctx")))
    pool: list[Probe] = []
    for sid in sids:
        try:
            pool.extend(probe_candidates(ledger_dir, sid))
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


def ctx_context(ledger_dir: str, probe: Probe, max_sections: int = 3) -> str:
    """The hooks' view: startup gists + keyword-hydrated ledger sections."""
    parts = [read_startup_context(ledger_dir)]
    try:
        doc, _ = load_session(ledger_dir, probe.session)
        result = hydrate_by_query(doc, probe.question,
                                  max_sections=max_sections,
                                  include_header=False)
        for s in result.sections:
            parts.extend(serialize_section(s, natural_language=True))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(p for p in parts if p)


_GREP_WINDOW = 800  # chars around a hit — what `grep -o -C` style use shows
_QUOTED_RE = re.compile(r'"([^"]{12,})"')


def grep_context(repo_path: str, probe: Probe, budget_bpe: int) -> str:
    """Null hypothesis: keyword-matched windows over the raw transcript,
    budget-parity with the CTX arm for the same probe.

    Modeled on what a competent agent actually does, not a strawman:
    (1) grep the exact quoted phrase from the question first, (2) then
    rank keyword windows by how many DISTINCT rare terms they contain —
    transcript lines are huge JSON blobs, so windows are cut around the
    match (grep -C style), never line prefixes. Terms include ground-
    truth words from the probed fact, which over-powers this arm — the
    conservative direction for any claim where CTX still wins."""
    transcript = find_transcript(repo_path, probe.session)
    if not transcript:
        return ""
    phrases = [m.group(1).rstrip(" .").lower()
               for m in _QUOTED_RE.finditer(probe.question)]
    terms = [w.lower() for w in
             _distinctive_words(probe.question + " " + probe.source_text, 10)]
    scored: list[tuple[int, int, str]] = []  # (-score, order, window)
    order = 0
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
        return ""
    scored.sort()
    out: list[str] = []
    for _, _, window in scored:
        out.append(window)
        if count_bpe_tokens("\n".join(out), model="claude") > budget_bpe:
            out.pop()
            break
    return "\n".join(out)


# ── Grading (rule-based; no LLM judge in the headline) ──


def grade(probe: Probe, answer: str) -> bool:
    if not answer or answer.startswith("(error:"):
        return False
    a = _norm(answer)
    e = _norm(probe.expected)
    if probe.grade_mode == "exact":
        return e in a
    return e in a  # contains — expected is already a distinctive phrase


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


def to_report(repo_path: str, probes: list[Probe],
              results: list[ProbeResult], *, seed: int,
              model: str) -> dict[str, Any]:
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
        "config": {"seed": seed, "model": model, "n_probes": len(probes)},
        "arms": aggregate(results),
        "probes": [asdict(p) for p in probes],
        "results": [asdict(r) for r in results],
    }
