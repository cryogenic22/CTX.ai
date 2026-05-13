"""CP-011 — tree-sitter TSX parser wrapper.

Sibling to ``parser.py`` (Python). Reuses ``ParseResult`` /
``ParseWarning`` from that module so downstream extractors don't
need to know whether the file is Python or TSX.

API:

    parse_tsx(path) -> ParseResult

Parses ``.tsx`` and ``.ts`` files. The TSX grammar is a superset
of TypeScript — using the TSX variant means we handle JSX cleanly
when it appears, and treat its absence as just-TypeScript.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Union

import tree_sitter
import tree_sitter_typescript

from ctxpack.core.code.parser import ParseResult, ParseWarning


PathLike = Union[str, Path]


_PARSER_LOCK = threading.Lock()
_TSX_LANGUAGE: tree_sitter.Language | None = None
_TSX_PARSER: tree_sitter.Parser | None = None


def _get_parser() -> tree_sitter.Parser:
    global _TSX_LANGUAGE, _TSX_PARSER
    if _TSX_PARSER is not None:
        return _TSX_PARSER
    with _PARSER_LOCK:
        if _TSX_PARSER is None:
            _TSX_LANGUAGE = tree_sitter.Language(
                tree_sitter_typescript.language_tsx()
            )
            _TSX_PARSER = tree_sitter.Parser(_TSX_LANGUAGE)
    return _TSX_PARSER


def parse_tsx(path: PathLike) -> ParseResult:
    """Parse a .tsx or .ts file. Same shape as ``parse_python``."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.is_dir():
        raise IsADirectoryError(p)
    source = p.read_bytes()
    tree = _get_parser().parse(source)
    warnings = _collect_warnings(tree.root_node)
    return ParseResult(path=p, tree=tree, source=source, warnings=warnings)


def _collect_warnings(root: tree_sitter.Node) -> list[ParseWarning]:
    if not root.has_error:
        return []
    warnings: list[ParseWarning] = []
    stack: list[tree_sitter.Node] = [root]
    while stack:
        node = stack.pop()
        if node.is_error:
            warnings.append(
                ParseWarning(
                    message="syntax error",
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    column_start=node.start_point[1],
                    column_end=node.end_point[1],
                )
            )
        elif node.is_missing:
            warnings.append(
                ParseWarning(
                    message=f"missing token: {node.type}",
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    column_start=node.start_point[1],
                    column_end=node.end_point[1],
                )
            )
        else:
            if node.has_error:
                stack.extend(node.children)
    return warnings
