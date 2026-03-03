"""Generate .ctx.prov companion files from IR field-source mapping.

The .ctx.prov format maps each key-value line in a .ctx file back to
its source file:line, enabling full auditability of compressed output.

Format (per spec section 9):
    §PROVENANCE FOR:output.ctx
    ±ENTITY-CUSTOMER
    IDENTIFIER → customer.yaml#L5-L9
    MATCH-RULES → customer.yaml#L10-L18
"""

from __future__ import annotations

from ..model import CTXDocument, KeyValue, Provenance, Section
from .ir import IRCorpus, IREntity


def generate_provenance(
    corpus: IRCorpus,
    ctx_filename: str = "output.ctx",
) -> str:
    """Generate .ctx.prov companion text from the IR corpus.

    Maps every entity field back to its IRField.source location.
    Multi-source fields show all sources joined with ' + '.
    """
    lines: list[str] = []
    lines.append(f"§PROVENANCE FOR:{ctx_filename}")
    lines.append("")

    for entity in corpus.entities:
        lines.append(f"±ENTITY-{entity.name}")
        for field in entity.fields:
            if field.source:
                source_str = str(field.source)
                # Append additional sources if present
                if field.additional_sources:
                    extra = " + ".join(str(s) for s in field.additional_sources)
                    source_str = f"{source_str} + {extra}"
                lines.append(f"  {field.key} → {source_str}")
            else:
                lines.append(f"  {field.key} → (no source)")
        lines.append("")

    if corpus.standalone_rules:
        lines.append("±STANDALONE-RULES")
        for rule in corpus.standalone_rules:
            if rule.source:
                source_str = str(rule.source)
                if rule.additional_sources:
                    extra = " + ".join(str(s) for s in rule.additional_sources)
                    source_str = f"{source_str} + {extra}"
                lines.append(f"  {rule.key} → {source_str}")
            else:
                lines.append(f"  {rule.key} → (no source)")
        lines.append("")

    return "\n".join(lines)


def inject_inline_provenance(corpus: IRCorpus) -> None:
    """Modify field values in-place to append inline SRC: annotations.

    After calling this, each field's value will include a SRC: suffix
    that the compressor will emit directly.
    """
    for entity in corpus.entities:
        for field in entity.fields:
            if field.source and field.source.file:
                source_str = str(field.source)
                if field.additional_sources:
                    extra = " + ".join(str(s) for s in field.additional_sources)
                    source_str = f"{source_str} + {extra}"
                field.value = f"{field.value}  SRC:{source_str}"

    for rule in corpus.standalone_rules:
        if rule.source and rule.source.file:
            source_str = str(rule.source)
            if rule.additional_sources:
                extra = " + ".join(str(s) for s in rule.additional_sources)
                source_str = f"{source_str} + {extra}"
            rule.value = f"{rule.value}  SRC:{source_str}"
