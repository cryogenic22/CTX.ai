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
- literals  every verbatim identifier banked (bulk complement to why)
- resume    one call: gist + stakes trio + literals — the first read
            after a /clear or context loss

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
    ("LITERAL", "VALUE"),
    ("ERROR", "MESSAGE"),
    ("TASK", "TASK"),
    ("FILE", "PATH"),
)

_TURN_IN_SRC_RE = re.compile(r"#turn(\d+)\b")

# why() returns full field lists for provenance, but one oversized value
# (a pasted command, a pre-cap ledger row) must not dump kilobytes into
# the agent's context — observed in the field: a commit-sha lookup buried
# under a serialized TOOL-BASH COMMAND blob. Truncation is explicit,
# never silent.
_WHY_FIELD_VALUE_CAP = 400


def _scoped(value: str) -> str:
    if len(value) <= _WHY_FIELD_VALUE_CAP:
        return value
    return (value[:_WHY_FIELD_VALUE_CAP]
            + f" …[truncated {len(value) - _WHY_FIELD_VALUE_CAP} chars]")


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

    if not result.sections:
        # Spec v1.1 §7: a miss is an asserted absence, not an empty
        # string — auditable ("searched N as of turn T") so the agent
        # can say "not in memory" instead of guessing.
        return {
            "session": sid,
            "found": False,
            "sections_matched": 0,
            "sections_available": result.sections_available,
            "searched_entities": len(_sections(doc)),
            "as_of_turn": _max_turn(doc),
            "text": "",
            "note": ("No banked fact matches — asserted absence after "
                     "searching the full ledger, not an error. Answer "
                     "'not in memory' rather than inferring a value."),
        }
    prose: list[str] = []
    for s in result.sections:
        prose.extend(serialize_section(s, natural_language=True))
        prose.append("")
    return {
        "session": sid,
        "found": True,
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


def _max_turn(doc: CTXDocument) -> int:
    """Latest turn any section carries — the honest 'as of' for an
    absence assertion (facts after this turn are not yet packed)."""
    turns = [_turn_of(s) for s in _sections(doc)]
    return max((t for t in turns if isinstance(t, int)), default=0)


def load_supersession(ledger_dir: str):
    """(edges, graph) folded from the ledger's events.jsonl — the
    read-path twin of the checkpoint's fact_superseded emission. Missing
    or unreadable events → ([], empty graph), so callers stay boring on a
    ledger with no declared supersessions (the common case today)."""
    from ..core.supersession_dag import (
        build_graph,
        edges_from_events,
    )

    rows: list[dict[str, Any]] = []
    path = os.path.join(ledger_dir, "events.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except (ValueError, json.JSONDecodeError):
                    continue  # one bad row must not blind the read path
    except OSError:
        return [], build_graph([])
    edges = edges_from_events(rows)
    return edges, build_graph(edges)


def session_why(doc: CTXDocument, sid: str, key: str,
                ledger_dir: Optional[str] = None) -> dict[str, Any]:
    """Provenance for a key: which sections/fields carry it, set at which
    turn, and the supersession chain when the value was revised.

    Match order: exact section name → exact field key (including
    SUPERSEDED-<KEY> chains) → exact field VALUE (a LITERAL whose VALUE
    equals the needle beats every substring hit — the literals-ledger
    recovery path) → substring in values.

    ``ledger_dir`` (optional) folds the supersession DAG from
    events.jsonl and annotates any matched fact that participates in a
    supersession with its ``supersession`` view (current/superseded
    status, supersedes/superseded_by edges with provenance, and its
    unresolved fork if the fold found one). Facts in no edge are left
    untouched — a ledger with no declared supersessions reads exactly as
    before. Gist rendering and candidate emission are deliberately NOT
    done here (they wait for real ledgers to produce edges).
    """
    if not key or not key.strip():
        return {"session": sid, "key": key, "matches": [],
                "error": "key is required"}
    needle = key.strip().upper()
    needle_bare = needle[len("ENTITY-"):] if needle.startswith("ENTITY-") else needle
    needle_lower = key.strip().lower()
    matches: list[dict[str, Any]] = []

    def _fields_of(s: Section) -> list[dict[str, str]]:
        return [{"key": c.key, "value": _scoped(c.value)}
                for c in s.children if isinstance(c, KeyValue)]

    def _chains_of(s: Section) -> list[dict[str, str]]:
        return [{"key": c.key, "chain": _scoped(c.value)}
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
                    _hit(s, "field_key", {"key": c.key, "value": _scoped(c.value)})
                    break

    if not matches:
        for s in _sections(doc):
            for c in s.children:
                if (isinstance(c, KeyValue)
                        and c.value.strip().lower() == needle_lower):
                    _hit(s, "value_exact",
                         {"key": c.key, "value": _scoped(c.value)})
                    break

    if not matches:
        for s in _sections(doc):
            for c in s.children:
                if isinstance(c, KeyValue) and needle_lower in c.value.lower():
                    _hit(s, "value_substring",
                         {"key": c.key, "value": _scoped(c.value)})
                    break

    if not matches:
        # Spec v1.1 §7: asserted, auditable absence
        return {"session": sid, "key": key, "matches": [], "count": 0,
                "found": False,
                "searched_entities": len(_sections(doc)),
                "as_of_turn": _max_turn(doc),
                "note": ("No banked fact matches this key — asserted "
                         "absence after searching the full ledger, not "
                         "an error. Answer 'not in memory' rather than "
                         "inferring a value.")}
    note = ""
    if any(m["superseded_chains"] for m in matches):
        note = ("A SUPERSEDED-<KEY> chain reads oldest -> newest; the "
                "section's current field value is the latest and wins.")

    # Supersession DAG (fact-level, cross-session): annotate a matched
    # fact only when it actually participates in a supersession, so a
    # ledger with no declared overrides stays byte-for-byte as before.
    forked = False
    if ledger_dir is not None:
        from ..core.supersession_dag import fact_view

        edges, graph = load_supersession(ledger_dir)
        if edges:
            for m in matches:
                fid = next((f["value"] for f in m["fields"]
                            if f["key"].upper() == "FACT-ID"), "")
                view = fact_view(fid, edges, graph) if fid else None
                if view is not None:
                    m["supersession"] = view
                    if view["conflict"] is not None:
                        forked = True
    if forked and not note:
        note = ("An unresolved supersession fork touches this key — two "
                "or more current values compete. Surface both; do not "
                "silently pick one.")

    return {"session": sid, "key": key, "matches": matches, "found": True,
            "count": len(matches),
            **({"has_conflict": True} if forked else {}),
            **({"note": note} if note else {})}


def session_literals(doc: CTXDocument, sid: str) -> dict[str, Any]:
    """Every verbatim identifier banked in the ledger, turn-ordered.

    The bulk complement to per-id ``why``: on resume the natural question
    is "give me every exact id" (commit shas, PRs, versions, paths,
    domain ids) so the agent writes correct identifiers from the ledger
    instead of reconstructing them from a paraphrase.
    """
    rows = []
    for s in _sections(doc):
        if _kind_of(s) != "LITERAL":
            continue
        rows.append({
            "turn": _turn_of(s),
            "value": _kv(s, "VALUE"),
            "kind": _kv(s, "KIND"),
            "section": s.name,
        })
    rows.sort(key=lambda r: (r["turn"], r["section"]))
    return {"session": sid, "count": len(rows), "literals": rows}


def session_resume(ledger_dir: str = DEFAULT_LEDGER_DIR,
                   session: Optional[str] = None) -> dict[str, Any]:
    """One-call resume: gist + stakes trio + literals.

    The pull twin of the SessionStart injection — after a /clear where
    injection didn't land, or mid-session, this single read restores
    working state instead of chaining recall → decisions → why.
    Explicit ``session`` returns THAT session's gist; the default
    returns the startup context (project rollup + latest gist).
    """
    from .checkpoint import read_startup_context

    doc, sid = load_session(ledger_dir, session)
    if session:
        gist = ""
        try:
            with open(os.path.join(ledger_dir, f"session-{sid}-gist.md"),
                      encoding="utf-8") as f:
                gist = f.read()
        except OSError:
            pass
    else:
        gist = read_startup_context(ledger_dir)
    trio = session_decisions(doc, sid)
    lits = session_literals(doc, sid)
    return {
        "session": sid,
        "gist": gist.strip(),
        "decisions": trio["decisions"],
        "constraints": trio["constraints"],
        "failed_approaches": trio["failed_approaches"],
        "literals": lits["literals"],
        "counts": {**trio["counts"], "literals": lits["count"]},
    }


def session_stats(ledger_dir: str = DEFAULT_LEDGER_DIR) -> dict[str, Any]:
    """Aggregate the checkpoint journal into the benefits report.

    Checkpoints are full re-packs, so the LAST journal row per session
    supersedes earlier ones; totals sum those. The headline is
    raw_fallback_rate: transcript greps / all past-session reads — the
    read path earning its keep means this trends toward 0.
    """
    journal = os.path.join(ledger_dir, "checkpoints.jsonl")
    rows: list[dict] = []
    try:
        with open(journal, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        raise LedgerError(f"No checkpoint journal at {journal!r}")

    last_per_session: dict[str, dict] = {}
    for row in rows:
        last_per_session[str(row.get("session", ""))] = row

    totals: dict[str, Any] = {}
    for row in last_per_session.values():
        for key, value in (row.get("stats") or {}).items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
            elif isinstance(value, dict):
                # by-type counters (e.g. incident_types) merge key-wise
                bucket = totals.setdefault(key, {})
                for sub, count in value.items():
                    if isinstance(count, int):
                        bucket[sub] = bucket.get(sub, 0) + count

    ledger_reads = totals.get("ledger_reads", 0)
    greps = totals.get("transcript_greps", 0)
    fallback_rate = (round(greps / (ledger_reads + greps), 3)
                     if (ledger_reads + greps) else None)

    latencies = [row["latency_ms"] for row in rows
                 if isinstance(row.get("latency_ms"), (int, float))]
    gists = [row["gist_bpe"] for row in last_per_session.values()
             if isinstance(row.get("gist_bpe"), int)]

    return {
        "ledger_dir": ledger_dir,
        "sessions": len(last_per_session),
        "checkpoints": len(rows),
        "captured": {k: totals.get(k, 0) for k in (
            "decisions", "constraints", "failed_approaches", "errors",
            "files_changed", "tasks", "requests", "literals",
            "incidents")},
        "incident_types": totals.get("incident_types", {}),
        "read_path": {
            "ledger_reads": ledger_reads,
            "transcript_greps": greps,
            "raw_fallback_rate": fallback_rate,
        },
        "gist_bpe": {"latest_per_session": sorted(gists)} if gists else {},
        "checkpoint_latency_ms": {
            "max": max(latencies), "mean": round(
                sum(latencies) / len(latencies), 1),
        } if latencies else {},
        "turns_packed": sum(
            row.get("turns", 0) for row in last_per_session.values()),
    }
