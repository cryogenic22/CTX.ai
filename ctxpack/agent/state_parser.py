"""Parse agent step dicts into IR entities for compression.

Converts a list of step dicts (tool results, entity observations, decisions)
into an IRCorpus suitable for the existing packer pipeline.
"""

from __future__ import annotations

from typing import Any

from ..core.packer.ir import (
    Certainty,
    IRCorpus,
    IREntity,
    IRField,
    IRSource,
    IRWarning,
    Severity,
)


def parse_steps(
    steps: list[dict[str, Any]],
    *,
    domain: str = "agent-state",
) -> IRCorpus:
    """Convert a list of step dicts into an IRCorpus.

    Step formats supported:
    - {"entities": [{"name": "X", ...}]} → IREntity per item
    - {"tool": "name", "result": {...}} → synthetic entity from tool results
    - {"decision": "text"} → standalone rule
    - Fallback: STEP-{i} entity from full dict

    Later steps get slightly higher salience (recency boost).
    """
    corpus = IRCorpus(domain=domain)
    source_words = 0

    for i, step in enumerate(steps):
        source = IRSource(file=f"step-{i}", line_start=i)
        salience = 1.0 + i * 0.01

        if "entities" in step and isinstance(step["entities"], list):
            for ent_dict in step["entities"]:
                entity = _dict_to_entity(ent_dict, source=source, salience=salience)
                corpus.entities.append(entity)
                source_words += _count_dict_words(ent_dict)

        elif "tool" in step:
            entity = _tool_to_entity(step, index=i, source=source, salience=salience)
            corpus.entities.append(entity)
            source_words += _count_dict_words(step)

        elif "decision" in step:
            rule = IRField(
                key="DECISION",
                value=str(step["decision"]),
                raw_value=step["decision"],
                source=source,
                salience=salience,
            )
            corpus.standalone_rules.append(rule)
            source_words += len(str(step["decision"]).split())

        else:
            # Fallback: treat entire dict as an entity
            entity = _fallback_entity(step, index=i, source=source, salience=salience)
            corpus.entities.append(entity)
            source_words += _count_dict_words(step)

    corpus.source_token_count = source_words
    corpus.source_files = [f"step-{i}" for i in range(len(steps))]
    return corpus


def _dict_to_entity(
    d: dict[str, Any],
    *,
    source: IRSource,
    salience: float,
) -> IREntity:
    """Convert an entity dict to an IREntity."""
    name = str(d.get("name", "UNKNOWN")).upper().replace(" ", "-")
    entity = IREntity(
        name=name,
        sources=[source],
        salience=salience,
    )

    for key, value in d.items():
        if key == "name":
            continue
        field = _make_field(key, value, source=source, salience=salience)
        entity.fields.append(field)

    return entity


def _tool_to_entity(
    step: dict[str, Any],
    *,
    index: int,
    source: IRSource,
    salience: float,
) -> IREntity:
    """Convert a tool result step to a synthetic entity."""
    tool_name = str(step["tool"]).upper().replace(" ", "-").replace("_", "-")
    entity_name = f"TOOL-{tool_name}"

    entity = IREntity(
        name=entity_name,
        sources=[source],
        salience=salience,
    )

    result = step.get("result", {})
    if isinstance(result, dict):
        for key, value in result.items():
            field = _make_field(key, value, source=source, salience=salience)
            entity.fields.append(field)
    else:
        field = _make_field("RESULT", result, source=source, salience=salience)
        entity.fields.append(field)

    return entity


def _fallback_entity(
    step: dict[str, Any],
    *,
    index: int,
    source: IRSource,
    salience: float,
) -> IREntity:
    """Convert an arbitrary dict to a STEP-N entity."""
    entity = IREntity(
        name=f"STEP-{index}",
        sources=[source],
        salience=salience,
    )

    for key, value in step.items():
        field = _make_field(key, value, source=source, salience=salience)
        entity.fields.append(field)

    return entity


def _make_field(
    key: str,
    value: Any,
    *,
    source: IRSource,
    salience: float,
) -> IRField:
    """Create an IRField from a key/value pair."""
    key_upper = key.upper().replace(" ", "-").replace("_", "-")

    if isinstance(value, list):
        str_value = "+".join(str(v) for v in value)
    elif isinstance(value, dict):
        parts = [f"{k}:{v}" for k, v in value.items()]
        str_value = ",".join(parts)
    else:
        str_value = str(value)

    return IRField(
        key=key_upper,
        value=str_value,
        raw_value=value,
        source=source,
        salience=salience,
    )


def _count_dict_words(d: dict[str, Any]) -> int:
    """Approximate word count of a dict (for source token estimation)."""
    return len(str(d).split())
