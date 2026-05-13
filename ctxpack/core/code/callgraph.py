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


def resolve_callees(
    edges: list[CallEdge],
    nodes: set[str],
) -> list[CallEdge]:
    """Map raw callee text (``User``, ``Widget.tick``, ``logger.info``)
    to qualified entity names (``models.py::User``) by local-name
    lookup.

    Heuristic: build a multimap from local-name (and from the tail of
    dotted callees) to qualified names. An edge resolves only when
    exactly one candidate exists — multi-candidate collisions are
    dropped as ambiguous, single-target hits flow through. This is
    good enough for PageRank signal; CP-021's BM25 task_score takes
    over once it's wired.
    """
    from collections import defaultdict

    by_local: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        local = n.split("::", 1)[1] if "::" in n else n
        by_local[local].append(n)
        # Also index by tail of dotted names so ``Widget.tick`` is
        # findable as a callee in another file's ``tick(...)`` call —
        # but the more interesting hit is the *full* dotted form, so
        # we add both.
        if "." in local:
            tail = local.rsplit(".", 1)[-1]
            by_local[tail].append(n)

    nodes_set = nodes  # set lookup
    out: list[CallEdge] = []
    for edge in edges:
        # Idempotent fast path: if the callee is already a qualified
        # name in our node set, accept it as-is. This matters for
        # incremental packs where reused edges come back already-
        # resolved.
        if edge.callee in nodes_set:
            out.append(edge)
            continue
        candidates = by_local.get(edge.callee, [])
        if not candidates and "." in edge.callee:
            tail = edge.callee.rsplit(".", 1)[-1]
            candidates = by_local.get(tail, [])
        if len(candidates) == 1:
            out.append(
                CallEdge(
                    caller=edge.caller,
                    callee=candidates[0],
                    line=edge.line,
                )
            )
        # Multi-candidate collisions are dropped (ambiguous). No-match
        # callees (stdlib, third-party) are also dropped — they're
        # outside our node set and can't contribute to centrality.
    return out
