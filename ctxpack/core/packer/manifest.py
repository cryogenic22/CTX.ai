"""Generate MANIFEST.ctx from layer files.

The MANIFEST is a lightweight index pointing to all layers with
token counts, enabling progressive hydration: L3 for routing,
L2 for detail, L1 for deep-dive.

V2 additions: section index, entity index, keyword index for
query-adaptive MCP hydration.
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
from ..serializer import serialize
from .compressor import count_tokens

# Regex for cross-ref targets
_CROSSREF_RE = re.compile(r"@ENTITY-(\w[\w-]*)")


def generate_manifest(
    layers: dict[str, CTXDocument],
    *,
    domain: str = "unknown",
) -> CTXDocument:
    """Generate a MANIFEST CTXDocument from layer documents.

    Args:
        layers: Mapping of layer name (e.g. "L2", "L3") to CTXDocument.
        domain: Domain name for the manifest header.
    """
    layer_children = []
    total_tokens = 0

    for layer_name in sorted(layers.keys()):
        doc = layers[layer_name]
        text = serialize(doc)
        tokens = len(text.split())
        total_tokens += tokens
        filename = f"{layer_name}.ctx"

        layer_children.append(
            KeyValue(key=layer_name, value=f"{filename} (~{tokens} tokens)")
        )

    # Build V2 indexes from L2 document
    body_sections = [Section(name="LAYERS", children=tuple(layer_children))]

    l2_doc = layers.get("L2")
    l3_doc = layers.get("L3")

    total_l2_tokens = 0
    total_l3_tokens = 0

    if l2_doc:
        section_index = _build_section_index(l2_doc)
        if section_index:
            body_sections.append(section_index)
        total_l2_tokens = count_tokens(l2_doc.body)

        entity_index = _build_entity_index(l2_doc)
        if entity_index:
            body_sections.append(entity_index)

        keyword_index = _build_keyword_index(l2_doc)
        if keyword_index:
            body_sections.append(keyword_index)

    if l3_doc:
        total_l3_tokens = count_tokens(l3_doc.body)

    today = datetime.date.today().isoformat()
    status_fields = (
        KeyValue(key="DOMAIN", value=domain),
    )

    # Budget metadata
    source_tokens_val = "~0"
    if l2_doc:
        source_tokens_val = l2_doc.header.get("SOURCE_TOKENS", "~0")
    elif l3_doc:
        source_tokens_val = l3_doc.header.get("SOURCE_TOKENS", "~0")

    avg_section_tokens = 0
    entity_count = sum(
        1 for elem in (l2_doc.body if l2_doc else ())
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-")
    )
    if entity_count > 0 and total_l2_tokens > 0:
        avg_section_tokens = total_l2_tokens // entity_count

    metadata = (
        KeyValue(key="COMPRESSED", value=today),
        KeyValue(key="SOURCE_TOKENS", value=source_tokens_val),
        KeyValue(key="CTX_TOKENS", value=f"~{total_tokens}"),
        KeyValue(key="LAYERS", value="+".join(sorted(layers.keys()))),
        KeyValue(key="TOTAL_L2_TOKENS", value=f"~{total_l2_tokens}"),
        KeyValue(key="TOTAL_L3_TOKENS", value=f"~{total_l3_tokens}"),
        KeyValue(key="AVG_SECTION_TOKENS", value=f"~{avg_section_tokens}"),
    )

    header = Header(
        magic="§CTX",
        version="1.0",
        layer=Layer.MANIFEST,
        status_fields=status_fields,
        metadata=metadata,
        span=Span.lines(1, 1 + len(metadata)),
    )

    return CTXDocument(header=header, body=tuple(body_sections))


def _build_section_index(doc: CTXDocument) -> Section | None:
    """Build ±SECTION-INDEX: section name, token count, key list."""
    children = []
    for elem in doc.body:
        if not isinstance(elem, Section):
            continue
        tokens = count_tokens(elem.children) + 1  # +1 for section name
        keys = []
        for child in elem.children:
            if isinstance(child, KeyValue):
                keys.append(child.key)
        key_str = ",".join(keys[:8])  # Cap at 8 keys for brevity
        if len(keys) > 8:
            key_str += f",+{len(keys) - 8}"
        children.append(
            KeyValue(key=elem.name, value=f"~{tokens}tok keys:[{key_str}]")
        )

    if not children:
        return None
    return Section(name="SECTION-INDEX", children=tuple(children))


def _build_entity_index(doc: CTXDocument) -> Section | None:
    """Build ±ENTITY-INDEX: entity name → section name + token cost."""
    children = []
    for elem in doc.body:
        if isinstance(elem, Section) and elem.name.startswith("ENTITY-"):
            entity_name = elem.name[len("ENTITY-"):]
            tokens = count_tokens(elem.children) + 1
            children.append(
                KeyValue(key=entity_name, value=f"±{elem.name} ~{tokens}tok")
            )

    if not children:
        return None
    return Section(name="ENTITY-INDEX", children=tuple(children))


# Semantic tokens to extract from values (domain-relevant terms)
_SEMANTIC_RE = re.compile(
    r"\b(retention|churn|pii|pci[-_]?dss|gdpr|immutable|nullable|"
    r"cascade|encrypted?|confidential|restricted|active|inactive|"
    r"archived|deleted|pending|approved|unique|required|mandatory)\b",
    re.IGNORECASE,
)


def _build_keyword_index(doc: CTXDocument) -> Section | None:
    """Build ±KEYWORD-INDEX: top keywords per section for routing.

    Extracts three categories of keywords:
    1. Structural: KV keys (IDENTIFIER, STATUS-MACHINE, etc.)
    2. Navigational: cross-reference targets (@ENTITY-X → x)
    3. Semantic: domain-relevant terms from values (retention, churn, pii, etc.)
    """
    children = []
    for elem in doc.body:
        if not isinstance(elem, Section):
            continue
        keywords: set[str] = set()
        for child in elem.children:
            if isinstance(child, KeyValue):
                # Structural: KV key
                keywords.add(child.key.lower())
                # Navigational: cross-ref targets
                for m in _CROSSREF_RE.finditer(child.value):
                    keywords.add(m.group(1).lower())
                # Semantic: domain terms from values
                for m in _SEMANTIC_RE.finditer(child.value):
                    keywords.add(m.group(1).lower())
            elif isinstance(child, PlainLine):
                for m in _CROSSREF_RE.finditer(child.text):
                    keywords.add(m.group(1).lower())
                for m in _SEMANTIC_RE.finditer(child.text):
                    keywords.add(m.group(1).lower())
        # Add entity name itself
        if elem.name.startswith("ENTITY-"):
            keywords.add(elem.name[len("ENTITY-"):].lower())

        top_kw = sorted(keywords)[:15]  # Raised cap from 10 to 15 for semantic terms
        if top_kw:
            children.append(
                KeyValue(key=elem.name, value=",".join(top_kw))
            )

    if not children:
        return None
    return Section(name="KEYWORD-INDEX", children=tuple(children))
