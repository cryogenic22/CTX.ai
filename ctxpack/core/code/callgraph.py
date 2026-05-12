"""CP-014 — Python static call graph (best-effort).

For each function/method symbol in a file, walk its body and record
every ``call`` node. We deliberately keep this naive:

- Callee text is captured verbatim (``User``, ``self._ticks``,
  ``logger.info``). No name resolution, no ``self``→class rewriting,
  no import tracing.
- Dynamic dispatch (``getattr``, ``**kwargs`` forwarding) is invisible
  — same caveat that applies to every static call graph in Python.

Despite the limitations, the raw edge list is enough for:
- CP-019 PageRank (popular callees get rank).
- ``callers_static`` / ``callees_static`` IRField rendering (with the
  ``_static`` suffix making the imprecision explicit to the agent).
"""

from __future__ import annotations

from dataclasses import dataclass

import tree_sitter

from ctxpack.core.code.naming import qualified_names_for_module
from ctxpack.core.code.parser import ParseResult
from ctxpack.core.code.symbols import Kind, Symbol, extract_symbols


@dataclass(frozen=True)
class CallEdge:
    """One call-site from ``caller`` to ``callee``."""

    caller: str  # qualified name from CP-009
    callee: str  # raw call expression text
    line: int    # 1-indexed line of the call site


def build_call_graph(result: ParseResult, file_path: str) -> list[CallEdge]:
    """Return all call edges in ``result``, keyed by caller's
    qualified name.

    Functions, methods, and classes (their ``__init__`` body counted
    via the method walk) all contribute. Class attributes and class
    bodies that aren't methods contribute no edges.
    """
    symbols = extract_symbols(result)
    pairs = qualified_names_for_module(file_path, symbols)
    out: list[CallEdge] = []
    for sym, qname in pairs:
        if sym.kind not in (Kind.FUNCTION, Kind.METHOD):
            continue
        node = _find_function_node(result.tree.root_node, sym)
        if node is None:
            continue
        body = node.child_by_field_name("body")
        if body is None:
            continue
        for call_node in _walk_calls(body):
            fn = call_node.child_by_field_name("function")
            if fn is None or fn.text is None:
                continue
            callee = result.source[fn.start_byte:fn.end_byte].decode("utf-8")
            out.append(
                CallEdge(
                    caller=qname,
                    callee=callee.strip(),
                    line=call_node.start_point[0] + 1,
                )
            )
    return out


def _find_function_node(
    root: tree_sitter.Node, symbol: Symbol
) -> tree_sitter.Node | None:
    candidate = root.descendant_for_byte_range(symbol.byte_start, symbol.byte_end)
    while candidate is not None:
        if (
            candidate.type == "function_definition"
            and candidate.start_byte == symbol.byte_start
        ):
            return candidate
        candidate = candidate.parent
    return None


def _walk_calls(node: tree_sitter.Node):
    """Iterative pre-order walk yielding every ``call`` descendant."""
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "call":
            yield n
        stack.extend(n.children)
