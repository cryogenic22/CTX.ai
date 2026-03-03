"""Agent state compression: compress multi-step agent traces into .ctx format.

Usage:
    from ctxpack.agent import compress_state
    result = compress_state(steps)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.model import CTXDocument
from ..core.packer.compressor import compress, count_tokens
from ..core.packer.conflict import detect_conflicts
from ..core.packer.entity_resolver import resolve_entities
from ..core.packer.ir import IRWarning
from ..core.serializer import serialize
from .state_parser import parse_steps


@dataclass
class AgentCompressResult:
    """Result of compressing agent state."""

    ctx_text: str
    document: CTXDocument
    tokens_raw: int
    tokens_compressed: int
    compression_ratio: float
    entities_merged: int
    conflicts_detected: int
    warnings: list[str] = field(default_factory=list)
    step_count: int = 0


def compress_state(
    steps: list[dict[str, Any]],
    *,
    domain: str = "agent-state",
    strict: bool = False,
    max_ratio: float = 0,
    min_tokens_per_entity: int = 0,
) -> AgentCompressResult:
    """Compress a list of agent step dicts into a .ctx document.

    Steps can contain:
    - {"entities": [{"name": "X", ...}]} — observed entities
    - {"tool": "name", "result": {...}} — tool call results
    - {"decision": "text"} — agent decisions/reasoning

    Args:
        steps: List of step dicts from an agent trace.
        domain: Domain label for the .ctx header.
        strict: Suppress inferred fields (emit only explicit facts).
        max_ratio: Maximum compression ratio (0 = no limit).
        min_tokens_per_entity: Minimum token budget per entity (0 = no limit).

    Returns:
        AgentCompressResult with compressed .ctx text and metrics.
    """
    if not steps:
        # Empty steps: return minimal result
        from ..core.model import Header, Layer

        empty_doc = CTXDocument(
            header=Header(magic="§CTX", version="1.0", layer=Layer.L2),
        )
        return AgentCompressResult(
            ctx_text=serialize(empty_doc),
            document=empty_doc,
            tokens_raw=0,
            tokens_compressed=0,
            compression_ratio=0.0,
            entities_merged=0,
            conflicts_detected=0,
            step_count=0,
        )

    # 1. Parse steps → IRCorpus
    corpus = parse_steps(steps, domain=domain)
    tokens_raw = corpus.source_token_count

    # Track pre-merge entity count
    pre_merge_count = len(corpus.entities)

    # 2. Entity resolution (merge duplicates across steps)
    resolve_entities(corpus)

    post_merge_count = len(corpus.entities)
    entities_merged = pre_merge_count - post_merge_count

    # 3. Conflict detection
    conflicts = detect_conflicts(corpus)
    corpus.warnings.extend(conflicts)

    # 4. Compress → CTXDocument
    doc = compress(
        corpus,
        strict=strict,
        max_ratio=max_ratio,
        min_tokens_per_entity=min_tokens_per_entity,
    )

    # 5. Serialize
    ctx_text = serialize(doc)
    tokens_compressed = count_tokens(doc.body)

    # Compute ratio
    ratio = tokens_raw / tokens_compressed if tokens_compressed > 0 else 0.0

    # Collect warning messages
    warning_msgs = [w.message for w in corpus.warnings]

    return AgentCompressResult(
        ctx_text=ctx_text,
        document=doc,
        tokens_raw=tokens_raw,
        tokens_compressed=tokens_compressed,
        compression_ratio=ratio,
        entities_merged=entities_merged,
        conflicts_detected=len(conflicts),
        warnings=warning_msgs,
        step_count=len(steps),
    )
