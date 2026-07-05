"""Pack-on-compact checkpoint engine.

"Compaction is a commit, not a loss event": before Claude Code's summarizer
discards history, deterministically pack the session transcript into a
.ctx ledger plus a small prose gist that gets re-injected after compaction
(SessionStart) — Constraint Pinning, done without an LLM.

Artifacts written to <out_dir> (default .claude/ctx/):

- session-<sid>.ctx        the packed session ledger (L2)
- session-<sid>-gist.md    ≤GIST_BPE_BUDGET prose gist (in-distribution:
                           plain markdown the model reads natively)
- latest-gist.md           copy of the most recent gist (SessionStart
                           fires for a NEW session id; what it needs is
                           the last session's memory)
- checkpoints.jsonl        append-only checkpoint journal (ts, session,
                           turns, entities, sha256 of the ledger)

Zero LLM calls, zero network. Same transcript → byte-identical ledger
(pass as_of / set CTXPACK_AS_OF to pin the header date).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from ..core import factid, rank
from ..core.packer.compressor import compress
from ..core.packer.conflict import detect_conflicts
from ..core.packer.entity_resolver import resolve_entities
from ..core.serializer import serialize
from .transcript_parser import ParsedTranscript, decision_marker, parse_transcript

GIST_BPE_BUDGET = 2000

# Gist section order: highest-stakes first, so budget trimming (which cuts
# from the end) drops tool runs before it ever touches constraints.
_GIST_KINDS = (
    ("CONSTRAINT", "Constraints (verbatim — do not violate)", "RULE"),
    ("DECISION", "Decisions", "DECISION"),
    ("LITERAL", "Exact identifiers (verbatim)", "VALUE"),
    ("FAILED-APPROACH", "Failed approaches (do not retry)", "NOTE"),
    # RAW = the verbatim ctx-incident line — auditable as stated; stale/
    # wrong incidents double as a warning to the next session
    ("INCIDENT", "Memory incidents (ctx telemetry)", "RAW"),
    ("USER-REQUEST", "What was asked", "REQUEST"),
    ("TASK", "Tasks", "TASK"),
    ("ERROR", "Errors seen", "MESSAGE"),
    ("FILE", "Files changed", "PATH"),
)

# Cap the gist's literal list so a session that names hundreds of ids can't
# crowd out the prose sections; the full set stays in the ledger (ctx/recall).
_GIST_LITERAL_CAP = 40


@dataclass
class CheckpointResult:
    session_id: str = ""
    ctx_path: str = ""
    gist_path: str = ""
    turns: int = 0
    entities: int = 0
    conflicts: int = 0
    ledger_sha256: str = ""
    gist_bpe: int = 0


def _count_bpe(text: str) -> int:
    try:
        from ..benchmarks.metrics.cost import count_bpe_tokens
        return count_bpe_tokens(text, model="claude")
    except Exception:
        return max(1, len(text) // 4)


def _entity_line(prefix: str, e, primary_key: str) -> str:
    value = next((f.value for f in e.fields if f.key == primary_key),
                 e.fields[0].value if e.fields else "")
    turn = e.sources[0].turn if e.sources else "?"
    extra = ""
    if prefix == "FILE":
        edits = next((f.value for f in e.fields if f.key == "EDITS"), "")
        extra = f" ({edits} edits)" if edits else ""
    elif prefix == "TASK":
        status = next((f.value for f in e.fields if f.key == "STATUS"), "")
        extra = f" [{status}]" if status else ""
    elif prefix == "LITERAL":
        kind = next((f.value for f in e.fields if f.key == "KIND"), "")
        extra = f" [{kind}]" if kind else ""
    return f"- {value}{extra} (turn {turn})"


def _entity_rank(e, ranks: "dict[str, float]") -> float:
    fid = next((f.value for f in e.fields if f.key == "FACT-ID"), "")
    if fid in ranks:
        return ranks[fid]
    return rank.prior_for(e.name.rsplit("-", 1)[0])


def build_gist(parsed: ParsedTranscript,
               ranks: "Optional[dict[str, float]]" = None) -> str:
    """Render the session ledger as a compact markdown gist.

    Prose-first on purpose: models read markdown natively (.ctx notation is
    the storage format, not the injection format).

    Without ``ranks`` (rank/v0-static-priors) this is the legacy render:
    chronological sections, literals capped most-recent, budget trimming
    that drops lines from the lowest-stakes section up. With ``ranks``
    (the rank/v1 event fold) selection and trimming are salience-aware —
    the literal cap keeps the highest-rank identifiers and budget
    pressure evicts the GLOBALLY lowest-rank fact across all sections
    (kind priors and the constraint floor encode the stakes order) —
    while the render order inside a section stays chronological
    (facts still read in the order they happened).
    """
    ents = parsed.corpus.entities
    header: list[str] = [
        f"# Session memory (session {parsed.session_id[:8]}, "
        f"{parsed.last_turn} turns)",
        "",
        "Deterministic ledger recovered from the session transcript. "
        "Full detail: `ctxpack hydrate` on the session .ctx, or grep the "
        "raw transcript.",
    ]

    if not ranks:
        lines = list(header)
        for prefix, title, primary_key in _GIST_KINDS:
            matched = [e for e in ents if e.name.startswith(prefix)]
            if not matched:
                continue
            # Chronological: facts read in the order they happened
            matched.sort(key=lambda e: e.sources[0].turn if e.sources else 0)
            capped_note = ""
            if prefix == "LITERAL" and len(matched) > _GIST_LITERAL_CAP:
                # Signal the bound, never truncate silently: the full set
                # stays in the ledger (ctx/recall).
                capped_note = (f" (showing {_GIST_LITERAL_CAP} most-recent of "
                               f"{len(matched)} — full set in the ledger)")
                matched = matched[-_GIST_LITERAL_CAP:]
            lines.append("")
            lines.append(f"## {title}{capped_note}")
            for e in matched:
                lines.append(_entity_line(prefix, e, primary_key))
        text = "\n".join(lines)
        # Trim from the end until within budget — the section order
        # guarantees constraints/decisions are the last to go.
        while _count_bpe(text) > GIST_BPE_BUDGET and len(lines) > 4:
            lines.pop()
            text = "\n".join(lines)
        return text

    # rank/v1 path — sections carry their entities so trimming can evict
    # by salience instead of by file position
    sections: list = []  # (prefix, title, primary_key, entities, total)
    for prefix, title, primary_key in _GIST_KINDS:
        matched = [e for e in ents if e.name.startswith(prefix)]
        if not matched:
            continue
        matched.sort(key=lambda e: e.sources[0].turn if e.sources else 0)
        total = len(matched)
        if prefix == "LITERAL" and total > _GIST_LITERAL_CAP:
            keep = sorted(
                matched,
                key=lambda e: (-_entity_rank(e, ranks),
                               -(e.sources[0].turn if e.sources else 0),
                               e.name))[:_GIST_LITERAL_CAP]
            keep_ids = {id(e) for e in keep}
            matched = [e for e in matched if id(e) in keep_ids]
        sections.append((prefix, title, primary_key, matched, total))

    def _render() -> "tuple[str, list[str]]":
        lines = list(header)
        for prefix, title, primary_key, matched, total in sections:
            if not matched:
                continue
            note = ""
            if prefix == "LITERAL" and len(matched) < total:
                note = (f" (showing {len(matched)} highest-rank of {total} "
                        f"— full set in the ledger)")
            lines.append("")
            lines.append(f"## {title}{note}")
            for e in matched:
                lines.append(_entity_line(prefix, e, primary_key))
        return "\n".join(lines), lines

    # Global lowest-rank eviction (not section-ordered): kind priors and
    # the constraint floor already encode the stakes order, and the fold
    # ranks a junk inferred decision BELOW a git_sha — dogfood evidence
    # (KP_SDLC ca35891c) showed section-ordered trimming evicting 23 real
    # identifiers while keeping six junk decision lines.
    text, lines = _render()
    while _count_bpe(text) > GIST_BPE_BUDGET and len(lines) > 4:
        candidates = [(e, matched) for _, _, _, matched, _ in sections
                      for e in matched]
        if not candidates:
            break
        # Evict lowest rank; ties evict the oldest fact first
        victim, owner = min(
            candidates,
            key=lambda pair: (_entity_rank(pair[0], ranks),
                              pair[0].sources[0].turn
                              if pair[0].sources else 0,
                              pair[0].name))
        owner.remove(victim)
        text, lines = _render()
    return text


def _emit_events(out_dir: str, parsed: ParsedTranscript, corpus,
                 sha: str) -> int:
    """Materialize this session's event rows in events.jsonl.

    Spec v1.1 §5: the transcript is the single event source and
    events.jsonl is a materialized view of it — so the session's block
    is REGENERATED from the current parse and replaces its previous
    block in place (a session's first checkpoint appends its block at
    the end). The final file is cadence-independent: ten debounced
    stop-hook checkpoints and one single-shot checkpoint materialize
    byte-identical views, and deleting the file and re-running one
    checkpoint per transcript (journal order) reproduces it exactly.
    Rows carry the checkpoint sha they were last materialized at —
    turn provenance, not the checkpoint field, is the stable anchor.
    """
    events_path = os.path.join(out_dir, "events.jsonl")
    sid = parsed.session_id

    # Split the existing file around this session's previous block so the
    # regenerated block lands in the same position (other sessions' rows
    # are preserved byte-for-byte, order untouched).
    before: list = []
    after: list = []
    target = before
    if os.path.exists(events_path):
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                raw = line.rstrip("\n")
                if not raw.strip():
                    continue
                try:
                    row_sid = json.loads(raw).get("session")
                except json.JSONDecodeError:
                    target.append(raw)  # unparseable line: keep in place
                    continue
                if row_sid == sid:
                    target = after  # drop old block; regenerating below
                    continue
                target.append(raw)

    def _field(entity, key: str) -> str:
        return next((f.value for f in entity.fields if f.key == key), "")

    rows: list = []
    # cwd is transcript-derived (never env), so rank folds can exclude
    # eval-harness workspaces while events.jsonl stays rebuildable.
    cwd = parsed.stats.cwd

    def ev(event: str, fact_id=None, turn=None, **detail) -> None:
        rows.append({"schema": factid.EVENTS_SCHEMA, "session": sid,
                     "checkpoint": sha[:12], "cwd": cwd, "event": event,
                     "fact_id": fact_id, "turn": turn, "detail": detail})

    seen: set = set()  # one fact_asserted per fact_id within the block
    for entity in corpus.entities:
        fid = _field(entity, "FACT-ID")
        if not fid:
            continue
        turn = entity.sources[0].turn if entity.sources else None
        if entity.name.startswith("INCIDENT-"):
            linked = _field(entity, "LINKED-FACT-ID") or None
            ev("incident", fact_id=linked, turn=turn,
               incident_id=fid, type=_field(entity, "TYPE"),
               parse_ok=_field(entity, "PARSE-OK"))
            continue
        if fid in seen:
            continue
        seen.add(fid)
        # rsplit: keep the full kind ("FAILED-APPROACH", "USER-REQUEST") —
        # rows from before 2026-07-05 carry the first-segment truncation,
        # which rank folds normalize on read
        kind = entity.name.rsplit("-", 1)[0]
        detail = {"kind": kind, "basis": _field(entity, "BASIS")}
        if kind == "DECISION":
            # which marker word fired — the canonical "Decision:" is a
            # stronger commitment than verdict/conclusion/confirmed, and
            # rank folds weigh them differently (ctxpack.core.rank)
            marker = decision_marker(_field(entity, "DECISION"))
            if marker:
                detail["marker"] = marker
        elif kind == "LITERAL":
            literal_kind = _field(entity, "KIND")
            if literal_kind:
                detail["literal_kind"] = literal_kind
        ev("fact_asserted", fact_id=fid, turn=turn, **detail)
        for f in entity.fields:
            if f.key.startswith("SUPERSEDED-"):
                ev("supersession", fact_id=fid, turn=turn,
                   key=f.key[len("SUPERSEDED-"):], chain=str(f.value)[:300])

    ev("retrieval", ledger_reads=parsed.stats.ledger_reads,
       transcript_greps=parsed.stats.transcript_greps)

    with open(events_path, "w", encoding="utf-8", newline="\n") as f:
        for raw in before:
            f.write(raw + "\n")
        for row in rows:
            f.write(json.dumps(row) + "\n")
        for raw in after:
            f.write(raw + "\n")
    return len(rows)


def run_checkpoint(
    transcript_path: str,
    out_dir: str = ".claude/ctx",
    *,
    as_of: Optional[str] = None,
) -> CheckpointResult:
    """Pack a session transcript into the ledger + gist artifacts.

    Idempotent: re-parses the full transcript every time (the transcript is
    L0 and never deleted; a full deterministic re-pack is cheaper than
    incremental-merge correctness risk at session scale).
    """
    import time
    t0 = time.perf_counter()

    parsed = parse_transcript(transcript_path)
    corpus = parsed.corpus

    resolve_entities(corpus, supersede_by_recency=True)
    conflicts = detect_conflicts(corpus)
    corpus.warnings.extend(conflicts)
    doc = compress(corpus, as_of=as_of)
    ledger_text = serialize(doc)

    sid = parsed.session_id[:8] if parsed.session_id else "unknown"
    os.makedirs(out_dir, exist_ok=True)

    ctx_path = os.path.join(out_dir, f"session-{sid}.ctx")
    with open(ctx_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(ledger_text)

    sha = hashlib.sha256(ledger_text.encode("utf-8")).hexdigest()
    _emit_events(out_dir, parsed, corpus, sha)

    # rank = fold(events, policy), spec v1.1 §6 — folded AFTER this
    # checkpoint's events land so the gist sees its own session's facts.
    # project_root is the transcript's cwd (never env): rows from other
    # workspaces (benchmark harnesses) are excluded from the fold.
    policy = rank.resolve_policy()
    ranks = rank.fold_events(
        rank.load_events(os.path.join(out_dir, "events.jsonl")),
        policy=policy,
        project_root=parsed.stats.cwd or "")

    gist_text = build_gist(parsed, ranks=ranks)
    gist_path = os.path.join(out_dir, f"session-{sid}-gist.md")
    with open(gist_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(gist_text)
    with open(os.path.join(out_dir, "latest-gist.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(gist_text)

    gist_bpe = _count_bpe(gist_text)
    import datetime
    journal_entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session": parsed.session_id,
        "turns": parsed.last_turn,
        "entities": len(corpus.entities),
        "conflicts": len(conflicts),
        "sha256": sha,
        "gist_bpe": gist_bpe,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        # the policy actually used, so folds stay A/B-testable offline
        # against the same event log (spec v1.1 §6)
        "rank_policy": policy,
        "stats": parsed.stats.to_dict(),
    }
    with open(os.path.join(out_dir, "checkpoints.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps(journal_entry) + "\n")

    # Regenerate the cross-session rollup (excludes this session — its own
    # gist is latest-gist.md, injected alongside)
    project_text = build_project_gist(out_dir, exclude_session=sid,
                                      ranks=ranks)
    project_path = os.path.join(out_dir, "project-gist.md")
    if project_text:
        with open(project_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(project_text)
    elif os.path.exists(project_path):
        os.remove(project_path)  # stale rollup is worse than none

    return CheckpointResult(
        session_id=parsed.session_id,
        ctx_path=ctx_path,
        gist_path=gist_path,
        turns=parsed.last_turn,
        entities=len(corpus.entities),
        conflicts=len(conflicts),
        ledger_sha256=sha,
        gist_bpe=gist_bpe,
    )


# ── Live-transcript resolution ──
#
# Hooks receive transcript_path on stdin, but an agent checkpointing
# mid-session (MCP ctx/checkpoint, or bare `ctxpack checkpoint`) has to
# find it. Claude Code writes transcripts to
# ~/.claude/projects/<munged-project-path>/<session-uuid>.jsonl, munging
# every non-alphanumeric path char to '-'. Picking the newest-mtime file
# selects the INPUT only — the pack of that transcript stays
# byte-deterministic; the determinism ground rule governs pack output,
# not which live session is being packed.


def _claude_project_dir_name(project_dir: str) -> str:
    """Munge an absolute path the way Claude Code names per-project
    transcript directories (every non-alphanumeric char → '-')."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project_dir))


def find_live_transcript(project_dir: str = ".",
                         session: Optional[str] = None,
                         claude_home: Optional[str] = None) -> str:
    """Path of the project's live (most recently written) transcript.

    ``session`` narrows to files whose name starts with that id prefix.
    Raises FileNotFoundError with guidance when nothing matches — the
    caller should then ask for an explicit --transcript path.
    """
    home = (claude_home
            or os.environ.get("CLAUDE_CONFIG_DIR")
            or os.path.join(os.path.expanduser("~"), ".claude"))
    tdir = os.path.join(home, "projects",
                        _claude_project_dir_name(project_dir))
    try:
        names = [n for n in os.listdir(tdir) if n.endswith(".jsonl")]
    except OSError:
        names = []
    if session:
        names = [n for n in names if n.startswith(session[:8])]
    if not names:
        raise FileNotFoundError(
            f"No Claude Code transcript found under {tdir!r}"
            + (f" for session {session!r}" if session else "")
            + " — pass an explicit transcript path."
        )
    names.sort(key=lambda n: (os.path.getmtime(os.path.join(tdir, n)), n))
    return os.path.join(tdir, names[-1])


def read_latest_gist(out_dir: str = ".claude/ctx") -> str:
    """Return the most recent gist text, or empty string if none exists."""
    path = os.path.join(out_dir, "latest-gist.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ── Cross-session project gist ──
#
# latest-gist.md answers "what happened last session"; the project gist
# answers "what has this repo decided across ALL sessions" — the fast
# onboarding context for a new agent (or a new machine) picking up
# multi-day work. Only the stakes trio crosses sessions: constraints,
# decisions, failed approaches. Everything else stays per-session.

PROJECT_GIST_BPE_BUDGET = 1500

_PROJECT_KINDS = (
    ("CONSTRAINT", "Constraints (verbatim — do not violate)"),
    ("DECISION", "Decisions"),
    ("FAILED-APPROACH", "Failed approaches (do not retry)"),
)


def _journal_session_order(out_dir: str) -> list[str]:
    """Session ids (8-char) in first-checkpoint order — the deterministic
    chronology source (file mtimes are not portable)."""
    order: list[str] = []
    seen: set[str] = set()
    try:
        with open(os.path.join(out_dir, "checkpoints.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    sid = str(json.loads(line).get("session", ""))[:8]
                except json.JSONDecodeError:
                    continue
                if sid and sid not in seen:
                    seen.add(sid)
                    order.append(sid)
    except OSError:
        pass
    return order


def build_project_gist(out_dir: str = ".claude/ctx",
                       exclude_session: str = "",
                       ranks: "Optional[dict[str, float]]" = None) -> str:
    """Merge the stakes trio across all session ledgers, oldest first.

    ``exclude_session`` is the session whose own gist is injected
    alongside (latest-gist.md) — leaving it out avoids double-injection.
    Returns "" when no OTHER session exists (nothing to roll up).
    Deterministic: chronology from the journal, dedup by normalized text.
    With ``ranks`` (rank/v1 fold), budget pressure evicts the lowest-rank
    row of the lowest-stakes kind instead of whatever sits at the end of
    the file — render order stays chronological.
    """
    from ..core.parser import parse as _parse_ctx
    from .session_reader import (
        _kind_of, _kv, _primary_value, _sections, _turn_of,
    )

    exclude = exclude_session[:8]
    on_disk = set()
    try:
        for name in os.listdir(out_dir):
            if name.startswith("session-") and name.endswith(".ctx"):
                on_disk.add(name[len("session-"):-len(".ctx")])
    except OSError:
        return ""
    ordered = [s for s in _journal_session_order(out_dir) if s in on_disk]
    ordered += sorted(on_disk - set(ordered))  # journal-less stragglers
    sids = [s for s in ordered if s != exclude]
    if not sids:
        return ""

    # kind → list of (sid, turn, text, score); dedup across sessions
    rows: dict[str, list] = {kind: [] for kind, _ in _PROJECT_KINDS}
    seen_hashes: set[str] = set()
    for sid in sids:
        path = os.path.join(out_dir, f"session-{sid}.ctx")
        try:
            with open(path, encoding="utf-8") as f:
                doc = _parse_ctx(f.read(), level=2)
        except Exception:  # noqa: BLE001 — one bad ledger must not kill the rollup
            continue
        for section in _sections(doc):
            kind = _kind_of(section)
            if kind not in rows:
                continue
            text = _primary_value(section)
            if not text:
                continue
            fingerprint = " ".join(text.lower().split())
            if fingerprint in seen_hashes:
                continue
            seen_hashes.add(fingerprint)
            score = 0.0
            if ranks:
                fid = _kv(section, "FACT-ID")
                if fid and fid in ranks:
                    score = ranks[fid]
                else:  # pre-event-log ledgers: score from static priors
                    score = rank.prior_for(
                        kind, basis=_kv(section, "BASIS"),
                        marker=decision_marker(text))
            rows[kind].append((sid, _turn_of(section), text, score))

    if not any(rows.values()):
        return ""

    header = [
        f"# Project memory ({len(sids)} earlier session"
        f"{'s' if len(sids) != 1 else ''}, oldest first)",
        "",
        "Cross-session ledger rollup. Detail per session: "
        "`ctxpack session decisions --session <id>`.",
    ]

    def _render() -> "tuple[str, list[str]]":
        lines = list(header)
        for kind, title in _PROJECT_KINDS:
            if not rows[kind]:
                continue
            lines.append("")
            lines.append(f"## {title}")
            for sid, turn, text, _score in rows[kind]:
                lines.append(f"- {text} (s:{sid}#turn{turn})")
        return "\n".join(lines), lines

    text_out, lines = _render()
    if not ranks:
        # Stakes-ordered trim, same policy as the legacy session gist
        while (_count_bpe(text_out) > PROJECT_GIST_BPE_BUDGET
               and len(lines) > 4):
            lines.pop()
            text_out = "\n".join(lines)
        return text_out

    # Global lowest-rank eviction — same rationale as the session gist:
    # the fold's priors and the constraint floor encode the stakes order
    while _count_bpe(text_out) > PROJECT_GIST_BPE_BUDGET and len(lines) > 4:
        candidates = [(row, kind) for kind, _ in _PROJECT_KINDS
                      for row in rows[kind]]
        if not candidates:
            break
        # Evict lowest rank; ties evict the oldest row first
        victim, kind = min(candidates,
                           key=lambda pair: (pair[0][3], pair[0][1],
                                             pair[0][0], pair[0][2]))
        rows[kind].remove(victim)
        text_out, lines = _render()
    return text_out


def read_startup_context(out_dir: str = ".claude/ctx") -> str:
    """What SessionStart injects: project rollup (if any) + last session's
    gist. Either part may be empty; both empty → ''. """
    project = ""
    try:
        with open(os.path.join(out_dir, "project-gist.md"),
                  encoding="utf-8") as f:
            project = f.read().strip()
    except OSError:
        pass
    latest = read_latest_gist(out_dir).strip()
    if project and latest:
        return f"{project}\n\n---\n\n{latest}"
    return project or latest


# ── Stop-hook debounce ──
#
# The Stop hook fires after every completed turn; re-packing each time is
# wasteful and adds latency to every exchange. Checkpoint only when the
# transcript has grown by DEBOUNCE turns since this session's last
# checkpoint (env CTXPACK_STOP_DEBOUNCE_TURNS; 0 = every turn). Between
# Stop checkpoints the raw transcript still protects everything — this
# just shrinks the catch-up window after a hard kill to ~a few turns.

STOP_DEBOUNCE_TURNS_DEFAULT = 10


def _count_transcript_turns(transcript_path: str) -> int:
    """Cheap turn count matching parse_transcript's entry filter."""
    count = 0
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") not in ("user", "assistant"):
                    continue
                if d.get("isSidechain") or d.get("isMeta"):
                    continue
                count += 1
    except OSError:
        return 0
    return count


def _last_checkpoint_turns(out_dir: str, session_id: str) -> int:
    """Turns recorded at this session's most recent checkpoint (0 if none)."""
    last = 0
    try:
        with open(os.path.join(out_dir, "checkpoints.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if session_id and row.get("session") == session_id:
                    last = int(row.get("turns", 0) or 0)
    except OSError:
        return 0
    return last


def should_checkpoint_on_stop(
    transcript_path: str,
    out_dir: str,
    session_id: str = "",
    debounce_turns: Optional[int] = None,
) -> bool:
    """Debounce gate for the Stop hook. True when the session has grown
    enough since its last checkpoint to be worth a re-pack."""
    if debounce_turns is None:
        try:
            debounce_turns = int(os.environ.get(
                "CTXPACK_STOP_DEBOUNCE_TURNS", STOP_DEBOUNCE_TURNS_DEFAULT))
        except ValueError:
            debounce_turns = STOP_DEBOUNCE_TURNS_DEFAULT
    now = _count_transcript_turns(transcript_path)
    if now == 0:
        return False
    last = _last_checkpoint_turns(out_dir, session_id)
    if now <= last:
        return False  # nothing new since the last checkpoint
    if last == 0:
        return True   # first checkpoint of the session
    return (now - last) >= max(debounce_turns, 1)
