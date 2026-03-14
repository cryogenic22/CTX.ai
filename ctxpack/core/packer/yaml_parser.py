"""Minimal YAML subset parser + entity extraction for domain knowledge.

Zero external dependencies — covers the YAML subset needed for entity-definition
files: key-value maps, block/flow sequences, nested structures, scalars, comments.
Unsupported features (anchors, tags, multi-line scalars) produce clear errors.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .ir import Certainty, IREntity, IRField, IRRelationship, IRSource, IRWarning, Severity

# ── YAML Subset Parser ──


class YAMLParseError(Exception):
    """Error during YAML subset parsing."""

    def __init__(self, message: str, line: int = 0, filename: str = ""):
        self.line = line
        self.filename = filename
        loc = f"{filename}:" if filename else ""
        if line:
            loc += f"line {line}: "
        super().__init__(f"{loc}{message}")


_UNSUPPORTED_RE = re.compile(r"^[^#]*[&*!](?=[A-Za-z])")
_ANCHOR_RE = re.compile(r"[&*]\w+")
_TAG_RE = re.compile(r"!!\w+|![^\s]+")
_MAPPING_RE = re.compile(r"^(\s*)([^#:]+?)\s*:\s*(.*?)\s*$")


def yaml_parse(text: str, *, filename: str = "") -> Any:
    """Parse a YAML subset string into Python objects.

    Supports: mappings, block sequences (``- item``), flow sequences
    (``[a, b]``), flow mappings (``{a: 1, b: 2}``), scalars, comments.

    Rejects: anchors (``&``/``*``), tags (``!``), multi-line scalars
    (``|``, ``>``).
    """
    parser = _YAMLParser(text, filename=filename)
    return parser.parse()


class _YAMLParser:
    def __init__(self, text: str, *, filename: str = ""):
        self._filename = filename
        self._lines: list[str] = text.split("\n")
        self._pos = 0

    def _error(self, msg: str) -> YAMLParseError:
        return YAMLParseError(msg, line=self._pos + 1, filename=self._filename)

    def parse(self) -> Any:
        self._skip_blanks_and_comments()
        if self._pos >= len(self._lines):
            return {}
        return self._parse_value(indent=-1)

    def _skip_blanks_and_comments(self) -> None:
        while self._pos < len(self._lines):
            stripped = self._lines[self._pos].strip()
            if stripped == "" or stripped.startswith("#"):
                self._pos += 1
            else:
                break

    def _current_indent(self) -> int:
        if self._pos >= len(self._lines):
            return -1
        line = self._lines[self._pos]
        return len(line) - len(line.lstrip())

    def _peek_stripped(self) -> str:
        if self._pos >= len(self._lines):
            return ""
        return self._lines[self._pos].strip()

    def _check_unsupported(self, line: str) -> None:
        stripped = line.strip()
        # Check for multi-line scalar indicators at end of key: value
        # Only reject if | or > appears as the sole value after a colon
        if re.match(r"^[^#:]+:\s*[|>]\s*$", stripped):
            raise self._error(
                f"Multi-line scalar indicators (| and >) are not supported"
            )
        if _TAG_RE.search(stripped):
            raise self._error(f"YAML tags are not supported")
        if _ANCHOR_RE.search(stripped):
            # Check it's not inside a quoted string
            clean = re.sub(r"['\"].*?['\"]", "", stripped)
            if _ANCHOR_RE.search(clean):
                raise self._error(f"YAML anchors/aliases are not supported")

    def _parse_value(self, indent: int) -> Any:
        self._skip_blanks_and_comments()
        if self._pos >= len(self._lines):
            return None

        stripped = self._peek_stripped()

        # Flow sequence or mapping on current line
        if stripped.startswith("["):
            return self._parse_flow_sequence(stripped)
        if stripped.startswith("{"):
            return self._parse_flow_mapping(stripped)

        # Block sequence
        if stripped.startswith("- ") or stripped == "-":
            return self._parse_block_sequence(indent)

        # Mapping
        if ":" in stripped and not stripped.startswith("#"):
            return self._parse_mapping(indent)

        # Bare scalar
        line = stripped
        self._pos += 1
        return self._parse_scalar(line)

    def _parse_mapping(self, parent_indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self._pos < len(self._lines):
            self._skip_blanks_and_comments()
            if self._pos >= len(self._lines):
                break
            ci = self._current_indent()
            if ci <= parent_indent and parent_indent >= 0:
                break

            line = self._lines[self._pos]
            stripped = line.strip()
            if stripped.startswith("#") or stripped == "":
                self._pos += 1
                continue
            if stripped.startswith("- "):
                break

            self._check_unsupported(line)

            m = _MAPPING_RE.match(line)
            if not m:
                break
            key_indent = len(m.group(1))
            if key_indent <= parent_indent and parent_indent >= 0:
                break

            key = m.group(2).strip()
            value_str = m.group(3)

            # Remove inline comment
            value_str = self._strip_inline_comment(value_str)

            self._pos += 1

            if value_str == "":
                # Value is on next lines (nested map, sequence, etc.)
                self._skip_blanks_and_comments()
                if self._pos < len(self._lines):
                    next_indent = self._current_indent()
                    if next_indent > key_indent:
                        result[key] = self._parse_value(key_indent)
                    else:
                        result[key] = None
                else:
                    result[key] = None
            elif value_str.startswith("["):
                result[key] = self._parse_flow_sequence(value_str)
            elif value_str.startswith("{"):
                result[key] = self._parse_flow_mapping(value_str)
            else:
                result[key] = self._parse_scalar(value_str)

        return result

    def _parse_block_sequence(self, parent_indent: int) -> list[Any]:
        result: list[Any] = []
        seq_indent: Optional[int] = None
        while self._pos < len(self._lines):
            self._skip_blanks_and_comments()
            if self._pos >= len(self._lines):
                break
            ci = self._current_indent()
            line = self._lines[self._pos]
            stripped = line.strip()

            if seq_indent is None:
                seq_indent = ci
            elif ci < seq_indent:
                break
            elif ci > seq_indent:
                break

            if not stripped.startswith("-"):
                break

            self._check_unsupported(line)

            # Remove leading "- "
            if stripped == "-":
                item_str = ""
            else:
                item_str = stripped[2:].strip()

            self._pos += 1

            if item_str == "":
                # Nested value on next lines
                self._skip_blanks_and_comments()
                if self._pos < len(self._lines):
                    next_indent = self._current_indent()
                    if next_indent > ci:
                        result.append(self._parse_value(ci))
                    else:
                        result.append(None)
                else:
                    result.append(None)
            elif item_str.startswith("{"):
                result.append(self._parse_flow_mapping(item_str))
            elif item_str.startswith("["):
                result.append(self._parse_flow_sequence(item_str))
            elif ":" in item_str and not item_str.startswith("#"):
                # Inline mapping within sequence item: "- key: value"
                # Check if there are more keys indented under this item
                k, v = item_str.split(":", 1)
                k = k.strip()
                v = self._strip_inline_comment(v.strip())
                inline_map: dict[str, Any] = {}
                if v.startswith("{"):
                    inline_map[k] = self._parse_flow_mapping(v)
                elif v.startswith("["):
                    inline_map[k] = self._parse_flow_sequence(v)
                elif v:
                    inline_map[k] = self._parse_scalar(v)
                else:
                    inline_map[k] = None
                # Check for continuation keys at deeper indent
                self._skip_blanks_and_comments()
                if self._pos < len(self._lines):
                    next_indent = self._current_indent()
                    if next_indent > ci:
                        more = self._parse_mapping(ci)
                        inline_map.update(more)
                result.append(inline_map)
            else:
                result.append(self._parse_scalar(item_str))

        return result

    def _parse_flow_sequence(self, text: str) -> list[Any]:
        text = text.strip()
        if not text.startswith("["):
            return []
        # Handle multi-line flow sequences
        content = text[1:]
        while "]" not in content:
            self._pos += 1 if self._pos < len(self._lines) else 0
            if self._pos >= len(self._lines):
                break
            content += " " + self._lines[self._pos].strip()

        if "]" in content:
            content = content[: content.rindex("]")]

        items: list[Any] = []
        for item in self._split_flow(content):
            item = item.strip()
            if item:
                if item.startswith("{"):
                    items.append(self._parse_flow_mapping(item))
                else:
                    items.append(self._parse_scalar(item))
        return items

    def _parse_flow_mapping(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if not text.startswith("{"):
            return {}
        content = text[1:]
        while "}" not in content:
            self._pos += 1 if self._pos < len(self._lines) else 0
            if self._pos >= len(self._lines):
                break
            content += " " + self._lines[self._pos].strip()

        if "}" in content:
            content = content[: content.rindex("}")]

        result: dict[str, Any] = {}
        for item in self._split_flow(content):
            item = item.strip()
            if ":" in item:
                k, v = item.split(":", 1)
                result[k.strip()] = self._parse_scalar(v.strip())
        return result

    def _split_flow(self, text: str) -> list[str]:
        """Split flow collection by commas, respecting nesting."""
        items: list[str] = []
        depth = 0
        start = 0
        for i, ch in enumerate(text):
            if ch in ("[", "{"):
                depth += 1
            elif ch in ("]", "}"):
                depth -= 1
            elif ch == "," and depth == 0:
                items.append(text[start:i])
                start = i + 1
        if start < len(text):
            items.append(text[start:])
        elif start == len(text) and start > 0:
            pass  # trailing comma, no empty append
        return items

    def _parse_scalar(self, text: str) -> Any:
        text = text.strip()
        text = self._strip_inline_comment(text)

        # Quoted strings
        if (text.startswith('"') and text.endswith('"')) or (
            text.startswith("'") and text.endswith("'")
        ):
            return text[1:-1]

        # Null
        if text.lower() in ("null", "~", ""):
            return None

        # Boolean
        if text.lower() in ("true", "yes", "on"):
            return True
        if text.lower() in ("false", "no", "off"):
            return False

        # Integer
        try:
            return int(text)
        except ValueError:
            pass

        # Float
        try:
            return float(text)
        except ValueError:
            pass

        return text

    def _strip_inline_comment(self, text: str) -> str:
        """Strip inline comments (`` # ...``) while respecting quotes."""
        in_quote = None
        for i, ch in enumerate(text):
            if ch in ('"', "'") and in_quote is None:
                in_quote = ch
            elif ch == in_quote:
                in_quote = None
            elif ch == "#" and in_quote is None and i > 0 and text[i - 1] == " ":
                return text[: i - 1].rstrip()
        return text


# ── Entity Extraction ──


def extract_entities_from_yaml(
    data: dict[str, Any],
    *,
    filename: str = "",
) -> tuple[list[IREntity], list[IRField], list[IRWarning]]:
    """Extract IREntities and standalone rules from parsed YAML data.

    Returns (entities, standalone_rules, warnings).
    """
    entities: list[IREntity] = []
    standalone_rules: list[IRField] = []
    warnings: list[IRWarning] = []

    source = IRSource(file=filename)

    # Check if this is a single-entity file (has 'entity' key at top level)
    if "entity" in data:
        entity = _extract_single_entity(data, source)
        entities.append(entity)
        return entities, standalone_rules, warnings

    # Check if this is a rules file (has 'rules' key at top level)
    if "rules" in data:
        rules_data = data["rules"]
        if isinstance(rules_data, list):
            for item in rules_data:
                if isinstance(item, dict):
                    for k, v in item.items():
                        standalone_rules.append(
                            IRField(
                                key=_hyphenate(k).upper(),
                                value=_compress_value(v),
                                raw_value=v,
                                source=source,
                            )
                        )
        elif isinstance(rules_data, dict):
            for k, v in rules_data.items():
                standalone_rules.append(
                    IRField(
                        key=_hyphenate(k).upper(),
                        value=_compress_value(v),
                        raw_value=v,
                        source=source,
                    )
                )
        return entities, standalone_rules, warnings

    # Check for multiple entities (each top-level key is an entity)
    # Heuristic: if top-level values are dicts with entity-like fields
    for k, v in data.items():
        if isinstance(v, dict) and _looks_like_entity(v):
            entity = _extract_single_entity(
                {"entity": k, **v}, source
            )
            entities.append(entity)
        else:
            # Standalone config/rule
            standalone_rules.append(
                IRField(
                    key=_hyphenate(k).upper(),
                    value=_compress_value(v),
                    raw_value=v,
                    source=source,
                )
            )

    return entities, standalone_rules, warnings


def _looks_like_entity(data: dict) -> bool:
    """Heuristic: does this dict look like an entity definition?"""
    entity_keys = {
        "identifier", "golden_source", "match_rules", "pii",
        "pii_classification", "retention", "fields", "attributes",
        "status", "relationships", "constraints",
        "id", "uuid", "has_many", "has_one", "references",
        "depends_on", "primary_key",
    }
    return bool(set(data.keys()) & entity_keys)


def _extract_single_entity(data: dict[str, Any], source: IRSource) -> IREntity:
    """Extract one IREntity from a YAML dict with an ``entity`` key."""
    name = _canonicalize_name(str(data.get("entity", "UNKNOWN")))
    aliases: list[str] = []
    fields: list[IRField] = []
    relationships: list[IRRelationship] = []
    annotations: dict[str, str] = {}

    description = str(data.get("description", ""))

    _RELATIONSHIP_KEYS = {"belongs_to", "belongs-to", "has_many", "has-many",
                          "has_one", "has-one", "references", "refs",
                          "depends_on", "depends-on"}

    for key, val in data.items():
        if key == "entity":
            continue
        if key == "aliases":
            if isinstance(val, list):
                aliases = [str(a) for a in val]
            continue
        if key == "description":
            annotations["description"] = description
            continue

        comp_key, comp_val, certainty = _compress_entity_field(key, val, description=description)
        fields.append(
            IRField(
                key=comp_key,
                value=comp_val,
                raw_value=val,
                source=source,
                certainty=certainty,
            )
        )

        # Build IRRelationship for relationship keys
        norm_key = key.lower().replace("-", "_")
        if norm_key in {k.replace("-", "_") for k in _RELATIONSHIP_KEYS}:
            rels = _build_relationships(name, norm_key, val, source)
            relationships.extend(rels)

    return IREntity(
        name=name,
        aliases=aliases,
        fields=fields,
        relationships=relationships,
        annotations=annotations,
        sources=[source],
    )


def _build_relationships(
    entity_name: str, norm_key: str, val: Any, source: IRSource
) -> list[IRRelationship]:
    """Build IRRelationship objects from a relationship field value."""
    _REL_TYPE_MAP = {
        "belongs_to": "belongs-to",
        "has_many": "has-many",
        "has_one": "has-one",
        "references": "references",
        "refs": "references",
        "depends_on": "depends-on",
    }
    _CARDINALITY_MAP = {
        "belongs_to": "1:1",
        "has_many": "1:N",
        "has_one": "1:1",
        "references": "1:1",
        "refs": "1:1",
        "depends_on": "1:1",
    }
    rel_type = _REL_TYPE_MAP.get(norm_key, "references")
    default_card = _CARDINALITY_MAP.get(norm_key, "1:1")

    results: list[IRRelationship] = []

    if isinstance(val, dict):
        target = _canonicalize_name(str(val.get("entity", "")))
        if target:
            results.append(IRRelationship(
                source_entity=entity_name,
                target_entity=target,
                rel_type=rel_type,
                via_field=str(val.get("field", val.get("via", ""))),
                cardinality=str(val.get("cardinality", default_card)),
                cascade=str(val.get("cascade", "")),
                required=bool(val.get("required", val.get("mandatory", False))),
                source=source,
            ))
    elif isinstance(val, list):
        for item in val:
            if isinstance(item, dict):
                target = _canonicalize_name(str(item.get("entity", "")))
                if target:
                    results.append(IRRelationship(
                        source_entity=entity_name,
                        target_entity=target,
                        rel_type=rel_type,
                        via_field=str(item.get("field", item.get("via", ""))),
                        cardinality=str(item.get("cardinality", default_card)),
                        cascade=str(item.get("cascade", "")),
                        required=bool(item.get("required", item.get("mandatory", False))),
                        source=source,
                    ))
            elif isinstance(item, str):
                results.append(IRRelationship(
                    source_entity=entity_name,
                    target_entity=_canonicalize_name(item),
                    rel_type=rel_type,
                    cardinality=default_card,
                    source=source,
                ))
    elif isinstance(val, str):
        results.append(IRRelationship(
            source_entity=entity_name,
            target_entity=_canonicalize_name(val),
            rel_type=rel_type,
            cardinality=default_card,
            source=source,
        ))

    return results


# ── Field Compression Rules ──


def _compress_entity_field(key: str, val: Any, *, description: str = "") -> tuple[str, str, Certainty]:
    """Compress a YAML entity field to L2 key:value notation.

    Returns (compressed_key, compressed_value, certainty).
    """
    norm_key = key.lower().replace("-", "_")

    # golden_source → ★GOLDEN-SOURCE:value
    if norm_key == "golden_source":
        return "★GOLDEN-SOURCE", _compress_scalar(val), Certainty.EXPLICIT

    # identifier → IDENTIFIER:name(type,flags)
    if norm_key == "identifier":
        value, certainty = _compress_identifier(val, description=description)
        return "IDENTIFIER", value, certainty

    # match_rules → MATCH-RULES:[field:method(options),...]
    if norm_key == "match_rules":
        return "MATCH-RULES", _compress_match_rules(val), Certainty.EXPLICIT

    # pii + pii_classification → PII-CLASSIFICATION:fields→LEVEL
    if norm_key == "pii_classification":
        return "PII-CLASSIFICATION", _compress_scalar(val), Certainty.EXPLICIT
    if norm_key == "pii":
        if isinstance(val, list):
            return "PII", "+".join(str(v) for v in val), Certainty.EXPLICIT
        return "PII", _compress_scalar(val), Certainty.EXPLICIT

    # retention → RETENTION:active→X|churned→N-months→action
    if norm_key == "retention":
        return "RETENTION", _compress_retention(val), Certainty.EXPLICIT

    # status / status_machine → STATUS-MACHINE:state→state→...|...
    if norm_key in ("status", "status_machine", "status_flow"):
        return "STATUS-MACHINE", _compress_status(val), Certainty.EXPLICIT

    # relationships (belongs_to, has_many, has_one, references, depends_on)
    if norm_key in ("belongs_to", "belongs-to"):
        return "BELONGS-TO", _compress_relationship(val), Certainty.EXPLICIT
    if norm_key in ("has_many", "has-many"):
        return "HAS-MANY", _compress_relationship_extended(val, "1:N"), Certainty.EXPLICIT
    if norm_key in ("has_one", "has-one"):
        return "HAS-ONE", _compress_relationship_extended(val, "1:1"), Certainty.EXPLICIT
    if norm_key in ("references", "refs"):
        return "REFERENCES", _compress_relationship_extended(val, "1:1"), Certainty.EXPLICIT
    if norm_key in ("depends_on", "depends-on"):
        return "DEPENDS-ON", _compress_relationship_extended(val, "1:1"), Certainty.EXPLICIT

    # immutable_after → IMMUTABLE-AFTER:state(details)
    if norm_key in ("immutable_after", "immutable-after"):
        return "IMMUTABLE-AFTER", _compress_scalar(val), Certainty.EXPLICIT

    # financial_fields → FINANCIAL-FIELDS:[f1,f2]→TYPE
    if norm_key in ("financial_fields", "financial-fields"):
        return "FINANCIAL-FIELDS", _compress_typed_list(val), Certainty.EXPLICIT

    # Generic compression
    compressed_key = _hyphenate(key).upper()
    compressed_val = _compress_value(val)
    return compressed_key, compressed_val, Certainty.EXPLICIT


def _compress_identifier(val: Any, *, description: str = "") -> tuple[str, Certainty]:
    """Returns (compressed_value, certainty)."""
    certainty = Certainty.EXPLICIT
    if isinstance(val, dict):
        name = val.get("name", val.get("field", ""))
        typ = val.get("type", "")
        flags = []
        for flag_key in ("immutable", "unique", "required"):
            if val.get(flag_key):
                # Enrich "unique" with scope from description if available
                if flag_key == "unique" and description:
                    scope = _extract_scope(description, flag_key)
                    if scope:
                        flags.append(scope)
                        certainty = Certainty.INFERRED
                    else:
                        flags.append(flag_key)
                else:
                    flags.append(flag_key)
        # Also include explicit scope/unique_per fields
        scope_val = val.get("scope", val.get("unique_per", ""))
        if scope_val and "unique" not in str(flags):
            flags.append(f"unique-per-{_hyphenate(str(scope_val))}")
        parts = [str(typ)] + flags if typ else flags
        if parts:
            return f"{name}({','.join(parts)})", certainty
        return str(name), certainty
    if isinstance(val, str):
        return val, certainty
    return str(val), certainty


def _extract_scope(description: str, flag: str) -> str:
    """Try to extract a scope qualifier for a flag from entity description.

    E.g. "Product catalog entity" + "unique" → "unique-per-merchant"
    if description mentions merchant/tenant/org scope.
    """
    desc_lower = description.lower()
    scope_markers = {
        "per merchant": "unique-per-merchant",
        "per-merchant": "unique-per-merchant",
        "per tenant": "unique-per-tenant",
        "per-tenant": "unique-per-tenant",
        "per organization": "unique-per-org",
        "per org": "unique-per-org",
        "per store": "unique-per-store",
        "per region": "unique-per-region",
        "per account": "unique-per-account",
    }
    for marker, result in scope_markers.items():
        if marker in desc_lower:
            return result
    return ""


def _compress_match_rules(val: Any) -> str:
    if not isinstance(val, list):
        return _compress_value(val)
    parts: list[str] = []
    for rule in val:
        if isinstance(rule, dict):
            field = rule.get("field", "")
            method = rule.get("method", "")
            options = rule.get("options", "")
            if options:
                if isinstance(options, dict):
                    opt_str = ",".join(
                        f"{k}" if v is True else f"{k}"
                        for k, v in options.items()
                    )
                elif isinstance(options, list):
                    opt_str = ",".join(str(o) for o in options)
                else:
                    opt_str = str(options)
                parts.append(f"{field}:{_hyphenate(method)}({opt_str})")
            else:
                parts.append(f"{field}:{_hyphenate(method)}")
        else:
            parts.append(str(rule))
    return "[" + ",\n  ".join(parts) + "]"


def _compress_retention(val: Any) -> str:
    if isinstance(val, dict):
        parts: list[str] = []
        for k, v in val.items():
            if isinstance(v, dict):
                sub_parts = []
                for sk, sv in v.items():
                    sub_parts.append(str(sv))
                parts.append(f"{_hyphenate(k)}→{'→'.join(sub_parts)}")
            else:
                parts.append(f"{_hyphenate(k)}→{v}")
        return "|".join(parts)
    return _compress_scalar(val)


def _compress_status(val: Any) -> str:
    if isinstance(val, list):
        return "→".join(str(s) for s in val)
    if isinstance(val, dict):
        # flow: [states], terminal: [states]
        flow = val.get("flow", val.get("states", []))
        terminal = val.get("terminal", [])
        result = "→".join(str(s) for s in flow) if isinstance(flow, list) else str(flow)
        if terminal and isinstance(terminal, list):
            result += "|" + "|".join(str(t) for t in terminal)
        return result
    return str(val)


def _compress_relationship(val: Any) -> str:
    if isinstance(val, dict):
        entity = val.get("entity", "")
        field = val.get("field", val.get("via", ""))
        required = val.get("required", val.get("mandatory", False))
        req_str = ",mandatory" if required else ""
        return f"@ENTITY-{_canonicalize_name(entity)}({field}{req_str})"
    return str(val)


def _compress_relationship_extended(val: Any, default_cardinality: str = "1:1") -> str:
    """Compress an extended relationship (has_many, has_one, references, depends_on).

    Supports dict input with: entity, field/via, cardinality, cascade, required.
    Uses spec operators: → (standard), ~> (weak), >> (cascade).
    """
    if isinstance(val, dict):
        entity = val.get("entity", "")
        field = val.get("field", val.get("via", ""))
        cardinality = val.get("cardinality", default_cardinality)
        cascade = val.get("cascade", "")
        required = val.get("required", val.get("mandatory", False))

        parts = []
        if field:
            parts.append(field)
        parts.append(cardinality)
        if required:
            parts.append("mandatory")

        ref = f"@ENTITY-{_canonicalize_name(entity)}({','.join(parts)})"
        if cascade:
            ref += f">>cascade-{_hyphenate(str(cascade))}"
        return ref
    if isinstance(val, list):
        # List of relationships
        items = []
        for item in val:
            items.append(_compress_relationship_extended(item, default_cardinality))
        return "+".join(items)
    if isinstance(val, str):
        # Simple entity name reference
        return f"@ENTITY-{_canonicalize_name(val)}"
    return str(val)


def _compress_typed_list(val: Any) -> str:
    if isinstance(val, dict):
        fields = val.get("fields", [])
        typ = val.get("type", "")
        if isinstance(fields, list):
            field_str = "[" + ",".join(str(f) for f in fields) + "]"
            if typ:
                return f"{field_str}→{typ}"
            return field_str
    if isinstance(val, list):
        return "[" + ",".join(str(v) for v in val) + "]"
    return _compress_value(val)


# ── Generic Compression Helpers ──


def _compress_value(val: Any) -> str:
    """Compress any Python value to L2 notation."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return _compress_scalar(val)
    if isinstance(val, list):
        items = [_compress_value(v) for v in val]
        return "+".join(items)
    if isinstance(val, dict):
        parts = []
        for k, v in val.items():
            cv = _compress_value(v)
            parts.append(f"{_hyphenate(k)}({cv})")
        return "+".join(parts)
    return str(val)


def _compress_scalar(val: Any) -> str:
    """Compress a scalar value, preserving spaces for BPE efficiency.

    Spaces in prose values are kept as-is. Only structural identifiers
    (keys, entity names) are hyphenated. This avoids the BPE inflation
    problem where hyphenated words tokenize ~40% worse than spaced words.
    """
    s = str(val)
    # Commas followed by space → comma-space (preserve for readability)
    # Underscores → hyphens (structural convention)
    return s.replace("_", "-")


def _hyphenate(text: str) -> str:
    """Convert spaces and underscores to hyphens for L2 notation."""
    return text.replace(" ", "-").replace("_", "-")


def _canonicalize_name(name: str) -> str:
    """Canonicalize an entity name: uppercase, _ → -, strip prefix."""
    name = name.upper().replace("_", "-").replace(" ", "-")
    # Strip common prefixes
    for prefix in ("ENTITY-", "ENTITY_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name
