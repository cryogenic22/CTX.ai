"""The live set: facts that are current.

One function, :func:`live_set_from_records`, decides what the project
gist, the session gist, and the brief render. A fact leaves the live
set when it is superseded, retracted, or stale. History stays in the
ledger; ``ctxpack session why`` still walks the chain.

Supersession ids are exact literals: a ``Supersedes:`` token must be
16 hex or 64 hex, and it matches a fact id only when the strings are
equal. In a mixed ledger a 16-hex token that is also a prefix of a
64-hex id (or the reverse) is ambiguous — it is flagged and not
applied. A unique prefix is not treated as a match.

Staleness (until plan milestone tracking lands) is an input, not a
clock. ``done_milestones`` names milestones or steps that are done.
A fact is stale only when every milestone/step scope in its text is
in that set and it has at least one such scope:

- ``until|during|in|for|within|scoped to <milestone|step> <id>``
- ``<milestone|step> <id> will``

Ids are compared case-insensitively. A leading ``milestone`` / ``step``
word is stripped, and ``m`` plus digits (``m4``) collapses to the
digits. A fact with no scope marker is never stale. An empty
``done_milestones`` drops nothing, so ledgers that never declared a
supersession or a done milestone render as they do today.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from ..core.supersession_dag import (
    Conflict,
    SupersessionEdge,
    build_graph,
)

_STAKES = frozenset({"DECISION", "CONSTRAINT", "FAILED-APPROACH"})
_ID_RE = re.compile(r"^[0-9a-f]{16}$|^[0-9a-f]{64}$")
_FACT_ID_RE = re.compile(
    r"(?im)^[ \t]*FACT-ID:[ \t]*([0-9a-fA-F]{64}|[0-9a-fA-F]{16})[ \t]*$")
_LEADING_MARKER_RE = re.compile(
    r"(?i)^(?:decision|conclusion|verdict|confirmed|constraint|invariant|"
    r"rejected|dead end)\s*:\s*")
_SCOPE_RE = re.compile(
    r"(?i)\b(?:until|during|in|for|within|scoped\s+to)\s+"
    r"(?:milestone|step)\s+([A-Za-z0-9][A-Za-z0-9._-]*)"
    r"|\b(?:milestone|step)\s+([A-Za-z0-9][A-Za-z0-9._-]*)\s+will\b")
_MILESTONE_PREFIX_RE = re.compile(r"^(?:milestone|step)\s+")

_PRIMARY = {
    "DECISION": "DECISION",
    "CONSTRAINT": "RULE",
    "FAILED-APPROACH": "NOTE",
    "USER-REQUEST": "REQUEST",
    "FINDING": "FINDING",
    "RETRACT": "RETRACTS-FACT-ID",
}


@dataclass(frozen=True)
class FactView:
    fact_id: str
    kind: str
    text: str
    turn: int
    session: str = ""
    basis: str = ""


@dataclass(frozen=True)
class Replacement:
    old_id: str
    new_id: str
    old_text: str
    new_text: str
    reason: str
    turn: int
    session: str = ""


@dataclass(frozen=True)
class AmbiguousRef:
    token: str
    matches: tuple[str, ...]


@dataclass(frozen=True)
class ForkView:
    roots: tuple[str, ...]
    heads: tuple[tuple[str, str], ...]  # (fact_id, text)


@dataclass(frozen=True)
class LiveSet:
    facts: tuple[FactView, ...]
    replacements: tuple[Replacement, ...]
    conflicts: tuple[ForkView, ...]
    ambiguous: tuple[AmbiguousRef, ...]
    retracted: tuple[tuple[str, str], ...]  # (fact_id, reason)
    stale: tuple[FactView, ...]

    @property
    def live_ids(self) -> frozenset[str]:
        return frozenset(f.fact_id for f in self.facts)


def normalize_milestone(token: str) -> str:
    """Canonical milestone/step id. ``Milestone 4``, ``m4``, and ``4`` agree."""
    text = " ".join(str(token or "").strip().lower().split())
    text = _MILESTONE_PREFIX_RE.sub("", text)
    if len(text) >= 2 and text[0] == "m" and text[1:].isdigit():
        text = text[1:]
    return text


def scope_ids(text: str) -> tuple[str, ...]:
    """Milestone/step ids the text is scoped to, in first-seen order."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _SCOPE_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2) or ""
        norm = normalize_milestone(raw)
        if norm and norm not in seen:
            seen.add(norm)
            found.append(norm)
    return tuple(found)


def is_milestone_stale(text: str, done_milestones: Iterable[str]) -> bool:
    """True when every scope in ``text`` is a done milestone or step."""
    done = {normalize_milestone(item) for item in done_milestones}
    done.discard("")
    if not done:
        return False
    scopes = scope_ids(text)
    if not scopes:
        return False
    return all(scope in done for scope in scopes)


def choice_was(text: str) -> str:
    """Old-choice rendering.

    A leading ``Decision:`` / ``Constraint:`` / ``Rejected:`` marker is
    removed so the banked line (marker included) is not repeated as a
    live bullet. The words of the choice stay. Negations are not
    touched: only that one leading marker is removed.
    """
    stripped = _LEADING_MARKER_RE.sub("", text or "", count=1).strip()
    return stripped or (text or "")


def resolve_supersedes_target(token: str, known_ids: Iterable[str]) -> dict[str, Any]:
    """Exact-literal resolution of a 16-hex or 64-hex fact id.

    Status is one of ``matched``, ``unmatched``, ``ambiguous``, ``invalid``.

    ``matched`` requires the token equal one known id and no id of the
    other width sharing that prefix. ``ambiguous`` is the mixed-ledger
    case (exact hit plus a longer/shorter sibling, several exact hits,
    or a prefix that would have to be guessed). A unique prefix of a
    longer id is ``ambiguous``, not ``matched``: exact-literal matching
    does not promote a prefix. ``unmatched`` is a well-formed id with
    no sibling and no exact hit — callers may still record it.
    """
    raw = str(token or "").strip().lower()
    if not _ID_RE.fullmatch(raw):
        return {"status": "invalid", "token": raw, "fact_id": "", "matches": ()}
    ids = sorted({str(item).strip().lower() for item in known_ids if str(item).strip()})
    exact = [item for item in ids if item == raw]
    if len(raw) == 16:
        related = [item for item in ids if len(item) == 64 and item.startswith(raw)]
    else:
        related = [item for item in ids if len(item) == 16 and raw.startswith(item)]
    if related or len(exact) > 1:
        matches = tuple(sorted(set(exact) | set(related)))
        return {"status": "ambiguous", "token": raw, "fact_id": "", "matches": matches}
    if len(exact) == 1:
        return {"status": "matched", "token": raw, "fact_id": exact[0], "matches": ()}
    return {"status": "unmatched", "token": raw, "fact_id": "", "matches": ()}


def iter_fact_ids(text: str) -> list[str]:
    """FACT-ID values in a ledger file, file order, lowercased."""
    return [match.group(1).lower() for match in _FACT_ID_RE.finditer(text or "")]


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def select_live_set(
    facts: Sequence[FactView],
    edges: Sequence[SupersessionEdge],
    *,
    done_milestones: Iterable[str] = (),
    retractions: Sequence[tuple[str, str]] = (),
    ambiguous: Sequence[AmbiguousRef] = (),
) -> LiveSet:
    """Facts that are current: not superseded, not retracted, not stale.

    Linear replacements are returned once each under ``replacements``.
    An unresolved fork (two or more live heads) is returned under
    ``conflicts`` and is not collapsed into a single replacement.
    ``ambiguous`` refs are echoed for the caller to flag; they are not
    edges and drop nothing.
    """
    by_id: dict[str, FactView] = {}
    for fact in facts:
        fid = _clean(fact.fact_id).lower()
        if not fid:
            continue
        # First writer wins so a repeated id keeps the earliest text.
        if fid not in by_id:
            by_id[fid] = FactView(
                fact_id=fid,
                kind=_clean(fact.kind).upper(),
                text=fact.text or "",
                turn=_as_int(fact.turn),
                session=_clean(fact.session),
                basis=_clean(fact.basis),
            )

    norm_edges: list[SupersessionEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in edges:
        base = _clean(edge.base).lower()
        head = _clean(edge.head).lower()
        if not base or not head or base == head:
            continue
        key = (base, head, edge.reason or "")
        if key in seen_edges:
            continue
        seen_edges.add(key)
        norm_edges.append(SupersessionEdge(
            base=base,
            head=head,
            turn=_as_int(edge.turn),
            reason=edge.reason or "",
            session=_clean(edge.session),
        ))
    norm_edges.sort(key=lambda e: (e.turn, e.base, e.head, e.session, e.reason))

    graph = build_graph(norm_edges)
    conflict_ids: set[str] = set()
    forks: list[ForkView] = []
    for conflict in graph.conflicts:
        conflict_ids.update(conflict.facts)
        heads = tuple(
            (hid, by_id[hid].text if hid in by_id else "")
            for hid in conflict.heads)
        forks.append(ForkView(roots=tuple(conflict.roots), heads=heads))

    retracted_pairs: list[tuple[str, str]] = []
    retracted_ids: set[str] = set()
    for item in retractions:
        if not item:
            continue
        fid = _clean(item[0]).lower()
        reason = _clean(item[1]) if len(item) > 1 else ""
        if not fid or fid in retracted_ids:
            continue
        retracted_ids.add(fid)
        retracted_pairs.append((fid, reason))
    retracted_pairs.sort(key=lambda pair: pair[0])

    superseded = set(graph.superseded)
    dropped = superseded | retracted_ids

    stale: list[FactView] = []
    live: list[FactView] = []
    for fid in sorted(by_id):
        fact = by_id[fid]
        if fact.kind not in _STAKES:
            continue
        if fid in dropped:
            continue
        if is_milestone_stale(fact.text, done_milestones):
            stale.append(fact)
            continue
        live.append(fact)
    live.sort(key=lambda f: (f.session, f.turn, f.kind, f.fact_id))
    stale.sort(key=lambda f: (f.session, f.turn, f.kind, f.fact_id))

    replacements: list[Replacement] = []
    for edge in norm_edges:
        if edge.base in conflict_ids or edge.head in conflict_ids:
            continue
        old = by_id.get(edge.base)
        new = by_id.get(edge.head)
        replacements.append(Replacement(
            old_id=edge.base,
            new_id=edge.head,
            old_text=old.text if old else "",
            new_text=new.text if new else "",
            reason=edge.reason,
            turn=edge.turn,
            session=edge.session or (new.session if new else ""),
        ))

    amb = tuple(sorted(
        (AmbiguousRef(a.token.lower(), tuple(sorted(a.matches))) for a in ambiguous),
        key=lambda a: (a.token, a.matches),
    ))
    # Dedup identical ambiguous refs.
    dedup_amb: list[AmbiguousRef] = []
    seen_amb: set[tuple[str, tuple[str, ...]]] = set()
    for ref in amb:
        ref_key = (ref.token, ref.matches)
        if ref_key in seen_amb:
            continue
        seen_amb.add(ref_key)
        dedup_amb.append(ref)

    return LiveSet(
        facts=tuple(live),
        replacements=tuple(replacements),
        conflicts=tuple(forks),
        ambiguous=tuple(dedup_amb),
        retracted=tuple(retracted_pairs),
        stale=tuple(stale),
    )


def live_set_from_records(
    records: Sequence[dict[str, Any]],
    *,
    done_milestones: Iterable[str] = (),
) -> LiveSet:
    """Build the live set from flat section/entity records.

    This is the function the project gist, the session gist, and the
    brief call. Each record may carry ``fact_id``, ``kind``, ``text``,
    ``turn``, ``session``, ``basis``, ``supersedes``,
    ``supersedes_reason``, ``retracts``, ``retract_reason``, and
    ``ambiguous`` (``token\\tmatch,match``).
    """
    facts: list[FactView] = []
    edges: list[SupersessionEdge] = []
    retractions: list[tuple[str, str]] = []
    ambiguous: list[AmbiguousRef] = []
    for row in records:
        kind = _clean(row.get("kind")).upper()
        fid = _clean(row.get("fact_id")).lower()
        turn = _as_int(row.get("turn"))
        session = _clean(row.get("session"))
        if fid and kind in _STAKES:
            facts.append(FactView(
                fact_id=fid,
                kind=kind,
                text=str(row.get("text") or ""),
                turn=turn,
                session=session,
                basis=_clean(row.get("basis")),
            ))
        base = _clean(row.get("supersedes")).lower()
        if base and fid and base != fid:
            edges.append(SupersessionEdge(
                base=base,
                head=fid,
                turn=turn,
                reason=_clean(row.get("supersedes_reason")),
                session=session,
            ))
        target = _clean(row.get("retracts")).lower()
        if target:
            retractions.append((target, _clean(row.get("retract_reason"))))
        amb = _clean(row.get("ambiguous"))
        if amb:
            token, _, rest = amb.partition("\t")
            matches = tuple(part for part in rest.split(",") if part)
            if token:
                ambiguous.append(AmbiguousRef(token.lower(), matches))
    return select_live_set(
        facts,
        edges,
        done_milestones=done_milestones,
        retractions=retractions,
        ambiguous=ambiguous,
    )


def render_live_preamble(live: LiveSet) -> list[str]:
    """Markdown lines for conflicts, changed choices, and flags.

    Empty when the live set has nothing to surface, so a ledger with no
    supersession renders exactly as before. The previous choice is shown
    without its leading marker (see :func:`choice_was`); the new choice
    is the full banked sentence.
    """
    lines: list[str] = []
    if live.ambiguous:
        lines.append("")
        lines.append("## Supersession unresolved")
        for item in live.ambiguous:
            joined = ", ".join(f"`{match}`" for match in item.matches) or "(none)"
            lines.append(
                f"- `{item.token}` matches {joined}; not applied.")
    if live.conflicts:
        lines.append("")
        lines.append("## Conflicts (unresolved fork)")
        for fork in live.conflicts:
            roots = ", ".join(f"`{root}`" for root in fork.roots) or "(none)"
            lines.append(
                f"- unresolved fork of {roots}; neither head supersedes the other.")
            for hid, text in fork.heads:
                shown = text if text else "(text not in this ledger)"
                lines.append(f"  - `{hid}`: {shown}")
    if live.replacements:
        lines.append("")
        lines.append("## Changed choices")
        for repl in live.replacements:
            reason = f" — {repl.reason}" if repl.reason else ""
            lines.append(f"- `{repl.old_id}` → `{repl.new_id}`{reason}")
            was = choice_was(repl.old_text) if repl.old_text else "(not in ledger)"
            now = repl.new_text if repl.new_text else "(not in ledger)"
            lines.append(f"  - was: {was}")
            lines.append(f"  - now: {now}")
    if live.retracted:
        lines.append("")
        lines.append("## Retracted")
        for fid, reason in live.retracted:
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- `{fid}` withdrawn{suffix}.")
    if live.stale:
        lines.append("")
        n = len(live.stale)
        noun = "item" if n == 1 else "items"
        lines.append(
            f"_Dropped {n} stale {noun} scoped to a done milestone._")
    return lines


def _efield(entity: Any, key: str) -> str:
    want = key.upper()
    for field in getattr(entity, "fields", ()) or ():
        if str(getattr(field, "key", "")).upper() == want:
            return str(getattr(field, "value", "") or "")
    return ""


def records_from_entities(entities: Iterable[Any], *, session: str = "") -> list[dict[str, Any]]:
    """Flat records for :func:`live_set_from_records` from IR entities."""
    out: list[dict[str, Any]] = []
    for entity in entities:
        name = str(getattr(entity, "name", "") or "")
        kind = name.rsplit("-", 1)[0] if name else ""
        sources = getattr(entity, "sources", None) or []
        turn = sources[0].turn if sources else 0
        primary = _PRIMARY.get(kind, "")
        text = _efield(entity, primary) if primary else ""
        if not text:
            for field in getattr(entity, "fields", ()) or ():
                fkey = str(getattr(field, "key", "")).upper()
                if fkey in {"TURN", "SRC", "FACT-ID", "BASIS", "STATUS",
                            "EXTRACTOR", "SOURCE-ROLE", "SOURCE-ROLES"}:
                    continue
                text = str(getattr(field, "value", "") or "")
                if text:
                    break
        out.append({
            "fact_id": _efield(entity, "FACT-ID").lower(),
            "kind": kind,
            "text": text,
            "turn": turn,
            "session": session,
            "basis": _efield(entity, "BASIS"),
            "supersedes": _efield(entity, "SUPERSEDES-FACT-ID").lower(),
            "supersedes_reason": _efield(entity, "SUPERSEDES-REASON"),
            "retracts": _efield(entity, "RETRACTS-FACT-ID").lower(),
            "retract_reason": _efield(entity, "REASON") if kind == "RETRACT" else "",
            "ambiguous": _efield(entity, "ID-AMBIGUOUS"),
        })
    return out


def stakes_ids(live: LiveSet) -> frozenset[str]:
    return frozenset(fact.fact_id for fact in live.facts)


# Re-export for callers that already imported Conflict.
__all__ = [
    "AmbiguousRef",
    "Conflict",
    "FactView",
    "ForkView",
    "LiveSet",
    "Replacement",
    "choice_was",
    "is_milestone_stale",
    "iter_fact_ids",
    "live_set_from_records",
    "normalize_milestone",
    "records_from_entities",
    "render_live_preamble",
    "resolve_supersedes_target",
    "scope_ids",
    "select_live_set",
    "stakes_ids",
]
