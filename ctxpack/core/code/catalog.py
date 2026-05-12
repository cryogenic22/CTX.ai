"""CP-010.3 — catalog row rendering with soft-cap truncation.

A catalog row is the agent's first look at a symbol: name, kind,
signature, and the opening line of the docstring. Rows are budgeted
to ~120 BPE so a full module's catalog stays cheap to scan even when
the module contains hundreds of Pydantic models.

When a row exceeds the cap, we truncate the **signature** (not the
name, which is the agent's anchor for follow-up hydrate calls) and
prefer to break at one of ``, ] ) > [ ( <`` or whitespace so the
truncation doesn't land mid-identifier.
"""

from __future__ import annotations

from ctxpack.core.code.tokens import count_bpe
from ctxpack.core.packer.ir import IREntity


_DEFAULT_CAP = 120
_ELLIPSIS = "…"
_BOUNDARY_CHARS = (",", "]", ")", ">", "[", "(", "<", " ", "\t")
# Allowed overhead beyond `cap`: name + kind + small framing tokens
# that we never truncate. Picked empirically; not load-bearing.
_OVERHEAD_BUDGET = 10


def render_catalog_row(entity: IREntity, *, cap: int = _DEFAULT_CAP) -> str:
    """Render a catalog row for ``entity``, soft-capped to ``cap`` BPE.

    Format: ``"<name> | <kind> | <signature> | <docstring 1st line>"``.
    Missing fields are skipped cleanly (no trailing pipes).
    """
    fields = {f.key: f.value for f in entity.fields}
    kind = fields.get("kind", "")
    sig = fields.get("signature", "")
    doc_first = _first_line(fields.get("docstring", ""))

    full = _join(entity.name, kind, sig, doc_first)
    if count_bpe(full) <= cap:
        return full

    # Truncate the signature first; doc and kind stay since they're tiny.
    truncated_sig = _truncate_signature(sig, cap=cap, name=entity.name,
                                        kind=kind, doc=doc_first)
    return _join(entity.name, kind, truncated_sig, doc_first)


def _truncate_signature(
    sig: str,
    *,
    cap: int,
    name: str,
    kind: str,
    doc: str,
) -> str:
    """Find the longest prefix of ``sig`` such that the rendered row
    fits within ``cap + _OVERHEAD_BUDGET`` BPE, then back up to a
    boundary character and append the ellipsis.
    """
    # Lower bound = empty sig + ellipsis; upper = full sig.
    lo, hi = 0, len(sig)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = sig[:mid] + _ELLIPSIS
        row = _join(name, kind, candidate, doc)
        if count_bpe(row) <= cap + _OVERHEAD_BUDGET:
            lo = mid
        else:
            hi = mid - 1
    cut = lo
    # Back up to a boundary character if there is one within the last
    # 12 chars — otherwise accept the mid-identifier truncation rather
    # than throw away too much signal.
    boundary = _last_boundary(sig, cut, window=12)
    if boundary is not None:
        cut = boundary
    return sig[:cut].rstrip() + _ELLIPSIS


def _last_boundary(s: str, end: int, *, window: int) -> int | None:
    start = max(0, end - window)
    for i in range(end - 1, start - 1, -1):
        if s[i] in _BOUNDARY_CHARS:
            return i + 1  # cut *after* the boundary
    return None


def _join(name: str, kind: str, sig: str, doc: str) -> str:
    parts = [name]
    if kind:
        parts.append(kind)
    if sig:
        parts.append(sig)
    if doc:
        parts.append(doc)
    return " | ".join(parts)


def _first_line(s: str) -> str:
    if not s:
        return ""
    return s.split("\n", 1)[0].strip()
