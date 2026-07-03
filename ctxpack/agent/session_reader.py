"""Read path over the checkpoint ledger (.claude/ctx/).

The checkpoint engine (checkpoint.py) is the write path: transcript →
session-<sid>.ctx + gist. This module is the read path the agent uses
mid-session, exposed via MCP tools and ``ctxpack session``:

- recall    progressive hydration over a session pack: no args → section
            index (the L3 pattern: the LLM routes), section/query → prose
- timeline  every fact in turn order — the ordinal recall models pay
            attention-tax for, served as a lookup
- decisions the stakes trio (decisions / constraints / failed approaches)
            in one call, with turn provenance
- why       provenance for a key: where a value came from, and its
            supersession chain when the value was revised

Stdlib only, zero LLM, zero network — same ledger → same answers.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from ..core.hydrator import hydrate_by_name, hydrate_by_query, list_sections
from ..core.model import CTXDocument, KeyValue, Section
from ..core.parser import parse
from ..core.serializer import serialize_section

DEFAULT_LEDGER_DIR = ".claude/ctx"

# Section-name prefixes (post "ENTITY-") → the field that carries the fact.
# Longest-first so USER-REQUEST wins over a hypothetical USER.
_KIND_PRIMARY_KEY = (
    ("FAILED-APPROACH", "NOTE"),
    ("USER-REQUEST", "REQUEST"),
    ("CONSTRAINT", "RULE"),
    ("TOOL-BASH", "RAN"),
    ("DECISION", "DECISION"),
    ("ERROR", "MESSAGE"),
    ("TASK", "TASK"),
    ("FILE", "PATH"),
)

_TURN_IN_SRC_RE = re.compile(r"#turn(\d+)\b")


class LedgerError(Exception):
    """Raised when the ledger dir / requested session can't be resolved."""


# ── Session resolution ──


def _known_sessions(ledger_dir: str) -> list[str]:
    try:
        names = sorted(os.listdir(ledger_dir))
    except OSError:
        return []
    return [n[len("session-"):-len(".ctx")] for n in names
            if n.startswith("session-") and n.endswith(".ctx")]


def resolve_session(ledger_dir: str = DEFAULT_LEDGER_DIR,
                    session: Optional[str] = None) -> tuple[str, str]:
    """Return (sid, ctx_path) for the requested or most recent session.

    "Most recent" is the last entry of checkpoints.jsonl — the journal is
    the source of truth for checkpoint order (file mtimes are not
    deterministic across machines/clones).
    """
    if session:
        sid = session[:8]
    else:
        sid = ""
        journal = os.path.join(ledger_dir, "checkpoints.jsonl")
        try:
            with open(journal, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sid = str(json.loads(line).get("session", ""))[:8]
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        if not sid:
            known = _known_sessions(ledger_dir)
            if len(known) == 1:
                sid = known[0]
    ctx_path = os.path.join(ledger_dir, f"session-{sid}.ctx") if sid else ""
    if not sid or not os.path.isfile(ctx_path):
        raise LedgerError(
            f"No session ledger found in {ledger_dir!r} "
            f"(requested: {session or 'latest'}; "
            f"available: {_known_sessions(ledger_dir) or 'none'})"
        )
    return sid, ctx_path


def load_session(ledger_dir: str = DEFAULT_LEDGER_DIR,
                 session: Optional[str] = None) -> tuple[CTXDocument, str]:
    """Parse the requested (or latest) session ledger."""
    sid, ctx_path = resolve_session(ledger_dir, session)
    with open(ctx_path, encoding="utf-8") as f:
        return parse(f.read(), level=2), sid


# ── Section accessors ──


def _kind_of(section: Section) -> str:
    name = section.name.upper()
    if name.startswith("ENTITY-"):
        name = name[len("ENTITY-"):]
    for prefix, _ in _KIND_PRIMARY_KEY:
        if name.startswith(prefix):
            return prefix
    return name.split("-")[0] if "-" in name else name


def _kv(section: Section, key: str) -> str:
    for child in section.children:
        if isinstance(child, KeyValue) and child.key.upper() == key.upper():
            return child.value
    return ""


def _primary_value(section: Section) -> str:
    kind = _kind_of(section)
    for prefix, primary in _KIND_PRIMARY_KEY:
        if kind == prefix:
            value = _kv(section, primary)
            if value:
                return value
    for child in section.children:
        if isinstance(child, KeyValue) and child.key.upper() not in (
                "TURN", "SRC"):
            return child.value
    return ""


def _turn_of(section: Section) -> int:
    turn = _kv(section, "TURN")
    if turn:
        try:
            return int(turn)
        except ValueError:
            pass
    m = _TURN_IN_SRC_RE.search("\n".join(serialize_section(section)))
    return int(m.group(1)) if m else -1


def _sections(doc: CTXDocument) -> list[Section]:
    return [e for e in doc.body if isinstance(e, Section)]


# ── Tool implementations ──


def session_recall(
    doc: CTXDocument,
    sid: str,
    *,
    section: str = "",
    query: str = "",
    max_sections: int = 5,
    telemetry: Any = None,
) -> dict[str, Any]:
    """Progressive hydration over a session ledger.

    No section/query → the index (section names + kinds + turns): the LLM
    reads it and calls again with the names it wants — the L3 routing
    pattern applied to session memory.
    """
    if section:
        names = [n.strip() for n in section.split(",") if n.strip()]
        # Accept both DECISION-XXXX and ENTITY-DECISION-XXXX spellings
        expanded: list[str] = []
        for n in names:
            expanded.append(n)
            if not n.upper().startswith("ENTITY-"):
                expanded.append(f"ENTITY-{n}")
        result = hydrate_by_name(
            doc, expanded, include_header=False, telemetry=telemetry,
            question=query or section, session_id=sid,
        )
    elif query:
        result = hydrate_by_query(doc, query, max_sections=max_sections,
                                  include_header=False)
    else:
        rows = [{
            "name": s.name,
            "kind": _kind_of(s),
            "turn": _turn_of(s),
            "tokens": entry["tokens"],
        } for s, entry in zip(_sections(doc), list_sections(doc))]
        return {
            "session": sid,
            "sections_available": len(rows),
            "index": rows,
            "hint": ("Call again with section=<name>[,<name>] to hydrate; "
                     "kinds: " + ", ".join(sorted({r['kind'] for r in rows}))),
        }

    prose: list[str] = []
    for s in result.sections:
        prose.extend(serialize_section(s, natural_language=True))
        prose.append("")
    return {
        "session": sid,
        "sections_matched": len(result.sections),
        "sections_available": result.sections_available,
        "tokens_injected": result.tokens_injected,
        "text": "\n".join(prose).strip(),
    }


def session_timeline(
    doc: CTXDocument,
    sid: str,
    *,
    kinds: Optional[list[str]] = None,
    limit: int = 0,
) -> dict[str, Any]:
    """Turn-ordered ledger rows — ordinal recall as a lookup, not an
    attention problem."""
    wanted = {k.upper() for k in kinds} if kinds else None
    rows = []
    for s in _sections(doc):
        kind = _kind_of(s)
        if wanted is not None and kind not in wanted:
            continue
        rows.append({"turn": _turn_of(s), "kind": kind,
                     "entry": _primary_value(s), "section": s.name})
    rows.sort(key=lambda r: (r["turn"], r["section"]))
    total = len(rows)
    if limit and limit > 0:
        rows = rows[-limit:]  # the most recent events are the useful tail
    return {"session": sid, "events": total, "timeline": rows}


def session_decisions(doc: CTXDocument, sid: str) -> dict[str, Any]:
    """The stakes trio in one call: decisions, constraints, failed
    approaches — each with turn provenance."""
    out: dict[str, list[dict[str, Any]]] = {
        "decisions": [], "constraints": [], "failed_approaches": [],
    }
    kind_to_bucket = {"DECISION": "decisions", "CONSTRAINT": "constraints",
                      "FAILED-APPROACH": "failed_approaches"}
    for s in _sections(doc):
        bucket = kind_to_bucket.get(_kind_of(s))
        if bucket is None:
            continue
        out[bucket].append({
            "turn": _turn_of(s),
            "text": _primary_value(s),
            "section": s.name,
        })
    for bucket in out.values():
        bucket.sort(key=lambda r: r["turn"])
    return {"session": sid, **out,
            "counts": {k: len(v) for k, v in out.items()}}


def session_why(doc: CTXDocument, sid: str, key: str) -> dict[str, Any]:
    """Provenance for a key: which sections/fields carry it, set at which
    turn, and the supersession chain when the value was revised.

    Match order: exact section name → exact field key (including
    SUPERSEDED-<KEY> chains) → substring in values.
    """
    if not key or not key.strip():
        return {"session": sid, "key": key, "matches": [],
                "error": "key is required"}
    needle = key.strip().upper()
    needle_bare = needle[len("ENTITY-"):] if needle.startswith("ENTITY-") else needle
    matches: list[dict[str, Any]] = []

    def _fields_of(s: Section) -> list[dict[str, str]]:
        return [{"key": c.key, "value": c.value}
                for c in s.children if isinstance(c, KeyValue)]

    def _chains_of(s: Section) -> list[dict[str, str]]:
        return [{"key": c.key, "chain": c.value}
                for c in s.children
                if isinstance(c, KeyValue)
                and c.key.upper().startswith("SUPERSEDED-")]

    def _hit(s: Section, matched_on: str, field: Optional[dict] = None) -> None:
        matches.append({
            "section": s.name,
            "kind": _kind_of(s),
            "turn": _turn_of(s),
            "matched_on": matched_on,
            "field": field,
            "fields": _fields_of(s),
            "superseded_chains": _chains_of(s),
        })

    for s in _sections(doc):
        s_name = s.name.upper()
        s_bare = s_name[len("ENTITY-"):] if s_name.startswith("ENTITY-") else s_name
        if s_bare == needle_bare or s_name == needle:
            _hit(s, "section_name")

    if not matches:
        for s in _sections(doc):
            for c in s.children:
                if not isinstance(c, KeyValue):
                    continue
                c_key = c.key.upper()
                if c_key == needle or c_key == f"SUPERSEDED-{needle}":
                    _hit(s, "field_key", {"key": c.key, "value": c.value})
                    break

    if not matches:
        needle_lower = key.strip().lower()
        for s in _sections(doc):
            for c in s.children:
                if isinstance(c, KeyValue) and needle_lower in c.value.lower():
                    _hit(s, "value_substring", {"key": c.key, "value": c.value})
                    break

    note = ""
    if any(m["superseded_chains"] for m in matches):
        note = ("A SUPERSEDED-<KEY> chain reads oldest -> newest; the "
                "section's current field value is the latest and wins.")
    return {"session": sid, "key": key, "matches": matches,
            "count": len(matches), **({"note": note} if note else {})}
