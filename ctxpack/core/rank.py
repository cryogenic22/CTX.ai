"""rank/v1 — deterministic event-sourced salience fold.

Contract (docs/spec-v1.1-fact-substrate.md §6): rank = fold(events,
policy). The fold consumes ctx-events/v1 rows ONLY — never ledger prose,
never the live session — so any policy can be A/B-tested offline against
the same event log. Content never moves; only rank does.

rank/v1-event-fold signals (everything deterministically present in the
log today, nothing more):

- priors: fact kind × extraction basis × decision-marker word × literal
  kind. ``inferred`` is the only basis allowed to be wrong about whether
  a fact exists at all, so it halves the DECISION prior — and only the
  DECISION prior: the measured over-extraction (KP_SDLC fixture labels,
  dogfood day-1 parser bugs) is exclusively decision-verb junk, while
  FAILED-APPROACH's verb pattern is the documented dead-end convention.
  The alias decision markers (verdict/conclusion/confirmed) are
  self-assessments, a weaker commitment than the canonical
  ``Decision:``.
- cross-session re-assertion: the same fact_id asserted by more than one
  session is load-bearing. Capped — no rich-get-richer (spec §6 guard).
- incident links: a ctx-incident row that resolved to a fact_id is a
  signed signal for exactly that fact (spec §8) — saved/missed raise it
  (the fact mattered), stale/wrong/user-corrected demote it. Capped
  both ways.
- recency: a strict tie-breaker (≤ RECENCY_EPSILON, smaller than any
  prior gap) — never a ranking force.

Floors are part of the policy: CONSTRAINT facts never fold below
CONSTRAINT_FLOOR — a demoted constraint is still a constraint.

Eval exclusion (ratified non-negotiable #4): rows whose transcript-
derived ``cwd`` differs from the ledger's project root are benchmark /
harness traffic and are skipped by default. Rows predating the cwd
stamp are kept — a missing stamp is not evidence of eval traffic.

Missing detail fields (rows emitted by older checkpoints) fold at
neutral multipliers: the policy never punishes a fact for having been
extracted before a field existed.

Within-session re-mention counting is deliberately absent (rank/v2
material): the transcript parser banks entities first-wins with a
single source, so the event log carries one assertion per fact per
session.
"""

from __future__ import annotations

import json
import os
from typing import Iterable, Mapping, Optional

from . import factid

RANK_POLICY_V0 = factid.RANK_POLICY          # "rank/v0-static-priors"
RANK_POLICY_V1 = "rank/v1-event-fold"
DEFAULT_RANK_POLICY = RANK_POLICY_V1
_KNOWN_POLICIES = (RANK_POLICY_V0, RANK_POLICY_V1)

KIND_PRIOR = {
    "CONSTRAINT": 3.0,
    "DECISION": 2.4,
    "FAILED-APPROACH": 2.2,
    "INCIDENT": 2.0,
    "LITERAL": 1.8,
    "USER-REQUEST": 1.2,
    "TASK": 1.2,
    "ERROR": 1.0,
    "FILE": 1.0,
}
DEFAULT_PRIOR = 1.0

# Rows emitted before 2026-07-05 truncated the kind at the first hyphen.
_LEGACY_KIND = {"FAILED": "FAILED-APPROACH", "USER": "USER-REQUEST"}

# Applied to DECISION only — the one kind with measured verb-pattern
# over-extraction. Every structurally anchored basis folds at 1.0.
_BASIS_MULT = {"inferred": 0.5}
_MARKER_MULT = {
    "decision": 1.0,
    "verdict": 0.7,
    "conclusion": 0.7,
    "confirmed": 0.7,
}
_LITERAL_KIND_MULT = {
    "git_sha": 1.0,
    "version": 1.0,
    "url": 1.0,
    "pr": 1.0,
    "path": 0.9,
    "number_unit": 0.7,
}

REASSERT_BOOST = 0.2   # per additional asserting session
REASSERT_CAP = 1.0
_INCIDENT_DELTA = {
    "saved": 0.5,
    "missed": 0.5,          # the fact was needed and unreachable — demand
    "user-corrected": -1.0,
    "stale": -1.0,
    "wrong": -1.5,
    "conflicting": -0.5,
    "native-better": -0.25,
}
INCIDENT_CAP = (-2.0, 1.0)
CONSTRAINT_FLOOR = 2.5
RECENCY_EPSILON = 0.01


def resolve_policy(env: Optional[Mapping[str, str]] = None) -> str:
    """Active rank policy: CTXPACK_RANK_POLICY when it names a known
    policy, else the default. Fail-open on unknown values — a typo in a
    hook environment must never break a checkpoint."""
    value = (env or os.environ).get("CTXPACK_RANK_POLICY", "").strip()
    return value if value in _KNOWN_POLICIES else DEFAULT_RANK_POLICY


def load_events(path: str) -> list:
    """Parse events.jsonl rows in file order; malformed lines are
    skipped (the fold's input contract is best-effort, its output is
    deterministic for a given file)."""
    rows: list = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def prior_for(kind: str, basis: str = "", marker: str = "",
              literal_kind: str = "") -> float:
    """Static prior for one fact — the fold's starting point, exposed so
    consumers can score facts that predate the event log."""
    kind = _LEGACY_KIND.get(str(kind or ""), str(kind or ""))
    p = KIND_PRIOR.get(kind, DEFAULT_PRIOR)
    if kind == "DECISION":
        p *= _BASIS_MULT.get(str(basis or ""), 1.0)
        p *= _MARKER_MULT.get(str(marker or ""), 1.0)
    elif kind == "LITERAL":
        p *= _LITERAL_KIND_MULT.get(str(literal_kind or ""), 1.0)
    return p


def fold_events(rows: Iterable[dict], *,
                policy: str = DEFAULT_RANK_POLICY,
                project_root: str = "") -> "dict[str, float]":
    """Fold event rows into {fact_id: salience}.

    rank/v0 returns {} — static priors mean no event-derived movement,
    and consumers keep their pre-fold behavior byte-for-byte (the A/B
    baseline). Unknown policies raise: a fold that silently guessed its
    policy would poison every offline comparison.
    """
    if policy == RANK_POLICY_V0:
        return {}
    if policy != RANK_POLICY_V1:
        raise ValueError(f"unknown rank policy: {policy!r}")

    root = _norm_path(project_root) if project_root else ""
    kept: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        cwd = str(r.get("cwd") or "")
        if cwd and root and _norm_path(cwd) != root:
            continue  # eval / foreign-workspace traffic
        kept.append(r)

    total = len(kept)
    prior: "dict[str, float]" = {}
    kind_of: "dict[str, str]" = {}
    sessions: "dict[str, set]" = {}
    last_index: "dict[str, int]" = {}
    incident_seen: set = set()
    incident_delta: "dict[str, float]" = {}

    for i, r in enumerate(kept):
        fid = r.get("fact_id")
        detail = r.get("detail") or {}
        event = r.get("event")
        if event == "fact_asserted" and fid:
            if fid not in prior:
                kind = _LEGACY_KIND.get(str(detail.get("kind") or ""),
                                        str(detail.get("kind") or ""))
                prior[fid] = prior_for(
                    kind,
                    basis=str(detail.get("basis") or ""),
                    marker=str(detail.get("marker") or ""),
                    literal_kind=str(detail.get("literal_kind") or ""))
                kind_of[fid] = kind
            sessions.setdefault(fid, set()).add(str(r.get("session") or ""))
            last_index[fid] = i
        elif event == "incident" and fid:
            # incidents re-emit at every checkpoint — dedup by identity
            iid = str(detail.get("incident_id") or "")
            if iid and (iid, fid) in incident_seen:
                continue
            incident_seen.add((iid, fid))
            incident_delta[fid] = (incident_delta.get(fid, 0.0)
                                   + _INCIDENT_DELTA.get(
                                       str(detail.get("type") or ""), 0.0))

    lo, hi = INCIDENT_CAP
    scores: "dict[str, float]" = {}
    for fid, p in prior.items():
        boost = min(REASSERT_CAP,
                    REASSERT_BOOST * max(0, len(sessions.get(fid, ())) - 1))
        delta = min(hi, max(lo, incident_delta.get(fid, 0.0)))
        eps = (RECENCY_EPSILON * (last_index[fid] / (total - 1))
               if total > 1 else 0.0)
        score = p + boost + delta + eps
        if kind_of.get(fid) == "CONSTRAINT":
            score = max(score, CONSTRAINT_FLOOR)
        scores[fid] = round(score, 6)
    return scores
