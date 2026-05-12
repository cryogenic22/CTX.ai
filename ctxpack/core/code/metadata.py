"""Semantic interpreters over extracted symbols.

Three pure-helper APIs built on the CP-005 decorator capture:

- :func:`extract_route` — interpret FastAPI-style route decorators.
- :func:`extract_dependencies` — find ``Depends(...)`` parameters.
- :func:`is_pydantic_model` — does this class inherit ``BaseModel``?

These do NOT mutate the Symbol; they're consulted at IREntity-emission
time (CP-010) to populate route/dependency/pydantic fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import tree_sitter

from ctxpack.core.code.parser import ParseResult
from ctxpack.core.code.symbols import Decorator, Kind, Symbol


# ── CP-006: FastAPI route detection ────────────────────────────────────


HTTP_METHODS = frozenset({
    "get", "post", "put", "patch",
    "delete", "head", "options", "trace",
})


@dataclass(frozen=True)
class RouteInfo:
    """A FastAPI route detected on a function/method.

    ``http_path`` is the raw source text of the first positional
    decorator argument (quotes preserved). ``None`` when the decorator
    is used without a call (``@app.get`` rather than ``@app.get(...)``).
    """

    http_method: str
    http_path: Optional[str]


def extract_route(symbol: Symbol) -> Optional[RouteInfo]:
    """Return :class:`RouteInfo` for the first FastAPI-style route
    decorator on ``symbol``, else ``None``.

    A decorator counts as a route when its dotted name ends in a
    recognised HTTP method (``app.get`` / ``router.post`` /
    ``v1_router.delete`` etc.).
    """
    for d in symbol.decorators:
        method = _http_method_from_decorator(d)
        if method is None:
            continue
        path = d.args[0] if d.args else None
        return RouteInfo(http_method=method.upper(), http_path=path)
    return None


def _http_method_from_decorator(d: Decorator) -> Optional[str]:
    if "." not in d.name:
        return None
    tail = d.name.rsplit(".", 1)[-1]
    if tail in HTTP_METHODS:
        return tail
    return None


# ── CP-007: FastAPI Depends(...) extraction ─────────────────────────────


@dataclass(frozen=True)
class Dependency:
    """A FastAPI ``Depends(target)`` parameter on a function/method."""

    parameter: str  # the local parameter name (e.g. "db")
    target: str    # source text of the first positional arg to Depends


def extract_dependencies(
    result: ParseResult, symbol: Symbol
) -> list[Dependency]:
    """Return ``Depends(...)`` parameters declared on ``symbol``.

    Only function/method symbols are inspected. Classes and class
    attributes return ``[]``. Non-Depends defaults are ignored.
    """
    if symbol.kind not in (Kind.FUNCTION, Kind.METHOD):
        return []
    fn_node = _find_function_node(result.tree.root_node, symbol)
    if fn_node is None:
        return []
    params = fn_node.child_by_field_name("parameters")
    if params is None:
        return []
    out: list[Dependency] = []
    for child in params.children:
        if child.type not in ("default_parameter", "typed_default_parameter"):
            continue
        dep = _depends_from_default_param(child, source=result.source)
        if dep is not None:
            out.append(dep)
    return out


def _find_function_node(
    root: tree_sitter.Node, symbol: Symbol
) -> Optional[tree_sitter.Node]:
    """Return the function_definition node whose byte range matches the
    symbol exactly. ``descendant_for_byte_range`` is the cheap path —
    it returns the smallest node covering the range.
    """
    candidate = root.descendant_for_byte_range(symbol.byte_start, symbol.byte_end)
    while candidate is not None:
        if (
            candidate.type == "function_definition"
            and candidate.start_byte == symbol.byte_start
        ):
            return candidate
        candidate = candidate.parent
    return None


# ── CP-008: Pydantic BaseModel detection ────────────────────────────────


@dataclass(frozen=True)
class PydanticField:
    """A typed class attribute on a Pydantic model.

    ``type_source`` and ``default_source`` are raw source text (no
    eval) so downstream consumers can present the user's exact text.
    ``default_source`` is ``None`` for fields without a default.
    """

    name: str
    type_source: str
    default_source: Optional[str]


def is_pydantic_model(result: ParseResult, symbol: Symbol) -> bool:
    """True if ``symbol`` is a class whose superclass list contains
    ``BaseModel`` (bare or dotted, e.g. ``pydantic.BaseModel``).
    """
    if symbol.kind is not Kind.CLASS:
        return False
    class_node = _find_class_node(result.tree.root_node, symbol)
    if class_node is None:
        return False
    superclasses = class_node.child_by_field_name("superclasses")
    if superclasses is None:
        return False
    for child in superclasses.children:
        if child.type in ("(", ")", ",", "keyword_argument"):
            continue
        if child.text is None:
            continue
        text = child.text.decode("utf-8").strip()
        # Bare 'BaseModel' or dotted '<package>.BaseModel'
        if text == "BaseModel":
            return True
        if "." in text and text.rsplit(".", 1)[-1] == "BaseModel":
            return True
    return False


def pydantic_fields(
    result: ParseResult, symbol: Symbol
) -> list[PydanticField]:
    """Return the typed class attributes of ``symbol``.

    Only returns fields for classes that pass ``is_pydantic_model``;
    other classes (and non-class symbols) return ``[]``.
    """
    if not is_pydantic_model(result, symbol):
        return []
    class_node = _find_class_node(result.tree.root_node, symbol)
    if class_node is None:
        return []
    body = class_node.child_by_field_name("body")
    if body is None:
        return []
    out: list[PydanticField] = []
    for member in body.children:
        if member.type != "expression_statement":
            continue
        if not member.children:
            continue
        assignment = member.children[0]
        if assignment.type != "assignment":
            continue
        left = assignment.child_by_field_name("left")
        type_node = assignment.child_by_field_name("type")
        value_node = assignment.child_by_field_name("right")
        if (
            left is None
            or left.type != "identifier"
            or left.text is None
            or type_node is None
        ):
            # Pydantic v2 still accepts untyped attrs but they're not
            # validated fields. Skip them.
            continue
        type_text = result.source[
            type_node.start_byte:type_node.end_byte
        ].decode("utf-8")
        default_text: Optional[str] = None
        if value_node is not None:
            default_text = result.source[
                value_node.start_byte:value_node.end_byte
            ].decode("utf-8")
        out.append(
            PydanticField(
                name=left.text.decode("utf-8"),
                type_source=type_text,
                default_source=default_text,
            )
        )
    return out


def _find_class_node(
    root: tree_sitter.Node, symbol: Symbol
) -> Optional[tree_sitter.Node]:
    candidate = root.descendant_for_byte_range(
        symbol.byte_start, symbol.byte_end
    )
    while candidate is not None:
        if (
            candidate.type == "class_definition"
            and candidate.start_byte == symbol.byte_start
        ):
            return candidate
        candidate = candidate.parent
    return None


def _depends_from_default_param(
    param: tree_sitter.Node, *, source: bytes
) -> Optional[Dependency]:
    """If `param.value` is a `Depends(target)` call, return a Dependency.

    Both ``default_parameter`` (``db=Depends(get_db)``) and
    ``typed_default_parameter`` (``db: Session = Depends(get_db)``)
    share the ``name`` and ``value`` fields.
    """
    name_node = param.child_by_field_name("name")
    value_node = param.child_by_field_name("value")
    if name_node is None or value_node is None or name_node.text is None:
        return None
    if value_node.type != "call":
        return None
    fn = value_node.child_by_field_name("function")
    if fn is None or fn.text is None or fn.text.decode("utf-8") != "Depends":
        return None
    args = value_node.child_by_field_name("arguments")
    if args is None:
        return None
    for arg in args.children:
        if arg.type in ("(", ")", ",", "keyword_argument"):
            continue
        return Dependency(
            parameter=name_node.text.decode("utf-8"),
            target=source[arg.start_byte:arg.end_byte].decode("utf-8"),
        )
    return None
