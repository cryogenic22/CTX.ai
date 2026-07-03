"""Entity Relationship Graph — Multi-Hop Traversal.

Builds a lightweight, in-memory graph from entity cross-references in a
CTXDocument. Enables multi-hop needle-finding: given a starting entity,
discover all related entities within N hops.

This addresses the "5 needles in a haystack" problem for cross-entity
questions. Instead of the LLM guessing which entities are related, the
graph traverses relationships extracted during packing.

Zero dependencies. The graph is a Python dict of sets.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any

from .model import CTXDocument, KeyValue, Section


# Relationship keys that indicate entity cross-references
_RELATIONSHIP_KEYS = {
    "HAS-MANY", "HAS-ONE", "BELONGS-TO", "REFERENCES", "DEPENDS-ON",
    "RELATIONSHIPS",
}

# Regex to extract @ENTITY-NAME references from values
_ENTITY_REF_RE = re.compile(r"@(ENTITY-[\w-]+)")

# Regex to extract target(EntityName) from compressed relationship notation
# Matches: target(Order), target(Customer), target(MerchantStore)
_TARGET_RE = re.compile(r"target\(([A-Z][\w-]*)\)", re.IGNORECASE)


class EntityGraph:
    """Lightweight entity relationship graph.

    Nodes are entity section names (e.g., "ENTITY-CUSTOMER").
    Every extracted reference is stored twice:

    - undirected (``_adjacency``) — the original view; neighbors/traverse/
      path keep their historical semantics
    - directed (``_out``/``_in``) — reference direction: the section that
      states ``DEPENDS-ON: @ENTITY-X`` gets an out-edge to X, and X gains
      the in-edge. ``parents(X)`` ("who depends on X") is the reverse-
      dependency query in-context reasoning fails at first (GraphWalks
      eval: RAW drops to 0.78-0.82 on it while the tool path is exact).
    """

    def __init__(self) -> None:
        self._adjacency: dict[str, set[str]] = {}
        self._out: dict[str, set[str]] = {}
        self._in: dict[str, set[str]] = {}

    @classmethod
    def from_document(cls, doc: CTXDocument) -> "EntityGraph":
        """Build graph from a CTXDocument by scanning for @ENTITY-X references."""
        graph = cls()

        for elem in doc.body:
            if not isinstance(elem, Section):
                continue
            if not elem.name.startswith("ENTITY-"):
                continue

            source = elem.name
            graph._ensure_node(source)

            # Scan all KV children for cross-references
            for child in elem.children:
                if isinstance(child, KeyValue):
                    # Pattern 1: @ENTITY-X references
                    refs = _ENTITY_REF_RE.findall(child.value)
                    for ref in refs:
                        graph._add_edge(source, ref)

                    # Pattern 2: target(EntityName) in compressed notation
                    if child.key in _RELATIONSHIP_KEYS or child.key == "RELATIONSHIPS":
                        targets = _TARGET_RE.findall(child.value)
                        for target in targets:
                            # Normalize: "Order" -> "ENTITY-ORDER"
                            normalized = target.upper().replace(" ", "-").replace("_", "-")
                            if not normalized.startswith("ENTITY-"):
                                normalized = f"ENTITY-{normalized}"
                            graph._add_edge(source, normalized)

        return graph

    @property
    def entities(self) -> set[str]:
        """All entity names in the graph."""
        return set(self._adjacency.keys())

    def neighbors(self, entity: str) -> set[str]:
        """Direct neighbors of an entity (depth=1)."""
        return set(self._adjacency.get(entity, set()))

    def traverse(self, entity: str, *, depth: int = 1) -> set[str]:
        """BFS traversal: all entities reachable within N hops.

        Returns a set of entity names, excluding the start entity.
        Handles cycles safely via visited tracking.
        """
        if entity not in self._adjacency:
            return set()

        visited: set[str] = {entity}
        queue: deque[tuple[str, int]] = deque([(entity, 0)])

        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            for neighbor in self._adjacency.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, current_depth + 1))

        visited.discard(entity)  # Exclude start node
        return visited

    def path(self, from_entity: str, to_entity: str) -> list[str]:
        """Shortest path between two entities (BFS).

        Returns list of entity names from source to target (inclusive).
        Returns empty list if no path exists.
        Returns [entity] if from == to.
        """
        if from_entity == to_entity:
            return [from_entity]

        if from_entity not in self._adjacency or to_entity not in self._adjacency:
            return []

        visited: set[str] = {from_entity}
        queue: deque[list[str]] = deque([[from_entity]])

        while queue:
            current_path = queue.popleft()
            current = current_path[-1]

            for neighbor in self._adjacency.get(current, set()):
                if neighbor == to_entity:
                    return current_path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(current_path + [neighbor])

        return []

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph for JSON export or L3 enrichment."""
        return {
            "entities": sorted(self._adjacency.keys()),
            "edges": {
                entity: sorted(neighbors)
                for entity, neighbors in sorted(self._adjacency.items())
                if neighbors
            },
            "entity_count": len(self._adjacency),
            "edge_count": sum(len(n) for n in self._adjacency.values()) // 2,
        }

    # ── Directed API ──

    def children(self, entity: str) -> set[str]:
        """Out-neighbors: what this entity references / depends on."""
        return set(self._out.get(entity, set()))

    def parents(self, entity: str) -> set[str]:
        """In-neighbors: who references / depends on this entity."""
        return set(self._in.get(entity, set()))

    def traverse_directed(self, entity: str, *, depth: int = 1,
                          direction: str = "out") -> set[str]:
        """BFS over directed edges. direction: 'out' (dependencies),
        'in' (dependents), or 'both' (== undirected traverse)."""
        adj = {"out": self._out, "in": self._in,
               "both": self._adjacency}.get(direction)
        if adj is None:
            raise ValueError(f"direction must be out|in|both, got {direction!r}")
        if entity not in self._adjacency:
            return set()
        visited: set[str] = {entity}
        queue: deque[tuple[str, int]] = deque([(entity, 0)])
        while queue:
            current, d = queue.popleft()
            if d >= depth:
                continue
            for neighbor in adj.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, d + 1))
        visited.discard(entity)
        return visited

    def path_directed(self, from_entity: str, to_entity: str) -> list[str]:
        """Shortest path following out-edges only (dependency direction)."""
        if from_entity == to_entity:
            return [from_entity]
        if from_entity not in self._adjacency or to_entity not in self._adjacency:
            return []
        visited: set[str] = {from_entity}
        queue: deque[list[str]] = deque([[from_entity]])
        while queue:
            current_path = queue.popleft()
            for neighbor in self._out.get(current_path[-1], set()):
                if neighbor == to_entity:
                    return current_path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(current_path + [neighbor])
        return []

    def query(self, op: str, entity: str, *, to: str = "",
              depth: int = 2, direction: str = "out") -> dict[str, Any]:
        """Deterministic graph query — the ctx/graph_query contract.

        ops: neighbors | parents | bfs | path. O(V+E), zero model tokens:
        the answer is computed over packed structure, not inferred.
        """
        entity = self.normalize(entity)
        if entity not in self._adjacency:
            return {"op": op, "entity": entity, "error": "unknown_entity",
                    "known_entities": len(self._adjacency)}
        if op == "neighbors":
            return {"op": op, "entity": entity,
                    "out": sorted(self._out.get(entity, set())),
                    "in": sorted(self._in.get(entity, set())),
                    "undirected": sorted(self._adjacency.get(entity, set()))}
        if op == "parents":
            return {"op": op, "entity": entity,
                    "parents": sorted(self.parents(entity))}
        if op == "bfs":
            return {"op": op, "entity": entity, "depth": depth,
                    "direction": direction,
                    "reachable": sorted(self.traverse_directed(
                        entity, depth=depth, direction=direction))}
        if op == "path":
            target = self.normalize(to)
            if not target:
                return {"op": op, "entity": entity,
                        "error": "path requires 'to'"}
            found = (self.path_directed(entity, target)
                     if direction == "out" else self.path(entity, target))
            return {"op": op, "entity": entity, "to": target,
                    "direction": direction, "path": found,
                    "found": bool(found)}
        return {"op": op, "entity": entity,
                "error": "op must be neighbors|parents|bfs|path"}

    @staticmethod
    def normalize(entity: str) -> str:
        """'order db' / 'Order_DB' → 'ENTITY-ORDER-DB'."""
        if not entity:
            return ""
        norm = entity.strip().upper().replace(" ", "-").replace("_", "-")
        return norm if norm.startswith("ENTITY-") else f"ENTITY-{norm}"

    def _ensure_node(self, entity: str) -> None:
        if entity not in self._adjacency:
            self._adjacency[entity] = set()
            self._out.setdefault(entity, set())
            self._in.setdefault(entity, set())

    def _add_edge(self, a: str, b: str) -> None:
        """Record a→b directed (reference direction) + undirected view."""
        self._ensure_node(a)
        self._ensure_node(b)
        self._adjacency[a].add(b)
        self._adjacency[b].add(a)
        self._out[a].add(b)
        self._in[b].add(a)
