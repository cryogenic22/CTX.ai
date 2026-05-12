"""CP-010 — Symbol → IREntity emitter.

Pulls together everything CP-002 through CP-009 ship:

- `parse_python` → ParseResult (CP-002)
- `extract_symbols` → list[Symbol] (CP-003/CP-004) including
  decorator metadata (CP-005)
- `extract_route` / `extract_dependencies` / `is_pydantic_model` /
  `pydantic_fields` semantic interpreters (CP-006/007/008)
- `qualified_names_for_module` for stable globally-unique names
  (CP-009)

…and produces a list of ``IREntity`` ready to flow into the existing
hydrator / catalog / grounding stack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

import tree_sitter

from ctxpack.core.code.metadata import (
    Dependency,
    extract_dependencies,
    extract_route,
    is_pydantic_model,
    pydantic_fields,
)
from ctxpack.core.code.naming import qualified_names_for_module
from ctxpack.core.code.parser import ParseResult
from ctxpack.core.code.symbols import Decorator, Kind, Symbol, extract_symbols
from ctxpack.core.code.tokens import count_bpe
from ctxpack.core.layers import ContextLayer
from ctxpack.core.packer.ir import IREntity, IRField, IRSource

PathLike = Union[str, Path]


_BODY_BPE_CAP = 16_000
_DOCSTRING_BPE_CAP = 1_000


def emit_irentities(
    result: ParseResult,
    file_path: PathLike,
    *,
    include_body: bool = True,
) -> list[IREntity]:
    """Produce one :class:`IREntity` per extracted symbol.

    ``file_path`` is the path used for qualified naming (CP-009). It
    is normalised to forward slashes internally.
    """
    symbols = extract_symbols(result)
    pairs = qualified_names_for_module(file_path, symbols)
    file_str = str(file_path).replace("\\", "/")
    out: list[IREntity] = []
    for symbol, qname in pairs:
        ent = _emit_one(
            result=result,
            symbol=symbol,
            qualified=qname,
            file_path=file_str,
            include_body=include_body,
        )
        out.append(ent)
    return out


def _emit_one(
    *,
    result: ParseResult,
    symbol: Symbol,
    qualified: str,
    file_path: str,
    include_body: bool,
) -> IREntity:
    fields: list[IRField] = []
    _push(fields, "kind", symbol.kind.value)

    sig = _signature(result, symbol)
    if sig:
        _push(fields, "signature", sig)

    # Always emit docstring (possibly empty) so consumers don't need
    # to handle the "field missing vs. empty" distinction.
    doc = _docstring(result, symbol)
    _push(fields, "docstring", _truncate(doc, _DOCSTRING_BPE_CAP) if doc else "")

    if include_body and symbol.kind in (
        Kind.FUNCTION,
        Kind.METHOD,
        Kind.CLASS,
    ):
        body = result.source[symbol.byte_start:symbol.byte_end].decode("utf-8")
        _push(fields, "body", _truncate(body, _BODY_BPE_CAP))

    if symbol.decorators:
        _push(
            fields,
            "decorators",
            json.dumps([d.name for d in symbol.decorators]),
        )
        _push(
            fields,
            "decorators_full",
            json.dumps(
                [
                    {
                        "name": d.name,
                        "args": list(d.args),
                        "kwargs": [list(kv) for kv in d.kwargs],
                        "line": d.line,
                    }
                    for d in symbol.decorators
                ]
            ),
        )

    route = extract_route(symbol)
    if route is not None:
        _push(fields, "http_method", route.http_method)
        if route.http_path is not None:
            _push(fields, "http_path", route.http_path)

    deps = extract_dependencies(result, symbol)
    if deps:
        _push(
            fields,
            "dependencies",
            json.dumps(
                [{"parameter": d.parameter, "target": d.target} for d in deps]
            ),
        )

    if symbol.kind is Kind.CLASS and is_pydantic_model(result, symbol):
        pyf = pydantic_fields(result, symbol)
        if pyf:
            _push(
                fields,
                "pydantic_fields",
                json.dumps(
                    [
                        {
                            "name": f.name,
                            "type": f.type_source,
                            "default": f.default_source,
                        }
                        for f in pyf
                    ]
                ),
            )

    # CP-019/20 placeholder. Real value lands when the ranker ships.
    _push(fields, "centrality_prior", "0.0")

    sources = [
        IRSource(
            file=file_path,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
        )
    ]

    return IREntity(
        name=qualified,
        fields=fields,
        sources=sources,
        layer=ContextLayer.RULES,
        confidence=1.0,
    )


def _push(fields: list[IRField], key: str, value: str) -> None:
    fields.append(
        IRField(
            key=key,
            value=value,
            layer=ContextLayer.RULES,
            confidence=1.0,
        )
    )


def _signature(result: ParseResult, symbol: Symbol) -> str:
    """Render the first line of the def/class header up to (and
    including) the closing colon. Multi-line signatures collapse to
    a single ` `-joined line.
    """
    body_node = _body_owning_node(result.tree.root_node, symbol)
    if body_node is None:
        # Fall back to first source line.
        return _first_line(result.source[symbol.byte_start:symbol.byte_end])
    body_field = body_node.child_by_field_name("body")
    if body_field is None:
        return _first_line(result.source[symbol.byte_start:symbol.byte_end])
    sig_bytes = result.source[symbol.byte_start:body_field.start_byte]
    sig = sig_bytes.decode("utf-8")
    # Multi-line signatures: collapse newlines, drop trailing colon
    # whitespace.
    sig = " ".join(sig.split())
    return sig.rstrip()


def _docstring(result: ParseResult, symbol: Symbol) -> str:
    """Return the docstring text (no quotes) if the first statement of
    the symbol's body is a string literal, else ''.
    """
    node = _body_owning_node(result.tree.root_node, symbol)
    if node is None:
        return ""
    body = node.child_by_field_name("body")
    if body is None or not body.children:
        return ""
    first = body.children[0]
    if first.type != "expression_statement" or not first.children:
        return ""
    s = first.children[0]
    if s.type != "string":
        return ""
    # The string includes its surrounding quotes; pull just the content.
    raw = result.source[s.start_byte:s.end_byte].decode("utf-8")
    return _strip_quotes(raw)


def _body_owning_node(
    root: tree_sitter.Node, symbol: Symbol
) -> Optional[tree_sitter.Node]:
    if symbol.kind not in (Kind.FUNCTION, Kind.METHOD, Kind.CLASS):
        return None
    target_types = ("function_definition", "class_definition")
    candidate = root.descendant_for_byte_range(
        symbol.byte_start, symbol.byte_end
    )
    while candidate is not None:
        if (
            candidate.type in target_types
            and candidate.start_byte == symbol.byte_start
        ):
            return candidate
        candidate = candidate.parent
    return None


def _strip_quotes(raw: str) -> str:
    """Remove the surrounding quote pair from a string literal source.

    Handles single-quoted, double-quoted, and triple-quoted variants
    plus the usual prefix flags (r, b, u, f and their uppercase forms).
    """
    # Drop any prefix flags up to the quote.
    i = 0
    while i < len(raw) and raw[i] not in ("'", '"'):
        i += 1
    body = raw[i:]
    triple_double = '"' * 3
    triple_single = "'" * 3
    for delim in (triple_double, triple_single):
        if body.startswith(delim) and body.endswith(delim):
            return body[len(delim):-len(delim)].strip()
    if (
        len(body) >= 2
        and body[0] == body[-1]
        and body[0] in ('"', "'")
    ):
        return body[1:-1]
    return body


def _first_line(b: bytes) -> str:
    text = b.decode("utf-8", errors="replace")
    return text.split("\n", 1)[0].strip()


def _truncate(text: str, cap: int) -> str:
    """Truncate ``text`` to ``cap`` BPE tokens, appending a marker.

    Uses the pinned BPE tokeniser (CP-002.5) so the budget aligns with
    every other size-measurement call site.
    """
    if count_bpe(text) <= cap:
        return text
    # Character-level binary search to find a slice that fits.
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_bpe(text[:mid]) <= cap:
            lo = mid
        else:
            hi = mid - 1
    truncated = text[:lo]
    remaining = len(text) - lo
    marker = f"\n[truncated {remaining} bytes for BPE budget]"
    return truncated + marker
