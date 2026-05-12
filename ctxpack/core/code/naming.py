"""CP-009 — qualified naming for code-packer symbols.

The Symbol.name produced by CP-003/CP-004 is the local identifier
(``main`` or ``Widget.tick``). For globally-unique entity IDs in the
IR layer we need ``<path>::<local>`` plus disambiguation when local
names collide (e.g. ``@overload`` defs).

Paths are normalised to forward slashes so qualified names compare
equal across Windows and POSIX hosts. The slash on the *prefix* is
the convention; symbols' dotted forms (``Widget.tick``) keep their
dots.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Union

from ctxpack.core.code.symbols import Symbol

PathLike = Union[str, Path]


def qualified_name(file_path: PathLike, symbol: Symbol) -> str:
    """Return ``<file>::<symbol.name>`` with forward-slash path.

    Does not handle name collisions — caller passes one symbol at a
    time. For a list of symbols that may share names, use
    :func:`qualified_names_for_module`.
    """
    return f"{_normalised(file_path)}::{symbol.name}"


def qualified_names_for_module(
    file_path: PathLike,
    symbols: list[Symbol],
) -> list[tuple[Symbol, str]]:
    """Pair each symbol with a unique qualified name within this file.

    Order is preserved. When two symbols would qualify to the same
    name, the first keeps the base form and subsequent ones get
    ``#1``, ``#2``, ... suffixes in the input (file) order.

    Cross-scope same-local-name (top-level ``foo`` and method
    ``Widget.foo``) does NOT collide — they have different
    ``symbol.name`` strings already.
    """
    prefix = _normalised(file_path)
    base_counts: Counter[str] = Counter()
    out: list[tuple[Symbol, str]] = []
    for s in symbols:
        base = f"{prefix}::{s.name}"
        seen = base_counts[base]
        base_counts[base] += 1
        if seen == 0:
            out.append((s, base))
        else:
            out.append((s, f"{base}#{seen}"))
    return out


def _normalised(file_path: PathLike) -> str:
    return str(file_path).replace("\\", "/")
