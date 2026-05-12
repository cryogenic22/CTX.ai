"""Top-level symbol extraction (CP-003).

One pass over a parsed module to find top-level functions and classes.
Methods, decorators, and FastAPI/Pydantic metadata land in later
tasks (CP-004 through CP-008). This module is intentionally narrow.

Naming at CP-003 is bare identifier (``read_user``, ``User``). CP-009
adds the ``<file>::<dotted.path>`` disambiguation scheme that handles
overloads and conditional definitions. Until then, callers should
treat ``Symbol.name`` as the local name only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import tree_sitter

from ctxpack.core.code.parser import ParseResult


# ── Kind ────────────────────────────────────────────────────────────────


class Kind(str, Enum):
    """Symbol categories. ``str, Enum`` keeps values JSON-serialisable
    and orderable, matching ``ctxpack.core.layers.ContextLayer``.

    Additive: CP-004 adds METHOD, CLASS_ATTRIBUTE; CP-008 may add
    PYDANTIC_MODEL; CP-012 adds COMPONENT, HOOK, etc.
    """

    FUNCTION = "function"
    CLASS = "class"


# ── Symbol ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Symbol:
    """One top-level symbol.

    Line numbers are 1-indexed (human convention). Byte offsets index
    into ``ParseResult.source`` so callers recover the source text
    via ``source[byte_start:byte_end]``.

    For decorated definitions, the line/byte range covers the
    underlying ``function_definition`` / ``class_definition``, NOT the
    decorator(s). Decorator capture lives in CP-005 as separate
    metadata fields on the (eventual) IREntity.
    """

    name: str
    kind: Kind
    line_start: int
    line_end: int
    byte_start: int
    byte_end: int


# ── Extraction ──────────────────────────────────────────────────────────


_FUNCTION_NODE_TYPE = "function_definition"
_CLASS_NODE_TYPE = "class_definition"
_DECORATED_NODE_TYPE = "decorated_definition"


def extract_symbols(result: ParseResult) -> list[Symbol]:
    """Return top-level functions and classes from ``result``.

    Order: file order (ascending ``byte_start``). The walker iterates
    immediate children of the module node. ``decorated_definition``
    nodes are unwrapped to their underlying function/class; decorated
    inner functions are exposed under the function/class name, not the
    decorator name.

    Nested defs (functions inside functions, methods inside classes,
    classes inside conditional branches) are NOT extracted at CP-003.
    CP-004 covers methods; later tasks may surface nested defs if a
    real need emerges.
    """
    out: list[Symbol] = []
    for child in result.root.children:
        target = _unwrap(child)
        if target is None:
            continue
        sym = _make_symbol(target)
        if sym is not None:
            out.append(sym)
    return out


def _unwrap(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the underlying function or class node if ``node`` is one
    (directly or wrapped in ``decorated_definition``). Otherwise None.
    """
    if node.type in (_FUNCTION_NODE_TYPE, _CLASS_NODE_TYPE):
        return node
    if node.type == _DECORATED_NODE_TYPE:
        # decorated_definition: one or more `decorator` children, then
        # the definition. Find the definition.
        for child in node.children:
            if child.type in (_FUNCTION_NODE_TYPE, _CLASS_NODE_TYPE):
                return child
        return None
    return None


def _make_symbol(node: tree_sitter.Node) -> Symbol | None:
    """Build a Symbol from a function_definition or class_definition node.

    Returns None if the node has no name (rare — parse-recovered
    fragments around syntax errors can occasionally lack the name
    field).
    """
    name_node = node.child_by_field_name("name")
    if name_node is None or name_node.text is None:
        return None
    kind = Kind.FUNCTION if node.type == _FUNCTION_NODE_TYPE else Kind.CLASS
    return Symbol(
        name=name_node.text.decode("utf-8"),
        kind=kind,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
    )
