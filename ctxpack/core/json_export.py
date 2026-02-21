"""Export CTXDocument AST to JSON-serializable dict."""

from __future__ import annotations

import json
from typing import Any, Union

from .model import (
    BodyElement,
    CTXDocument,
    Header,
    KeyValue,
    NumberedItem,
    PlainLine,
    Provenance,
    QuotedBlock,
    Section,
)


def to_dict(doc: CTXDocument) -> dict[str, Any]:
    """Convert a CTXDocument to a JSON-serializable dict."""
    return {
        "header": _header_dict(doc.header),
        "body": [_element_dict(e) for e in doc.body],
    }


def to_json(doc: CTXDocument, *, indent: int = 2) -> str:
    """Convert a CTXDocument to a JSON string."""
    return json.dumps(to_dict(doc), indent=indent, ensure_ascii=False)


def _header_dict(h: Header) -> dict[str, Any]:
    return {
        "magic": h.magic,
        "version": h.version,
        "layer": h.layer.value,
        "fields": {kv.key: kv.value for kv in h.all_fields},
    }


def _element_dict(elem: Union[Section, BodyElement]) -> dict[str, Any]:
    if isinstance(elem, Section):
        return {
            "type": "section",
            "name": elem.name,
            "subtitles": list(elem.subtitles),
            "indent": elem.indent,
            "depth": elem.depth,
            "children": [_element_dict(c) for c in elem.children],
        }
    if isinstance(elem, KeyValue):
        return {
            "type": "kv",
            "key": elem.key,
            "value": elem.value,
        }
    if isinstance(elem, NumberedItem):
        return {
            "type": "numbered",
            "number": elem.number,
            "text": elem.text,
        }
    if isinstance(elem, QuotedBlock):
        return {
            "type": "quoted",
            "lang": elem.lang,
            "content": elem.content,
        }
    if isinstance(elem, Provenance):
        return {
            "type": "provenance",
            "source": elem.source,
            "path": elem.path,
            "line_range": elem.line_range,
        }
    if isinstance(elem, PlainLine):
        return {
            "type": "plain",
            "text": elem.text,
        }
    return {"type": "unknown", "repr": repr(elem)}
