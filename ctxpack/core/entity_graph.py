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
    Edges are bidirectional relationship links extracted from
    cross-references in KV values.
    """

    def __init__(self) -> None:
        self._adjacency: dict[str, set[str]] = {}

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

    def _ensure_node(self, entity: str) -> None:
        if entity not in self._adjacency:
            self._adjacency[entity] = set()

    def _add_edge(self, a: str, b: str) -> None:
        """Add bidirectional edge."""
        self._ensure_node(a)
        self._ensure_node(b)
        self._adjacency[a].add(b)
        self._adjacency[b].add(a)
