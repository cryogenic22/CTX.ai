"""L3 (Gist) generator — deterministic extraction from L2 AST.

L3 is the ultra-compressed layer (<500 tokens) with sections:
  ENTITIES, TOPOLOGY, PATTERNS, CONSTRAINTS, WARNINGS

No LLM in the loop — preserves the zero-dependency property.
"""

from __future__ import annotations

import datetime
import re

from ..errors import Span
from ..model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    PlainLine,
    Section,
)
from ..packer.ir import CONDITIONAL_RE, WINDOW_RE
from .compressor import count_tokens

# Regex for cross-ref extraction
_CROSSREF_RE = re.compile(r"@ENTITY-(\w[\w-]*)")

# Token budget for L3
_L3_TOKEN_BUDGET = 500

# Topology classification thresholds (configurable)
# hub = entity with >= HUB_THRESHOLD inbound cross-references
# leaf = entity with 0 inbound cross-references
# bridge = everything else (1 to HUB_THRESHOLD-1 refs)
HUB_THRESHOLD = 3


def generate_l3(l2_doc: CTXDocument, *, hub_threshold: int | None = None) -> CTXDocument:
    """Generate an L3 CTXDocument from an L2 CTXDocument.

    Extracts:
    - ENTITIES: entity names + identifier types + role tags (hub/leaf/bridge)
    - TOPOLOGY: graph structure, hub entities, dependency counts
    - PATTERNS: status machines, match rules, retention, ID type distribution
    - CONSTRAINTS: fields marked ★ or ⚠, immutability rules, PII (severity sorted)
    - WARNINGS: direct copy from ⚠ lines in L2
    """
    threshold = hub_threshold if hub_threshold is not None else HUB_THRESHOLD
    entities_section = _extract_entities(l2_doc, hub_threshold=threshold)
    topology_section = _extract_topology(l2_doc, hub_threshold=threshold)
    patterns_section = _extract_patterns(l2_doc)
    constraints_section = _extract_constraints(l2_doc)
    warnings_section = _extract_warnings(l2_doc)

    body = [entities_section, topology_section, patterns_section,
            constraints_section, warnings_section]

    # Token-budget trim pass
    body = _trim_to_budget(body, _L3_TOKEN_BUDGET)

    body_tuple = tuple(body)
    ctx_tokens = count_tokens(body_tuple)

    # Pull metadata from L2 header
    domain = l2_doc.header.get("DOMAIN", "unknown")
    source_tokens = l2_doc.header.get("SOURCE_TOKENS", "~0")

    today = datetime.date.today().isoformat()
    status_fields = (
        KeyValue(key="DOMAIN", value=domain),
    )
    metadata = (
        KeyValue(key="COMPRESSED", value=today),
        KeyValue(key="SOURCE_TOKENS", value=source_tokens),
        KeyValue(key="CTX_TOKENS", value=f"~{ctx_tokens}"),
        KeyValue(key="RATIO", value=f"~{_parse_int(source_tokens) // max(ctx_tokens, 1)}x"),
    )

    header = Header(
        magic="§CTX",
        version="1.0",
        layer=Layer.L3,
        status_fields=status_fields,
        metadata=metadata,
        span=Span.lines(1, 1 + len(metadata)),
    )

    return CTXDocument(header=header, body=body_tuple)


def _extract_entities(doc: CTXDocument, *, hub_threshold: int = 3) -> Section:
    """Extract entity names, identifier types, relationships, and role tags."""
    # First compute roles for tagging
    roles = _compute_entity_roles(doc, hub_threshold=hub_threshold)

    children = []
    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_name = elem.name[len("ENTITY-"):]
            parts = [entity_name]

            role = roles.get(entity_name, "")
            if role:
                parts[0] = f"{entity_name}({role})"

            # Find identifier type
            for child in elem.children:
                if isinstance(child, KeyValue) and child.key == "IDENTIFIER":
                    parts.append(f"id:{child.value}")
                    break

            # Find relationships
            for child in elem.children:
                if isinstance(child, KeyValue) and child.key.startswith("BELONGS-TO"):
                    parts.append(f"→{child.value}")

            children.append(PlainLine(text=" | ".join(parts)))

    return Section(name="ENTITIES", children=tuple(children))


def _extract_topology(doc: CTXDocument, *, hub_threshold: int = 3) -> Section:
    """Extract graph topology: inbound refs, hub/leaf/bridge classification.

    Classification thresholds:
    - hub: >= hub_threshold inbound cross-references (default 3)
    - leaf: 0 inbound cross-references
    - bridge: 1 to hub_threshold-1 inbound cross-references
    """
    # Count inbound references per entity
    inbound: dict[str, int] = {}
    entity_names: list[str] = []

    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_name = elem.name[len("ENTITY-"):]
            entity_names.append(entity_name)
            inbound.setdefault(entity_name, 0)

            for child in elem.children:
                if isinstance(child, KeyValue):
                    for m in _CROSSREF_RE.finditer(child.value):
                        target = m.group(1)
                        if target != entity_name:
                            inbound[target] = inbound.get(target, 0) + 1

    children = []

    # Classify entities
    hubs = [name for name in entity_names if inbound.get(name, 0) >= hub_threshold]
    leaves = [name for name in entity_names if inbound.get(name, 0) == 0]
    bridges = [name for name in entity_names
               if 0 < inbound.get(name, 0) < hub_threshold and name not in hubs]

    if hubs:
        children.append(PlainLine(text=f"HUBS:{'+'.join(hubs)}"))
    if leaves:
        children.append(PlainLine(text=f"LEAVES:{'+'.join(leaves)}"))
    if bridges:
        children.append(PlainLine(text=f"BRIDGES:{'+'.join(bridges)}"))

    # Summary line
    children.append(PlainLine(
        text=f"GRAPH:{len(entity_names)}-entities,"
             f"{sum(inbound.values())}-edges"
    ))

    return Section(name="TOPOLOGY", children=tuple(children))


def _compute_entity_roles(doc: CTXDocument, *, hub_threshold: int = 3) -> dict[str, str]:
    """Compute hub/leaf/bridge role for each entity."""
    inbound: dict[str, int] = {}
    entity_names: list[str] = []

    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_name = elem.name[len("ENTITY-"):]
            entity_names.append(entity_name)
            inbound.setdefault(entity_name, 0)

            for child in elem.children:
                if isinstance(child, KeyValue):
                    for m in _CROSSREF_RE.finditer(child.value):
                        target = m.group(1)
                        if target != entity_name:
                            inbound[target] = inbound.get(target, 0) + 1

    roles: dict[str, str] = {}
    for name in entity_names:
        refs = inbound.get(name, 0)
        if refs >= hub_threshold:
            roles[name] = "hub"
        elif refs == 0:
            roles[name] = "leaf"
        else:
            roles[name] = "bridge"

    return roles


def _extract_patterns(doc: CTXDocument) -> Section:
    """Extract status machines, match rules, retention patterns, ID type distribution."""
    children = []
    seen = set()
    id_types: dict[str, int] = {}  # type → count

    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_name = elem.name[len("ENTITY-"):]
            for child in elem.children:
                if not isinstance(child, KeyValue):
                    continue
                if child.key == "STATUS-MACHINE":
                    key = f"{entity_name}:STATUS"
                    if key not in seen:
                        children.append(
                            PlainLine(text=f"{entity_name}:STATUS→{child.value}")
                        )
                        seen.add(key)
                elif child.key == "MATCH-RULES":
                    key = f"{entity_name}:MATCH"
                    if key not in seen:
                        rule_count = child.value.count(",") + 1 if child.value.startswith("[") else 1
                        children.append(
                            PlainLine(text=f"{entity_name}:MATCH({rule_count}-rules)")
                        )
                        seen.add(key)
                elif child.key == "RETENTION":
                    key = f"{entity_name}:RETENTION"
                    if key not in seen:
                        children.append(
                            PlainLine(text=f"{entity_name}:RETENTION→{child.value}")
                        )
                        seen.add(key)
                elif child.key == "IDENTIFIER":
                    # Extract type for distribution
                    m = re.search(r"\(([^,)]+)", child.value)
                    if m:
                        id_type = m.group(1).strip()
                        id_types[id_type] = id_types.get(id_type, 0) + 1

    # Add ID type distribution
    total_entities = sum(
        1 for elem in doc.body
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-")
    )
    if id_types and total_entities > 0:
        dominant = max(id_types.items(), key=lambda x: x[1])
        children.append(
            PlainLine(text=f"ID-PATTERN:{dominant[1]}/{total_entities}→{dominant[0]}")
        )

    # Extract window/tolerance patterns (±Nd, ±Nw, ±Nm)
    windows: list[str] = []
    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_name = elem.name[len("ENTITY-"):]
            for child in elem.children:
                if isinstance(child, KeyValue):
                    for m in WINDOW_RE.finditer(child.value):
                        win_key = f"{entity_name}:{child.key}"
                        if win_key not in seen:
                            unit_map = {"d": "days", "w": "weeks", "m": "months"}
                            unit = unit_map.get(m.group(2), m.group(2))
                            windows.append(f"{entity_name}:{child.key}→±{m.group(1)}{unit}")
                            seen.add(win_key)
    for w in windows:
        children.append(PlainLine(text=f"WINDOW:{w}"))

    # Extract conditional guard patterns (only-if, when, if)
    conditionals: list[str] = []
    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_name = elem.name[len("ENTITY-"):]
            for child in elem.children:
                if isinstance(child, KeyValue):
                    for m in CONDITIONAL_RE.finditer(child.value):
                        cond_key = f"{entity_name}:{child.key}"
                        if cond_key not in seen:
                            conditionals.append(
                                f"{entity_name}:{child.key}→{m.group(0)}"
                            )
                            seen.add(cond_key)
    for c in conditionals:
        children.append(PlainLine(text=f"GUARD:{c}"))

    if not children:
        children.append(PlainLine(text="(none detected)"))

    return Section(name="PATTERNS", children=tuple(children))


def _extract_constraints(doc: CTXDocument) -> Section:
    """Extract ★ fields, ⚠ fields, immutability rules, PII.

    Sorted by severity: PII > IMMUTABLE > ★ > other.
    Includes constraint density line.
    """
    # Collect with severity scores for sorting
    items: list[tuple[int, str]] = []  # (severity_score, text)

    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_name = elem.name[len("ENTITY-"):]
            for child in elem.children:
                if not isinstance(child, KeyValue):
                    continue
                if child.key in ("PII", "PII-CLASSIFICATION"):
                    items.append((
                        0,  # Highest priority
                        f"{entity_name}:{child.key}→{child.value}"
                    ))
                elif child.key == "IMMUTABLE-AFTER":
                    items.append((
                        1,
                        f"{entity_name}:IMMUTABLE-AFTER→{child.value}"
                    ))
                elif child.key.startswith("★"):
                    items.append((
                        2,
                        f"{entity_name}:{child.key}→{child.value}"
                    ))
                elif "⚠" in child.value:
                    items.append((
                        3,
                        f"{entity_name}:{child.key}→⚠{child.value}"
                    ))

    # Sort by severity
    items.sort(key=lambda x: x[0])
    children = [PlainLine(text=text) for _, text in items]

    # Add constraint density
    entity_count = sum(
        1 for elem in doc.body
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-")
    )
    if entity_count > 0:
        density = "high" if len(items) / max(entity_count, 1) > 2 else (
            "medium" if len(items) / max(entity_count, 1) > 1 else "low"
        )
        children.append(PlainLine(
            text=f"DENSITY:{density}({len(items)}-constraints/{entity_count}-entities)"
        ))

    if not children:
        children.append(PlainLine(text="(none detected)"))

    return Section(name="CONSTRAINTS", children=tuple(children))


def _extract_warnings(doc: CTXDocument) -> Section:
    """Copy warnings from L2 ⚠WARNINGS section."""
    children = []

    for elem in doc.body:
        if isinstance(elem, Section) and elem.name == "WARNINGS":
            for child in elem.children:
                if isinstance(child, PlainLine):
                    children.append(PlainLine(text=child.text))

    if not children:
        children.append(PlainLine(text="(none)"))

    return Section(name="WARNINGS", children=tuple(children))


def _trim_to_budget(body: list[Section], budget: int) -> list[Section]:
    """Trim L3 to stay within token budget.

    Drops lowest-salience lines from PATTERNS/CONSTRAINTS until within budget.
    ENTITIES, TOPOLOGY, and WARNINGS are preserved.
    """
    total = count_tokens(tuple(body))
    if total <= budget:
        return body

    # Trimmable sections: PATTERNS and CONSTRAINTS
    trimmable = {"PATTERNS", "CONSTRAINTS"}

    for section_idx in range(len(body) - 1, -1, -1):
        if total <= budget:
            break
        section = body[section_idx]
        if section.name not in trimmable:
            continue
        # Remove lines from end (lowest priority) until budget met
        children = list(section.children)
        while children and total > budget:
            removed = children.pop()
            removed_tokens = count_tokens((removed,))
            total -= removed_tokens
        if not children:
            children.append(PlainLine(text="(trimmed)"))
        body[section_idx] = Section(
            name=section.name,
            children=tuple(children),
        )

    return body


def _parse_int(s: str) -> int:
    """Parse an integer from a string like '~500'."""
    s = s.strip().lstrip("~")
    try:
        return int(s)
    except ValueError:
        return 0
