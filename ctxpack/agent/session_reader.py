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

from ..core.errors import ParseError
from ..core.hydrator import hydrate_by_name, hydrate_by_query, list_sections
from ..core.model import CTXDocument, KeyValue, Section
from ..core.parser import parse
from ..core.serializer import serialize_section
from ..core.tokens import estimate_tokens, estimator_label

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
        # Last LIVE journal row wins; backfilled (archive) rows land at
        # the tail out of chronological order and must never hijack the
        # default session. All-archive journals fall back to the tail.
        sid = ""
        sid_any = ""
        journal = os.path.join(ledger_dir, "checkpoints.jsonl")
        try:
            with open(journal, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sid_any = str(row.get("session", ""))[:8]
                    if not row.get("archive"):
                        sid = sid_any
        except OSError:
            pass
        sid = sid or sid_any
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
    text = "\n".join(prose).strip()
    # Q2-1: the estimate must describe the text actually RETURNED (the
    # prose render), not the raw .ctx the hydrator counted internally
    return {
        "session": sid,
        "found": True,
        "sections_matched": len(result.sections),
        "sections_available": result.sections_available,
        "tokens_injected": estimate_tokens(text, kind="prose"),
        "token_estimator": estimator_label("prose"),
        "text": text,
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


_MATCH_TIER = {"section_name": 0, "field_key": 1,
               "value_exact": 2, "value_substring": 3}
_WHY_MAX_MATCHES = 25

_CHAIN_NOTE = ("A SUPERSEDED-<KEY> chain reads oldest -> newest; the "
               "section's current field value is the latest and wins.")
_FORK_NOTE = ("An unresolved supersession fork touches this key — two or "
              "more current values compete. Surface both; do not silently "
              "pick one.")


def _why_matches(doc: CTXDocument,
                 key: str) -> "tuple[list[dict[str, Any]], int, int]":
    """The single-doc match cascade behind ``why``: exact section name →
    field key (incl. SUPERSEDED-<KEY>) → exact field value → substring.
    Returns (matches, entities_searched, max_turn). No DAG annotation and
    no absence shaping — the callers add those, so single- and
    cross-session ``why`` share one match semantics."""
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

    return matches, len(_sections(doc)), _max_turn(doc)


def _annotate_supersession(matches: "list[dict[str, Any]]",
                           ledger_dir: Optional[str]) -> bool:
    """Attach a ``supersession`` view to each matched fact that
    participates in a supersession edge; return True if any match sits in
    an unresolved fork. ``ledger_dir`` None, or a zero-edge ledger, leaves
    every match untouched — the read path stays boring."""
    if ledger_dir is None:
        return False
    from ..core.supersession_dag import fact_view

    edges, graph = load_supersession(ledger_dir)
    if not edges:
        return False
    forked = False
    for m in matches:
        fid = next((f["value"] for f in m["fields"]
                    if f["key"].upper() == "FACT-ID"), "")
        view = fact_view(fid, edges, graph) if fid else None
        if view is not None:
            m["supersession"] = view
            if view["conflict"] is not None:
                forked = True
    return forked


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
    done here (they wait for real ledgers to produce edges). This searches
    ONE session's doc; ``session_why_across`` searches the whole ledger.
    """
    if not key or not key.strip():
        return {"session": sid, "key": key, "matches": [],
                "error": "key is required"}
    matches, searched, max_turn = _why_matches(doc, key)
    if not matches:
        # Spec v1.1 §7: asserted, auditable absence
        return {"session": sid, "key": key, "matches": [], "count": 0,
                "found": False, "searched_entities": searched,
                "as_of_turn": max_turn,
                "note": ("No banked fact matches this key — asserted "
                         "absence after searching the full ledger, not "
                         "an error. Answer 'not in memory' rather than "
                         "inferring a value.")}
    note = _CHAIN_NOTE if any(m["superseded_chains"] for m in matches) else ""
    forked = _annotate_supersession(matches, ledger_dir)
    if forked and not note:
        note = _FORK_NOTE
    return {"session": sid, "key": key, "matches": matches, "found": True,
            "count": len(matches),
            **({"has_conflict": True} if forked else {}),
            **({"note": note} if note else {})}


def session_why_across(ledger_dir: str = DEFAULT_LEDGER_DIR, key: str = "",
                       session: Optional[str] = None,
                       max_matches: int = _WHY_MAX_MATCHES) -> dict[str, Any]:
    """Cross-session ``why``: search every banked session (journal order),
    so a value banked in an earlier session is recoverable while resuming
    on a later one — the single-session ``session_why`` only sees the doc
    it is handed (memory feedback #6). Each match carries its source
    ``session``; the supersession DAG is folded once across all events, so
    a fork spanning sessions surfaces here too. ``session`` scopes back to
    one session (prefix match). Matches rank by tier (exact > substring)
    then most-recent session, capped at ``max_matches``.

    Stdlib only, deterministic: same ledger → same answer."""
    if not key or not key.strip():
        return {"key": key, "matches": [], "error": "key is required"}
    from .checkpoint import _journal_session_order

    order = _journal_session_order(ledger_dir)
    if session:
        s8 = session.strip()[:8]
        order = [s for s in order if s.startswith(s8) or s8.startswith(s)]

    # No sessions at all is a ledger/config problem, NOT asserted absence:
    # reporting "not in memory" for a wrong --ledger would hide the mistake.
    if not order:
        raise LedgerError(
            f"no checkpointed sessions in {ledger_dir}"
            + (f" matching session {session!r}" if session else ""))

    collected: list[dict[str, Any]] = []
    searched = 0
    max_turn = 0
    for idx, sid in enumerate(order):
        try:
            doc, rsid = load_session(ledger_dir, sid)
        except (LedgerError, ParseError, UnicodeDecodeError, OSError):
            # one unreadable/malformed session must not blind the search:
            # missing (LedgerError/OSError), bad bytes (UnicodeDecodeError),
            # or structurally invalid (ParseError)
            continue
        found, n, mt = _why_matches(doc, key)
        for m in found:
            m["session"] = rsid
            m["_recency"] = idx
            collected.append(m)
        searched += n
        max_turn = max(max_turn, mt)

    if not collected:
        return {"key": key, "matches": [], "count": 0, "found": False,
                "sessions_searched": len(order),
                "searched_entities": searched, "as_of_turn": max_turn,
                "note": ("No banked fact matches this key in ANY session — "
                         "asserted absence after searching the whole "
                         "ledger, not an error. Answer 'not in memory'.")}

    collected.sort(key=lambda m: (_MATCH_TIER.get(m["matched_on"], 9),
                                  -m["_recency"], m.get("turn", 0)))
    truncated = len(collected) > max_matches
    matches = collected[:max_matches]
    for m in matches:
        m.pop("_recency", None)

    note = _CHAIN_NOTE if any(m["superseded_chains"] for m in matches) else ""
    forked = _annotate_supersession(matches, ledger_dir)
    if forked and not note:
        note = _FORK_NOTE
    _annotate_authority(matches, ledger_dir)
    return {"key": key, "matches": matches, "found": True,
            "count": len(matches), "sessions_searched": len(order),
            **({"truncated": True, "total_matches": len(collected)}
               if truncated else {}),
            **({"has_conflict": True} if forked else {}),
            **({"note": note} if note else {})}


def _annotate_authority(matches: "list[dict[str, Any]]",
                        ledger_dir: str) -> None:
    """Stamp each match with its derived authority.

    Extraction basis is not authority (an assistant emits ``Decision:``
    markers routinely): authority derives from the SOURCE-ROLE the
    parser stamped plus explicit ratification events only. Facts
    predating tp/1.2 carry no role and honestly report
    ``legacy_unknown`` — they are candidates, never owner-approved by
    age. A last-event rejection is surfaced as ``ratification:
    rejected`` so eligibility policy can exclude it downstream.
    """
    from ..core.factid import derive_authority
    from .ratification import RATIFY, ratification_state

    state = ratification_state(ledger_dir)
    for m in matches:
        fields = {str(f.get("key", "")).upper(): str(f.get("value", ""))
                  for f in m.get("fields") or []}
        fid = fields.get("FACT-ID", "").lower()
        role = fields.get("SOURCE-ROLE", "")
        action = state.get(fid) if fid else None
        m["authority"] = derive_authority(
            role, ratified=(action == RATIFY)).value
        if action and action != RATIFY:
            m["ratification"] = "rejected"


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


def classify_read_path(rows, emission=None) -> dict[str, Any]:
    """Session-level read-path adoption from checkpoint journal rows.

    The event counters alone cannot answer the question two field
    reports raised — "did the agent ever query the ledger?" A session
    that never queried and a session packed before this telemetry
    existed BOTH produce ``raw_fallback_rate = None``, so "the read path
    is dead" is precisely the claim the rate hides.

    ``explicit_recall`` means a deliberate query (an MCP ``ctx/session_*``
    call or a ``ctxpack session`` command). SessionStart injection is
    the PUSH path and is deliberately not counted here: conflating the
    two would make the pull path look adopted in every session that
    merely started.

    ``emission`` — the per-session receipt fold from
    ``injection_log.fold_emission_receipts``. It splits the zero-recall
    bucket, which is otherwise very different sessions wearing one
    label. The split reports what the receipts PROVE, and only that:

    - ``with_emission`` — a receipt says a non-empty gist reached the
      hook's stdout.
    - ``emission_empty`` — a receipt says the hook ran and emitted
      nothing. This is the ONLY evidence of "no gist": it is proven by
      a receipt, never inferred.
    - ``emission_failed`` — a receipt says the emission attempt broke.
    - ``emission_unmeasured`` — no receipt exists (the fold is ``None``
      because the log is absent, or the session has no row — it may
      simply predate the log). Absence of a receipt never proves "no
      emission", and no timestamp is consulted: checkpoint timestamps
      can be backfilled and prove nothing about session start. There is
      deliberately no "no_emission" bucket.

    Emission is not use. A session in ``with_emission`` was handed
    bytes; nothing here shows the model read or benefited from them
    (see ``ctxpack.core.states.Delivery``).

    The first three buckets partition the sessions; transcript_fallback
    overlaps them (a session may query the ledger AND still grep raw).
    """
    explicit = zero = untracked = fallback = 0
    with_emission = emission_empty = emission_failed = unmeasured = 0
    folded = emission.get("sessions", {}) if emission is not None else None
    for row in rows:
        stats = row.get("stats") or {}
        if "ledger_reads" not in stats:
            untracked += 1          # packed before this counter existed
            continue
        if int(stats.get("ledger_reads") or 0) > 0:
            explicit += 1
        else:
            zero += 1
            outcome = (folded.get(str(row.get("session", ""))[:8])
                       if folded is not None else None)
            if outcome == "injected":
                with_emission += 1
            elif outcome == "failed":
                emission_failed += 1
            elif outcome == "empty":
                emission_empty += 1
            else:
                unmeasured += 1     # no receipt is not "no emission"
        if int(stats.get("transcript_greps") or 0) > 0:
            fallback += 1
    measured = explicit + zero
    return {
        "sessions_explicit_recall": explicit,
        "sessions_zero_recall": zero,
        "sessions_no_telemetry": untracked,
        "sessions_transcript_fallback": fallback,
        "sessions_zero_recall_with_emission": with_emission,
        "sessions_zero_recall_emission_empty": emission_empty,
        "sessions_zero_recall_emission_failed": emission_failed,
        "sessions_zero_recall_emission_unmeasured": unmeasured,
        "explicit_recall_rate": (round(explicit / measured, 3)
                                 if measured else None),
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
    # Push-path emission record — {} means "not measured" (ledger predates
    # the injection log), never "never injected". The per-session receipt
    # fold joins zero-recall sessions to what their receipts prove
    # (injected / empty / failed); a session without a receipt stays
    # unmeasured — never "never given anything".
    from .injection_log import fold_emission_receipts, injection_stats
    startup_injection = injection_stats(ledger_dir)
    sessions_read_path = classify_read_path(
        last_per_session.values(), fold_emission_receipts(ledger_dir))

    latencies = [row["latency_ms"] for row in rows
                 if isinstance(row.get("latency_ms"), (int, float))]
    gists = [row["gist_bpe"] for row in last_per_session.values()
             if isinstance(row.get("gist_bpe"), int)]
    # identifier fidelity across the fold (feedback #7) — complements
    # raw_fallback_rate: recall says the id was found, fidelity says it was
    # found VERBATIM. `min` is the honest headline (the worst any checkpoint
    # ever did); rows before this feature carry no value and are skipped.
    fidelities = [row["literal_fidelity"] for row in rows
                  if isinstance(row.get("literal_fidelity"), (int, float))]

    return {
        "ledger_dir": ledger_dir,
        "sessions": len(last_per_session),
        "checkpoints": len(rows),
        "captured": {k: totals.get(k, 0) for k in (
            "decisions", "findings", "constraints", "failed_approaches",
            "errors", "files_changed", "tasks", "requests", "literals",
            "incidents")},
        "incident_types": totals.get("incident_types", {}),
        "read_path": {
            "ledger_reads": ledger_reads,
            "transcript_greps": greps,
            "raw_fallback_rate": fallback_rate,
            **sessions_read_path,
        },
        "startup_injection": startup_injection,
        "gist_bpe": {"latest_per_session": sorted(gists)} if gists else {},
        "identifier_fidelity": {
            "min": min(fidelities),
            "latest": fidelities[-1],
            "checkpoints_measured": len(fidelities),
        } if fidelities else {},
        "checkpoint_latency_ms": {
            "max": max(latencies), "mean": round(
                sum(latencies) / len(latencies), 1),
        } if latencies else {},
        "turns_packed": sum(
            row.get("turns", 0) for row in last_per_session.values()),
    }
