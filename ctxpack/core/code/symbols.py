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

    Additive: CP-008 may add PYDANTIC_MODEL; CP-012 adds COMPONENT,
    HOOK, etc.
    """

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    CLASS_ATTRIBUTE = "class_attribute"


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
_EXPRESSION_STMT_TYPE = "expression_statement"
_ASSIGNMENT_TYPE = "assignment"
_IDENTIFIER_TYPE = "identifier"


def extract_symbols(result: ParseResult) -> list[Symbol]:
    """Return top-level functions/classes plus class methods and
    class attributes from ``result``.

    Order: file order (ascending ``byte_start``). The walker iterates
    immediate children of the module node. ``decorated_definition``
    nodes are unwrapped to their underlying function/class. For each
    class found, we descend into its body and emit METHOD entries for
    inner functions (dotted as ``Class.method``) and CLASS_ATTRIBUTE
    entries for annotated/plain assignments (``Class.attr``).

    Not in scope for CP-004:
    - Inner functions inside methods.
    - Inner classes inside classes.
    - Decorator-based subclassing of method kind (property vs
      staticmethod vs classmethod) — all become METHOD; CP-005
      carries the decorator metadata separately.
    """
    out: list[Symbol] = []
    for child in result.root.children:
        target = _unwrap(child)
        if target is None:
            continue
        sym = _make_symbol(target)
        if sym is None:
            continue
        out.append(sym)
        if target.type == _CLASS_NODE_TYPE:
            out.extend(_class_body_symbols(target, class_name=sym.name))
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


def _class_body_symbols(
    class_node: tree_sitter.Node,
    *,
    class_name: str,
) -> list[Symbol]:
    """Walk a class body, emitting METHOD and CLASS_ATTRIBUTE entries.

    `class_node` is a `class_definition`. We access its `body` field
    (a `block`) and iterate its immediate children. We do NOT recurse
    into method bodies or nested classes — that's deliberate for v0.
    """
    body = class_node.child_by_field_name("body")
    if body is None:
        return []
    out: list[Symbol] = []
    for member in body.children:
        target = _unwrap(member)
        if target is not None and target.type == _FUNCTION_NODE_TYPE:
            method = _make_method_symbol(target, class_name=class_name)
            if method is not None:
                out.append(method)
            continue
        if member.type == _EXPRESSION_STMT_TYPE:
            attr = _make_class_attribute(member, class_name=class_name)
            if attr is not None:
                out.append(attr)
    return out


def _make_method_symbol(
    fn_node: tree_sitter.Node,
    *,
    class_name: str,
) -> Symbol | None:
    """Emit a METHOD with `<ClassName>.<method_name>` naming.

    Range is the function body extent (decorator-excluded, matching
    CP-003 convention for top-level decorated definitions).
    """
    name_node = fn_node.child_by_field_name("name")
    if name_node is None or name_node.text is None:
        return None
    return Symbol(
        name=f"{class_name}.{name_node.text.decode('utf-8')}",
        kind=Kind.METHOD,
        line_start=fn_node.start_point[0] + 1,
        line_end=fn_node.end_point[0] + 1,
        byte_start=fn_node.start_byte,
        byte_end=fn_node.end_byte,
    )


def _make_class_attribute(
    expr_node: tree_sitter.Node,
    *,
    class_name: str,
) -> Symbol | None:
    """Emit CLASS_ATTRIBUTE if expr_node wraps a single-target
    `identifier = ...` (typed or untyped) or `identifier: type`.

    Skips tuple unpacking (``a, b = 1, 2``), attribute writes
    (``self.x = ...`` — wouldn't be at class body level anyway), and
    docstrings (which are `string` nodes, not `assignment`).
    """
    # expression_statement should have one child: the assignment.
    if not expr_node.children:
        return None
    assignment = expr_node.children[0]
    if assignment.type != _ASSIGNMENT_TYPE:
        return None
    left = assignment.child_by_field_name("left")
    if left is None or left.type != _IDENTIFIER_TYPE or left.text is None:
        return None
    return Symbol(
        name=f"{class_name}.{left.text.decode('utf-8')}",
        kind=Kind.CLASS_ATTRIBUTE,
        line_start=expr_node.start_point[0] + 1,
        line_end=expr_node.end_point[0] + 1,
        byte_start=expr_node.start_byte,
        byte_end=expr_node.end_byte,
    )
