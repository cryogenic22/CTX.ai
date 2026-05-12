"""CP-019/020 — Weighted PageRank + centrality_prior population.

Power-iteration PageRank over the static call graph (CP-014 edges).
Edge weighting:

- Plain ``caller → callee`` carries weight 1.
- ``test_caller → callee`` (where ``test_node_predicate(caller)`` is
  True) carries weight 3 — tests are stronger evidence of importance.
- Export pins (declared callers from elsewhere in the codebase) get
  a damping bonus; deferred to the cross-module ranker work in v0.1,
  not in this MVP pass.

Tie-breaking on identical scores is alphabetical by node name so the
output dict iterates deterministically, satisfying §8.6.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable, Optional

from ctxpack.core.code.callgraph import CallEdge
from ctxpack.core.packer.ir import IREntity


_DEFAULT_DAMPING = 0.85
_DEFAULT_ITERATIONS = 30


def compute_pagerank(
    nodes: set[str],
    edges: Iterable[CallEdge],
    *,
    test_edges_weight: float = 3.0,
    damping: float = _DEFAULT_DAMPING,
    iterations: int = _DEFAULT_ITERATIONS,
    test_node_predicate: Optional[Callable[[str], bool]] = None,
) -> dict[str, float]:
    """Return ``{node: score}`` summing to 1.0.

    Nodes with no outgoing edges distribute their weight uniformly
    (the standard dangling-node trick) so the total mass is preserved.
    """
    node_list = sorted(nodes)
    n = len(node_list)
    if n == 0:
        return {}
    idx = {node: i for i, node in enumerate(node_list)}

    # Build weighted out-edges. Test-caller boost is modelled as the
    # caller having more "personal mass" to distribute: a test caller
    # is treated as if it had `test_edges_weight` times as much score
    # to push through. This survives the out-weight-normalisation that
    # would otherwise cancel any per-edge weighting when a source has
    # only one out-edge.
    out_edges: dict[int, list[int]] = defaultdict(list)
    caller_boost: list[float] = [1.0] * n
    for i, node in enumerate(node_list):
        if test_node_predicate is not None and test_node_predicate(node):
            caller_boost[i] = test_edges_weight
    for edge in edges:
        if edge.caller not in idx or edge.callee not in idx:
            continue
        out_edges[idx[edge.caller]].append(idx[edge.callee])

    # Power iteration. Each iteration propagates each node's score
    # times its caller boost; we renormalise at the end so total mass
    # stays at 1.
    scores = [1.0 / n] * n
    base = (1.0 - damping) / n
    for _ in range(iterations):
        new_scores = [base] * n
        dangling = 0.0
        for i in range(n):
            outs = out_edges[i]
            if not outs:
                dangling += scores[i] * caller_boost[i]
                continue
            share = damping * scores[i] * caller_boost[i] / len(outs)
            for j in outs:
                new_scores[j] += share
        # Dangling mass redistributed uniformly.
        if dangling:
            spread = damping * dangling / n
            for j in range(n):
                new_scores[j] += spread
        # Renormalise so the boost doesn't inflate total mass.
        total = sum(new_scores)
        if total > 0:
            new_scores = [s / total for s in new_scores]
        scores = new_scores

    # Normalise to sum=1 (power iteration drifts slightly numerically).
    total = sum(scores)
    if total > 0:
        scores = [s / total for s in scores]

    return {node_list[i]: scores[i] for i in range(n)}


def populate_centrality_prior(
    entities: list[IREntity],
    scores: dict[str, float],
) -> None:
    """Update each entity's ``centrality_prior`` IRField in place.

    Missing scores leave the field at its current value. Idempotent —
    re-running with the same scores produces the same field values.
    """
    for ent in entities:
        score = scores.get(ent.name)
        if score is None:
            continue
        for fld in ent.fields:
            if fld.key == "centrality_prior":
                fld.value = f"{score:.6f}"
                break
        else:
            # No existing centrality_prior field — append one (shouldn't
            # happen for entities emitted by CP-010, but defensive).
            from ctxpack.core.layers import ContextLayer
            from ctxpack.core.packer.ir import IRField
            ent.fields.append(
                IRField(
                    key="centrality_prior",
                    value=f"{score:.6f}",
                    layer=ContextLayer.RULES,
                    confidence=1.0,
                )
            )
