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

from ..core.packer.compressor import compress
from ..core.packer.conflict import detect_conflicts
from ..core.packer.entity_resolver import resolve_entities
from ..core.serializer import serialize
from .transcript_parser import ParsedTranscript, parse_transcript

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


def build_gist(parsed: ParsedTranscript) -> str:
    """Render the session ledger as a compact markdown gist.

    Prose-first on purpose: models read markdown natively (.ctx notation is
    the storage format, not the injection format). Trimmed to
    GIST_BPE_BUDGET by dropping lines from the lowest-stakes section up.
    """
    ents = parsed.corpus.entities
    lines: list[str] = [
        f"# Session memory (session {parsed.session_id[:8]}, "
        f"{parsed.last_turn} turns)",
        "",
        "Deterministic ledger recovered from the session transcript. "
        "Full detail: `ctxpack hydrate` on the session .ctx, or grep the "
        "raw transcript.",
    ]
    for prefix, title, primary_key in _GIST_KINDS:
        matched = [e for e in ents if e.name.startswith(prefix)]
        if not matched:
            continue
        # Chronological: facts read in the order they happened
        matched.sort(key=lambda e: e.sources[0].turn if e.sources else 0)
        capped_note = ""
        if prefix == "LITERAL" and len(matched) > _GIST_LITERAL_CAP:
            # Signal the bound, never truncate silently: the full set stays in
            # the ledger (ctx/recall), the gist shows the most-recent slice.
            capped_note = (f" (showing {_GIST_LITERAL_CAP} most-recent of "
                           f"{len(matched)} — full set in the ledger)")
            matched = matched[-_GIST_LITERAL_CAP:]
        lines.append("")
        lines.append(f"## {title}{capped_note}")
        for e in matched:
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
            lines.append(f"- {value}{extra} (turn {turn})")

    text = "\n".join(lines)
    # Trim from the end until within budget — the section order guarantees
    # constraints/decisions are the last to go.
    while _count_bpe(text) > GIST_BPE_BUDGET and len(lines) > 4:
        lines.pop()
        text = "\n".join(lines)
    return text


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

    gist_text = build_gist(parsed)
    gist_path = os.path.join(out_dir, f"session-{sid}-gist.md")
    with open(gist_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(gist_text)
    with open(os.path.join(out_dir, "latest-gist.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(gist_text)

    sha = hashlib.sha256(ledger_text.encode("utf-8")).hexdigest()
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
        "stats": parsed.stats.to_dict(),
    }
    with open(os.path.join(out_dir, "checkpoints.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps(journal_entry) + "\n")

    # Regenerate the cross-session rollup (excludes this session — its own
    # gist is latest-gist.md, injected alongside)
    project_text = build_project_gist(out_dir, exclude_session=sid)
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
                       exclude_session: str = "") -> str:
    """Merge the stakes trio across all session ledgers, oldest first.

    ``exclude_session`` is the session whose own gist is injected
    alongside (latest-gist.md) — leaving it out avoids double-injection.
    Returns "" when no OTHER session exists (nothing to roll up).
    Deterministic: chronology from the journal, dedup by normalized text.
    """
    from ..core.parser import parse as _parse_ctx
    from .session_reader import _kind_of, _primary_value, _sections, _turn_of

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

    # kind → list of (sid, turn, text); dedup across sessions
    rows: dict[str, list[tuple[str, int, str]]] = {
        kind: [] for kind, _ in _PROJECT_KINDS}
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
            rows[kind].append((sid, _turn_of(section), text))

    if not any(rows.values()):
        return ""

    lines: list[str] = [
        f"# Project memory ({len(sids)} earlier session"
        f"{'s' if len(sids) != 1 else ''}, oldest first)",
        "",
        "Cross-session ledger rollup. Detail per session: "
        "`ctxpack session decisions --session <id>`.",
    ]
    for kind, title in _PROJECT_KINDS:
        if not rows[kind]:
            continue
        lines.append("")
        lines.append(f"## {title}")
        for sid, turn, text in rows[kind]:
            lines.append(f"- {text} (s:{sid}#turn{turn})")

    text_out = "\n".join(lines)
    # Stakes-ordered trim, same policy as the session gist
    while _count_bpe(text_out) > PROJECT_GIST_BPE_BUDGET and len(lines) > 4:
        lines.pop()
        text_out = "\n".join(lines)
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
