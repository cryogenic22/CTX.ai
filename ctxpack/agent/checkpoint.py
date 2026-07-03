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
    ("FAILED-APPROACH", "Failed approaches (do not retry)", "NOTE"),
    ("USER-REQUEST", "What was asked", "REQUEST"),
    ("TASK", "Tasks", "TASK"),
    ("ERROR", "Errors seen", "MESSAGE"),
    ("FILE", "Files changed", "PATH"),
)


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
        lines.append("")
        lines.append(f"## {title}")
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
    import datetime
    journal_entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session": parsed.session_id,
        "turns": parsed.last_turn,
        "entities": len(corpus.entities),
        "conflicts": len(conflicts),
        "sha256": sha,
        "stats": parsed.stats.to_dict(),
    }
    with open(os.path.join(out_dir, "checkpoints.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps(journal_entry) + "\n")

    return CheckpointResult(
        session_id=parsed.session_id,
        ctx_path=ctx_path,
        gist_path=gist_path,
        turns=parsed.last_turn,
        entities=len(corpus.entities),
        conflicts=len(conflicts),
        ledger_sha256=sha,
        gist_bpe=_count_bpe(gist_text),
    )


def read_latest_gist(out_dir: str = ".claude/ctx") -> str:
    """Return the most recent gist text, or empty string if none exists."""
    path = os.path.join(out_dir, "latest-gist.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
