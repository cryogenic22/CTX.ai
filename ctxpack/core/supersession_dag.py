"""Supersession DAG — a deterministic fold over the supersession edges
already in ``events.jsonl``. No new capture, no write path, no memory
rewrite: the (base, head) edges ARE the existing ``fact_superseded``
events (base = the event's ``fact_id``, head = its ``by``).

Motivation. Today supersession is a flat set of edges consumed only for
rank demotion (``rank.py``: a superseded fact loses 1.0 and stops
competing for the gist). A flat set cannot tell a LINEAR REVISION
(A→B→C, current = C) apart from a BRANCH CONFLICT (A independently
superseded by both B and C, neither referencing the other — two
competing current values). The first is resolved and should collapse to
its tip; the second is an UNRESOLVED FORK and must be surfaced, never
silently collapsed to "A is superseded".

Contract (docs/spec-v1.1 §4, supersession DAG):
- current   : a fact nothing supersedes — a live head of its lineage.
- superseded: a fact some edge supersedes — it appears as an edge base.
- conflict  : a lineage (a connected fact family under the supersession
              relation) with ≥2 live heads not reconciled by a later
              fact superseding both — an unresolved fork, surfaced as a
              ``possible_conflict`` candidate (heads = the competing
              current values).

Pure functions, zero dependencies, sorted outputs: same events, same
graph, forever. This slice is read-only derivation — it does not touch
the checkpoint write path or the events schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class SupersessionEdge:
    """head supersedes base (the DAG points old → new)."""

    base: str
    head: str
    turn: int = -1
    reason: str = ""
    session: str = ""


@dataclass(frozen=True)
class Conflict:
    """An unresolved supersession fork: one lineage, ≥2 live heads."""

    roots: "list[str]"   # oldest fact(s) of the family — superseded, never a head
    heads: "list[str]"   # the competing current values
    facts: "list[str]"   # every fact_id in the family


@dataclass(frozen=True)
class SupersessionGraph:
    heads: "list[str]"          # current tips of every superseded lineage
    superseded: "list[str]"     # facts an edge supersedes
    conflicts: "list[Conflict]"

    def status_of(self, fact_id: str) -> str:
        """current | superseded — for facts inside a superseded lineage.

        Facts never involved in supersession are not in the graph; treat
        them as current by construction (nothing supersedes them)."""
        return "superseded" if fact_id in set(self.superseded) else "current"


def edges_from_events(events: Iterable[dict[str, Any]]) -> "list[SupersessionEdge]":
    """Extract supersession edges from a fold of event rows. Only
    ``fact_superseded`` (declared ``Supersedes:`` overrides) carries a
    base→head pair that can fork; self-loops and blank ids are dropped.

    Row schema is ctx-events/v1 (checkpoint.py ``ev``): the target is the
    top-level ``fact_id`` and the payload — the superseding fact ``by``
    and the ``reason`` — lives under ``detail``. Reading ``by``/``reason``
    at the top level silently yields zero edges on real ledgers."""
    out: "list[SupersessionEdge]" = []
    for e in events:
        if e.get("event") != "fact_superseded":
            continue
        detail = e.get("detail") or {}
        base = str(e.get("fact_id", "") or "")
        head = str(detail.get("by", "") or "")
        if not base or not head or base == head:
            continue
        raw_turn = e.get("turn")
        try:
            turn = int(raw_turn) if raw_turn is not None else -1
        except (TypeError, ValueError):
            turn = -1
        out.append(SupersessionEdge(
            base=base, head=head, turn=turn,
            reason=str(detail.get("reason", ""))[:200],
            session=str(e.get("session", "") or "")))
    return out


def build_graph(edges: Iterable[SupersessionEdge]) -> SupersessionGraph:
    """Fold edges into families and classify each lineage's live heads.

    A family is a connected component under the (undirected) supersession
    relation. A fact is a *live head* if no edge supersedes it (it never
    appears as a base). A family with one live head is resolved (linear
    chain or diamond reconciled by a later fact); a family with ≥2 live
    heads is an unresolved fork."""
    edges = list(edges)
    bases = {e.base for e in edges}
    heads_seen = {e.head for e in edges}
    facts = bases | heads_seen

    # Union-find over the undirected relation → fact families. Roots are
    # chosen deterministically (min id) so the fold is replay-stable.
    parent: "dict[str, str]" = {f: f for f in facts}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for e in edges:
        union(e.base, e.head)

    families: "dict[str, set[str]]" = {}
    for f in facts:
        families.setdefault(find(f), set()).add(f)

    live_heads = facts - bases                 # nothing supersedes them
    origins = facts - heads_seen               # never supersede anything
    conflicts: "list[Conflict]" = []
    for root in sorted(families):
        members = families[root]
        family_heads = sorted(members & live_heads)
        if len(family_heads) >= 2:
            conflicts.append(Conflict(
                roots=sorted(members & origins),
                heads=family_heads,
                facts=sorted(members)))

    return SupersessionGraph(
        heads=sorted(live_heads),
        superseded=sorted(bases),
        conflicts=conflicts)


def fact_view(fact_id: str, edges: Iterable[SupersessionEdge],
              graph: SupersessionGraph) -> "Optional[dict[str, Any]]":
    """Per-fact supersession view for the read path — status, the edges
    the fact participates in (each with turn/reason/session provenance),
    and its unresolved fork if the fold found one.

    Returns ``None`` when the fact is in no edge and no conflict: a fact
    outside every superseded lineage has nothing to surface, so the read
    path stays boring rather than stamping "current" on everything."""
    edges = list(edges)
    supersedes = sorted(
        ({"fact_id": e.base, "turn": e.turn, "reason": e.reason,
          "session": e.session} for e in edges if e.head == fact_id),
        key=lambda d: (d["turn"], d["fact_id"]))
    superseded_by = sorted(
        ({"fact_id": e.head, "turn": e.turn, "reason": e.reason,
          "session": e.session} for e in edges if e.base == fact_id),
        key=lambda d: (d["turn"], d["fact_id"]))
    conflict = next((c for c in graph.conflicts if fact_id in c.facts), None)
    if not supersedes and not superseded_by and conflict is None:
        return None
    return {
        "fact_id": fact_id,
        "status": graph.status_of(fact_id),
        "supersedes": supersedes,
        "superseded_by": superseded_by,
        "conflict": ({"roots": conflict.roots, "heads": conflict.heads,
                      "facts": conflict.facts} if conflict else None),
    }
