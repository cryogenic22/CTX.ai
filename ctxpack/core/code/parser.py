"""Tree-sitter Python parser wrapper (CP-002).

Single entry point: ``parse_python(path) -> ParseResult``.

The wrapper is intentionally thin. It exists so:

1. Every downstream extractor (CP-003+) goes through one parser
   configuration and one set of conventions (utf-8, 1-indexed lines).
2. Syntax errors don't crash the pipeline — they become warnings on
   the result, and the partial tree remains usable.
3. There is a single place to switch tree-sitter binding versions
   when the underlying API moves (it has moved twice already).

No symbol extraction here; that's CP-003.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Union

import tree_sitter
import tree_sitter_python

if TYPE_CHECKING:
    pass


# ── Parser singleton ────────────────────────────────────────────────────


_PARSER_LOCK = threading.Lock()
_PY_LANGUAGE: tree_sitter.Language | None = None
_PY_PARSER: tree_sitter.Parser | None = None


def _get_parser() -> tree_sitter.Parser:
    """Return a process-wide Python parser, lazily initialised.

    Tree-sitter Parser instances are cheap to reuse but not documented
    as thread-safe; the lock protects initialisation. Concurrent calls
    to ``parse_python`` from multiple threads serialise on the parser's
    internal state — fine for our usage (mostly single-threaded pack
    pipelines).
    """
    global _PY_LANGUAGE, _PY_PARSER
    if _PY_PARSER is not None:
        return _PY_PARSER
    with _PARSER_LOCK:
        if _PY_PARSER is None:
            _PY_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())
            _PY_PARSER = tree_sitter.Parser(_PY_LANGUAGE)
    return _PY_PARSER


# ── Result types ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParseWarning:
    """One issue detected during partial-parse.

    Lines are 1-indexed for human consumption (matches editors).
    Columns are 0-indexed (matches tree-sitter's Point convention).
    """

    message: str
    line_start: int
    line_end: int
    column_start: int
    column_end: int


@dataclass
class ParseResult:
    """Parsed-file artifact carried through CP-003+.

    ``tree`` is the raw tree-sitter ``Tree``. ``source`` is the bytes
    the parser consumed; downstream extractors slice
    ``source[node.start_byte:node.end_byte]`` to recover identifier
    and body text without re-reading the file.
    """

    path: Path
    tree: tree_sitter.Tree
    source: bytes
    warnings: list[ParseWarning] = field(default_factory=list)

    @property
    def root(self) -> tree_sitter.Node:
        return self.tree.root_node


# ── Public API ──────────────────────────────────────────────────────────


PathLike = Union[str, Path]


def parse_python(path: PathLike) -> ParseResult:
    """Parse a Python source file.

    Returns a :class:`ParseResult` whose ``tree`` is always a usable
    tree-sitter ``Tree`` (possibly with error nodes) and whose
    ``warnings`` list captures every error / missing-token span the
    parser recovered around.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        IsADirectoryError: if ``path`` refers to a directory.
        UnicodeDecodeError: deferred — we hand raw bytes to
            tree-sitter, which is byte-oriented; surfacing a clean
            decoding error before that point would require eagerly
            decoding the file, which we explicitly avoid. Source bytes
            stay raw on the result so extractors can slice cleanly.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.is_dir():
        raise IsADirectoryError(p)

    source = p.read_bytes()
    parser = _get_parser()
    tree = parser.parse(source)
    warnings = _collect_warnings(tree.root_node)

    return ParseResult(path=p, tree=tree, source=source, warnings=warnings)


# ── Warning collection ─────────────────────────────────────────────────


def _collect_warnings(root: tree_sitter.Node) -> list[ParseWarning]:
    """Walk the tree iteratively, collecting one warning per error /
    missing node.

    Iterative rather than recursive because tree-sitter trees can be
    deep on large files and Python's default recursion limit is 1000.
    """
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
            # Only descend through subtrees that contain errors;
            # everything else is clean and need not be walked.
            if node.has_error:
                stack.extend(node.children)
    return warnings
