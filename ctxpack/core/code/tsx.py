"""CP-012/013/015 — TSX symbol extractor, hooks, call graph.

Mirrors the Python pipeline (``symbols.py`` + ``callgraph.py``) but
tailored for React TSX:

- Component detection: function/const with JSX in body OR
  ``forwardRef``/``memo`` wrapping.
- Hook detection: function name starts with ``use`` followed by an
  uppercase letter (or is ``use``), and is callable.
- Hook usage: walk a component's body, capture identifier names of
  call expressions that match the hook predicate.
- Call graph: JSX element-usage edges (``<Card .../>`` produces an
  edge from the enclosing component to ``Card``).

Same ``Symbol``/``CallEdge`` dataclasses as Python so downstream code
(emitter, pack, ranker) is language-agnostic.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

import tree_sitter

from ctxpack.core.code.callgraph import CallEdge
from ctxpack.core.code.naming import qualified_names_for_module
from ctxpack.core.code.parser import ParseResult
from ctxpack.core.code.symbols import Kind, Symbol


# ── Predicates ──────────────────────────────────────────────────────────


_HOOK_NAME = re.compile(r"^use([A-Z]|$)")
_KNOWN_HOOKS = frozenset({
    "useState", "useEffect", "useMemo", "useCallback", "useRef",
    "useContext", "useReducer", "useLayoutEffect", "useImperativeHandle",
    "useDebugValue", "useId", "useTransition", "useDeferredValue",
    "useSyncExternalStore", "useInsertionEffect",
})


def _is_hook_name(name: str) -> bool:
    return bool(_HOOK_NAME.match(name))


def _is_pascal_case(name: str) -> bool:
    return bool(name) and name[0].isupper()


# ── Symbol extraction ──────────────────────────────────────────────────


def extract_symbols_tsx(result: ParseResult) -> list[Symbol]:
    """Top-level TSX/TS symbols.

    Walks ``program`` children, unwraps ``export_statement``, and
    emits one Symbol per function declaration, lexical declaration
    (const), type alias, or interface.
    """
    out: list[Symbol] = []
    for child in result.root.children:
        exported = False
        target = child
        if child.type == "export_statement":
            exported = True
            target = _export_inner(child) or child
        sym = _symbol_from_decl(target, result.source, exported=exported)
        if sym is not None:
            out.append(sym)
    return out


def _export_inner(node: tree_sitter.Node) -> Optional[tree_sitter.Node]:
    for c in node.children:
        if c.type in (
            "function_declaration",
            "lexical_declaration",
            "type_alias_declaration",
            "interface_declaration",
            "class_declaration",
            "variable_declaration",
        ):
            return c
    return None


def _symbol_from_decl(
    node: tree_sitter.Node, source: bytes, *, exported: bool
) -> Optional[Symbol]:
    """Build a Symbol from a TS/TSX top-level declaration node."""
    if node.type == "function_declaration":
        return _from_function_declaration(node, source, exported=exported)
    if node.type == "lexical_declaration":
        return _from_lexical_declaration(node, source, exported=exported)
    if node.type in ("type_alias_declaration", "interface_declaration"):
        return _from_type_or_interface(node, source, exported=exported)
    if node.type == "class_declaration":
        return _from_class_declaration(node, source, exported=exported)
    return None


def _from_function_declaration(
    node: tree_sitter.Node, source: bytes, *, exported: bool
) -> Optional[Symbol]:
    name_node = node.child_by_field_name("name")
    if name_node is None or name_node.text is None:
        return None
    name = name_node.text.decode("utf-8")
    kind = _classify_function_kind(name, node)
    hooks = _extract_hooks_inside(node) if kind in (Kind.COMPONENT, Kind.HOOK) else ()
    return Symbol(
        name=name,
        kind=kind,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        hooks=hooks,
        exported=exported,
    )


def _from_lexical_declaration(
    node: tree_sitter.Node, source: bytes, *, exported: bool
) -> Optional[Symbol]:
    """`const X = expr` or `const X = forwardRef(...)`."""
    # variable_declarator child carries name + value.
    declarator = next(
        (c for c in node.children if c.type == "variable_declarator"),
        None,
    )
    if declarator is None:
        return None
    name_node = declarator.child_by_field_name("name")
    value_node = declarator.child_by_field_name("value")
    if name_node is None or name_node.text is None:
        return None
    name = name_node.text.decode("utf-8")
    kind = _classify_const_kind(name, value_node)
    hooks = ()
    if value_node is not None and kind in (Kind.COMPONENT, Kind.HOOK):
        hooks = _extract_hooks_inside(value_node)
    return Symbol(
        name=name,
        kind=kind,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        hooks=hooks,
        exported=exported,
    )


def _from_type_or_interface(
    node: tree_sitter.Node, source: bytes, *, exported: bool
) -> Optional[Symbol]:
    name_node = node.child_by_field_name("name")
    if name_node is None or name_node.text is None:
        return None
    return Symbol(
        name=name_node.text.decode("utf-8"),
        kind=Kind.TYPE,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        exported=exported,
    )


def _from_class_declaration(
    node: tree_sitter.Node, source: bytes, *, exported: bool
) -> Optional[Symbol]:
    name_node = node.child_by_field_name("name")
    if name_node is None or name_node.text is None:
        return None
    return Symbol(
        name=name_node.text.decode("utf-8"),
        kind=Kind.CLASS,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        byte_start=node.start_byte,
        byte_end=node.end_byte,
        exported=exported,
    )


def _classify_function_kind(name: str, fn_node: tree_sitter.Node) -> Kind:
    if _is_hook_name(name) and name != "use":
        return Kind.HOOK
    if _is_pascal_case(name) and _body_contains_jsx(fn_node):
        return Kind.COMPONENT
    return Kind.FUNCTION


def _classify_const_kind(
    name: str, value_node: Optional[tree_sitter.Node]
) -> Kind:
    """`const Card = forwardRef(...)` → COMPONENT. Otherwise CONST."""
    if value_node is not None and _is_pascal_case(name):
        if _is_component_factory_call(value_node):
            return Kind.COMPONENT
        if _value_contains_jsx(value_node):
            return Kind.COMPONENT
    if _is_hook_name(name) and value_node is not None and _value_is_function(value_node):
        return Kind.HOOK
    return Kind.CONST


_COMPONENT_FACTORIES = frozenset({"forwardRef", "memo"})


def _is_component_factory_call(value_node: tree_sitter.Node) -> bool:
    """True if value is a call to forwardRef / memo (with or without
    React. namespace prefix)."""
    if value_node.type != "call_expression":
        return False
    fn = value_node.child_by_field_name("function")
    if fn is None or fn.text is None:
        return False
    fname = fn.text.decode("utf-8")
    tail = fname.rsplit(".", 1)[-1]
    return tail in _COMPONENT_FACTORIES


def _value_contains_jsx(value_node: tree_sitter.Node) -> bool:
    return _node_contains_type(value_node, _JSX_NODE_TYPES)


def _value_is_function(value_node: tree_sitter.Node) -> bool:
    return value_node.type in (
        "arrow_function", "function_expression", "function",
    )


_JSX_NODE_TYPES = frozenset({
    "jsx_element", "jsx_self_closing_element", "jsx_fragment",
})


def _body_contains_jsx(node: tree_sitter.Node) -> bool:
    body = node.child_by_field_name("body")
    if body is None:
        return False
    return _node_contains_type(body, _JSX_NODE_TYPES)


def _node_contains_type(root: tree_sitter.Node, types: frozenset[str]) -> bool:
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type in types:
            return True
        stack.extend(n.children)
    return False


def _extract_hooks_inside(node: tree_sitter.Node) -> tuple[str, ...]:
    """Walk the node's subtree, return the ordered, deduplicated list
    of hook names called inside.
    """
    out: list[str] = []
    seen: set[str] = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None and fn.text is not None:
                call_name = fn.text.decode("utf-8")
                short = call_name.rsplit(".", 1)[-1]
                if short in _KNOWN_HOOKS or _is_hook_name(short):
                    if short not in seen and short != "use":
                        seen.add(short)
                        out.append(short)
        stack.extend(n.children)
    return tuple(out)


# ── Call graph (CP-015) ─────────────────────────────────────────────────


def build_call_graph_tsx(result: ParseResult, file_path: str) -> list[CallEdge]:
    """Edges per source-file:

    - Caller = enclosing function/component/hook qualified name.
    - Callee = name of the JSX element OR identifier in a call expression.

    Both call-expressions and JSX usages contribute. The latter is
    the unique-to-TSX signal (``<Card .../>`` doesn't appear as a
    bare call in the AST).
    """
    out: list[CallEdge] = []
    symbols = extract_symbols_tsx(result)
    pairs = qualified_names_for_module(file_path, symbols)
    for sym, qname in pairs:
        if sym.kind not in (Kind.FUNCTION, Kind.COMPONENT, Kind.HOOK, Kind.METHOD):
            continue
        # Find the underlying function node for this symbol.
        fn_node = _find_function_for_symbol(result.tree.root_node, sym)
        if fn_node is None:
            continue
        for ce in _walk_edges(fn_node, result.source):
            out.append(CallEdge(caller=qname, callee=ce[0], line=ce[1]))
    return out


def _find_function_for_symbol(
    root: tree_sitter.Node, symbol: Symbol
) -> Optional[tree_sitter.Node]:
    candidate = root.descendant_for_byte_range(symbol.byte_start, symbol.byte_end)
    while candidate is not None:
        if candidate.start_byte == symbol.byte_start and candidate.type in (
            "function_declaration",
            "lexical_declaration",
            "function_expression",
            "arrow_function",
        ):
            return candidate
        candidate = candidate.parent
    return None


def _walk_edges(
    root: tree_sitter.Node, source: bytes
) -> Iterable[tuple[str, int]]:
    """Yield (callee_name, line_1_indexed) for every call_expression
    and JSX element under ``root``.
    """
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None and fn.text is not None:
                yield (
                    source[fn.start_byte:fn.end_byte].decode("utf-8").strip(),
                    n.start_point[0] + 1,
                )
        elif n.type in ("jsx_element", "jsx_self_closing_element"):
            name = _jsx_element_name(n, source)
            if name is not None:
                yield (name, n.start_point[0] + 1)
        stack.extend(n.children)


def _jsx_element_name(
    node: tree_sitter.Node, source: bytes
) -> Optional[str]:
    """Return the tag name of a JSX element, e.g. ``Card`` for
    ``<Card label={...}/>``.

    ``jsx_self_closing_element`` exposes the name via the ``name``
    field. ``jsx_element`` wraps an ``jsx_opening_element`` whose
    name field is what we want.
    """
    if node.type == "jsx_self_closing_element":
        name_node = node.child_by_field_name("name")
    else:
        opening = next(
            (c for c in node.children if c.type == "jsx_opening_element"),
            None,
        )
        if opening is None:
            return None
        name_node = opening.child_by_field_name("name")
    if name_node is None or name_node.text is None:
        return None
    raw = source[name_node.start_byte:name_node.end_byte].decode("utf-8").strip()
    # Filter out lower-case HTML element names (``div``, ``span``) —
    # those aren't symbols we care about for the call graph.
    if not raw or not raw[0].isupper():
        return None
    return raw
