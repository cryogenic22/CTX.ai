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
class Decorator:
    """A captured ``@decorator`` annotation.

    Source-text-preserving capture: ``args`` and ``kwargs`` values
    are the literal source substrings (including quotes for strings,
    list brackets for lists, etc.). Downstream consumers (CP-006
    route detection, CP-007 Depends, CP-008 Pydantic base-class
    detection) decide whether to evaluate them.

    Name is the dotted form a Python parser would resolve (``app.get``,
    ``staticmethod``, ``validators.email``) — call vs. bare-reference
    is collapsed; both produce the same ``name``.
    """

    name: str
    args: tuple[str, ...] = ()
    kwargs: tuple[tuple[str, str], ...] = ()
    line: int = 0  # 1-indexed line of the @ symbol


@dataclass(frozen=True)
class Symbol:
    """One top-level symbol.

    Line numbers are 1-indexed (human convention). Byte offsets index
    into ``ParseResult.source`` so callers recover the source text
    via ``source[byte_start:byte_end]``.

    For decorated definitions, the line/byte range covers the
    underlying ``function_definition`` / ``class_definition``, NOT the
    decorator(s). Decorators themselves live on ``decorators`` as a
    tuple of :class:`Decorator` records.
    """

    name: str
    kind: Kind
    line_start: int
    line_end: int
    byte_start: int
    byte_end: int
    decorators: tuple[Decorator, ...] = ()


# ── Extraction ──────────────────────────────────────────────────────────


_FUNCTION_NODE_TYPE = "function_definition"
_CLASS_NODE_TYPE = "class_definition"
_DECORATED_NODE_TYPE = "decorated_definition"
_DECORATOR_NODE_TYPE = "decorator"
_EXPRESSION_STMT_TYPE = "expression_statement"
_ASSIGNMENT_TYPE = "assignment"
_IDENTIFIER_TYPE = "identifier"
_ATTRIBUTE_TYPE = "attribute"
_CALL_TYPE = "call"
_KEYWORD_ARGUMENT_TYPE = "keyword_argument"
_ARGUMENT_LIST_TYPE = "argument_list"


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
        decorators = _decorators_for(child, source=result.source)
        sym = _make_symbol(target, decorators=decorators)
        if sym is None:
            continue
        out.append(sym)
        if target.type == _CLASS_NODE_TYPE:
            out.extend(
                _class_body_symbols(target, class_name=sym.name, source=result.source)
            )
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


def _make_symbol(
    node: tree_sitter.Node,
    *,
    decorators: tuple[Decorator, ...] = (),
) -> Symbol | None:
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
        decorators=decorators,
    )


def _class_body_symbols(
    class_node: tree_sitter.Node,
    *,
    class_name: str,
    source: bytes,
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
            decorators = _decorators_for(member, source=source)
            method = _make_method_symbol(
                target, class_name=class_name, decorators=decorators
            )
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
    decorators: tuple[Decorator, ...] = (),
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
        decorators=decorators,
    )


# ── Decorator extraction (CP-005) ──────────────────────────────────────


def _decorators_for(
    node: tree_sitter.Node, *, source: bytes
) -> tuple[Decorator, ...]:
    """Extract the decorator list from a node.

    If ``node`` is a ``decorated_definition``, returns its decorators
    in source order. Otherwise returns ``()``.
    """
    if node.type != _DECORATED_NODE_TYPE:
        return ()
    out: list[Decorator] = []
    for child in node.children:
        if child.type == _DECORATOR_NODE_TYPE:
            d = _parse_decorator(child, source=source)
            if d is not None:
                out.append(d)
    return tuple(out)


def _parse_decorator(
    decorator_node: tree_sitter.Node, *, source: bytes
) -> Decorator | None:
    """Convert a tree-sitter `decorator` node to a :class:`Decorator`.

    The decorator child after the ``@`` is one of:
    - ``identifier`` (``@cache``)
    - ``attribute`` (``@app.get`` without call)
    - ``call`` (``@app.get("/foo")``)
    """
    inner = _decorator_inner(decorator_node)
    if inner is None:
        return None
    line = decorator_node.start_point[0] + 1

    if inner.type == _IDENTIFIER_TYPE or inner.type == _ATTRIBUTE_TYPE:
        name = _dotted_name(inner, source=source)
        if name is None:
            return None
        return Decorator(name=name, args=(), kwargs=(), line=line)

    if inner.type == _CALL_TYPE:
        fn = inner.child_by_field_name("function")
        if fn is None:
            return None
        name = _dotted_name(fn, source=source)
        if name is None:
            return None
        args, kwargs = _parse_call_arguments(inner, source=source)
        return Decorator(name=name, args=args, kwargs=kwargs, line=line)

    return None


def _decorator_inner(decorator_node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the first non-``@`` child of a decorator node."""
    for child in decorator_node.children:
        if child.type == "@":
            continue
        return child
    return None


def _dotted_name(node: tree_sitter.Node, *, source: bytes) -> str | None:
    """Render `identifier` or `attribute` chains as a dotted string."""
    if node.text is None:
        return None
    # Both identifier ("cache") and attribute ("app.get",
    # "validators.email") render correctly when read straight from
    # source. Strip any whitespace defensively.
    return source[node.start_byte:node.end_byte].decode("utf-8").strip()


def _parse_call_arguments(
    call_node: tree_sitter.Node, *, source: bytes
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Extract positional + keyword args from a `call` node.

    Returns ``(args, kwargs)`` where each entry is the literal source
    text of the corresponding value (with surrounding quotes/brackets
    preserved for strings/lists/dicts).
    """
    arg_list = call_node.child_by_field_name("arguments")
    if arg_list is None:
        # Fall back to scanning children for argument_list.
        for c in call_node.children:
            if c.type == _ARGUMENT_LIST_TYPE:
                arg_list = c
                break
    if arg_list is None:
        return ((), ())

    args: list[str] = []
    kwargs: list[tuple[str, str]] = []
    for child in arg_list.children:
        if child.type in ("(", ")", ","):
            continue
        if child.type == _KEYWORD_ARGUMENT_TYPE:
            kw = _parse_keyword_argument(child, source=source)
            if kw is not None:
                kwargs.append(kw)
            continue
        # Positional argument: capture source text.
        text = source[child.start_byte:child.end_byte].decode("utf-8")
        args.append(text)
    return tuple(args), tuple(kwargs)


def _parse_keyword_argument(
    node: tree_sitter.Node, *, source: bytes
) -> tuple[str, str] | None:
    """Convert `keyword_argument` to ``(name, value_source)``."""
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if name_node is None or value_node is None or name_node.text is None:
        return None
    return (
        name_node.text.decode("utf-8"),
        source[value_node.start_byte:value_node.end_byte].decode("utf-8"),
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
