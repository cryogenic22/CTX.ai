"""Claude Code session transcript → IRCorpus.

Parses the session JSONL that Claude Code writes (the ``transcript_path``
every hook receives) into the packer IR, extracting ONLY structurally
identifiable, load-bearing facts — the deterministic-extraction contract:

- USER-REQUEST     what the user asked for (first line of each user turn)
- CONSTRAINT       imperative/negation sentences from USER turns, verbatim
                   (never prose-compressed — negations must survive)
- DECISION         decision-shaped sentences from assistant text
- FAILED-APPROACH  dead ends the assistant declared
- ERROR            tool results flagged is_error
- FILE-*           one entity per file edited/written (edit counts, last turn)
- TASK-*           TodoWrite / TaskCreate items with status
- Read/Grep/Glob and other read-only tool chatter is deliberately dropped:
  it is recoverable from the raw transcript (L0), which is never deleted.

Every fact carries turn provenance (``session:{id}#turn{n}``) so
supersession can order revisions and ``ctx/why`` can point back to the
exact exchange. Zero LLM calls; same transcript → same IR.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.packer.ir import IRCorpus, IREntity, IRField, IRSource

# ── Extraction patterns ──

# User-turn sentences that read as standing instructions/constraints
_CONSTRAINT_RE = re.compile(
    r"(?i)\b(do not|don'?t|never|must not|mustn'?t|no longer|always|"
    r"make sure|be careful|remember to|must \w+|should not|shouldn'?t|"
    r"only use|use only|stick to|keep .{0,40}\b(under|below|within))\b"
)

# Assistant sentences that read as decisions / conclusions. The reliable
# path is the explicit "Decision:" convention (the dogfood CLAUDE.md asks
# sessions to state decisions that way); the verb patterns are best-effort.
_DECISION_RE = re.compile(
    r"(?i)(?:\b(?:decision|conclusion|verdict|confirmed)\s*:"
    r"|\b(?:decided to|i'?ll (?:use|go with|take)|going with|"
    r"we'?ll (?:use|go with)|chose|choosing|settled on|root cause|"
    r"caused by|the fix (?:is|was)|fixed by|renamed?|instead of using|"
    r"switch(?:ed|ing) to|the right (?:move|approach|fix) is|"
    r"key finding)\b)"
)

# User messages longer than this (after cleaning) are treated as pasted
# material (transcripts, logs, articles): still scanned for the request
# line, but NOT mined for constraints — quoted prose is full of imperative
# sentences that are not instructions to the agent.
_PASTED_CONTENT_THRESHOLD = 3000

# Sentences riddled with video/log timestamps are quoted material
_TIMESTAMP_NOISE_RE = re.compile(r"\b\d+:\d{2}\b")

_FAILED_RE = re.compile(
    r"(?i)\b(didn'?t work|doesn'?t work|dead end|failed because|"
    r"abandon(?:ed|ing)|gave up on|reverted|turned out to be wrong|"
    r"false (?:positive|start)|won'?t work because)\b"
)

_SYS_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_TAGGED_META_RE = re.compile(
    r"<(local-command-caveat|command-name|command-message|command-args|"
    r"local-command-stdout)>.*?</\1>", re.DOTALL,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# Tools whose invocations mutate state and deserve per-file tracking
_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}


@dataclass
class TranscriptStats:
    """Extraction coverage counters for the go/no-go gate."""

    turns: int = 0
    user_turns: int = 0
    requests: int = 0
    constraints: int = 0
    decisions: int = 0
    failed_approaches: int = 0
    errors: int = 0
    files_changed: int = 0
    tasks: int = 0
    bash_commands: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class ParsedTranscript:
    corpus: IRCorpus = field(default_factory=IRCorpus)
    stats: TranscriptStats = field(default_factory=TranscriptStats)
    session_id: str = ""
    last_turn: int = 0


def _clean(text: str, limit: int = 300) -> str:
    """Sanitize a value for a line-oriented KV: strip meta, collapse ws."""
    text = _SYS_REMINDER_RE.sub("", text)
    text = _TAGGED_META_RE.sub("", text)
    text = " ".join(text.split())
    return text[:limit]


def _clean_multiline(text: str, limit: int = 100_000) -> str:
    """Like _clean but preserves line breaks — used before sentence
    splitting so bullet-list items stay separate sentences instead of
    merging into one over-length (and therefore dropped) blob."""
    text = _SYS_REMINDER_RE.sub("", text)
    text = _TAGGED_META_RE.sub("", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:limit]


def _short_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8].upper()


def _file_entity_name(path: str) -> str:
    norm = re.sub(r"[^\w.-]+", "-", path).strip("-").upper()
    norm = norm.replace(".", "-")
    return f"FILE-{norm[-60:]}"


def _sentences(text: str) -> list[str]:
    return [
        s.strip() for s in _SENTENCE_SPLIT_RE.split(text)
        if 15 <= len(s.strip()) <= 300
    ]


def _text_of(content: Any) -> str:
    """Concatenated text blocks of a message content (str or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            blk.get("text", "") for blk in content
            if isinstance(blk, dict) and blk.get("type") == "text"
        )
    return ""


def parse_transcript(
    path: str,
    *,
    domain: Optional[str] = None,
    since_turn: int = 0,
) -> ParsedTranscript:
    """Parse a Claude Code session JSONL into IR.

    Args:
        path: transcript_path as provided by Claude Code hooks.
        domain: .ctx header domain; defaults to session-<id[:8]>.
        since_turn: skip turns below this index (incremental checkpoints —
            pass the previous checkpoint's ``last_turn``).
    """
    session_id = ""
    entries: list[dict] = []
    with open(path, encoding="utf-8") as f:
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
            entries.append(d)
            if not session_id:
                session_id = str(d.get("sessionId", ""))

    sid = session_id[:8] if session_id else "unknown"
    corpus = IRCorpus(domain=domain or f"session-{sid}")
    stats = TranscriptStats()
    src_file = f"session:{sid}"

    seen_names: set[str] = set()
    file_edits: dict[str, dict] = {}  # path → {count, last_turn, tools}
    tool_seq = 0
    source_words = 0

    def _src(turn: int, ts: str) -> IRSource:
        return IRSource(file=src_file, turn=turn, timestamp=ts)

    entities_by_name: dict[str, IREntity] = {}

    def _add(name: str, fields: dict[str, str], *, turn: int, ts: str,
             salience: float, update: bool = False) -> None:
        nonlocal source_words
        if name in seen_names:
            if update and name in entities_by_name:
                # Refresh mutable fields in place (e.g. a TodoWrite status
                # change) — first-wins dedup must not freeze task state.
                entity = entities_by_name[name]
                for key, value in fields.items():
                    key_norm = key.upper().replace("_", "-")
                    for f in entity.fields:
                        if f.key == key_norm and value:
                            f.value = value
                            f.raw_value = value
                            f.source = _src(turn, ts)
            return
        seen_names.add(name)
        entity = IREntity(name=name, sources=[_src(turn, ts)], salience=salience)
        for key, value in fields.items():
            if not value:
                continue
            entity.fields.append(IRField(
                key=key.upper().replace("_", "-"),
                value=value,
                raw_value=value,
                source=_src(turn, ts),
                salience=salience,
            ))
            source_words += len(str(value).split())
        corpus.entities.append(entity)
        entities_by_name[name] = entity

    for turn, d in enumerate(entries):
        if turn < since_turn:
            continue
        stats.turns = turn + 1
        ts = str(d.get("timestamp", ""))
        msg = d.get("message", {}) or {}
        content = msg.get("content")

        if d["type"] == "user":
            # tool_result blocks arrive as user entries — handle them AND
            # any text blocks in the same message (mixed messages happen)
            blocks = content if isinstance(content, list) else []
            for tr in blocks:
                if not (isinstance(tr, dict) and tr.get("type") == "tool_result"):
                    continue
                if tr.get("is_error"):
                    # content may be a string OR a list of text blocks —
                    # str() on a block list writes repr garbage
                    tr_content = tr.get("content", "")
                    text = _clean(_text_of(tr_content) or str(tr_content), 240)
                    if text:
                        stats.errors += 1
                        _add(f"ERROR-{_short_hash(text)}",
                             {"message": text, "turn": str(turn)},
                             turn=turn, ts=ts, salience=1.5)

            text = _clean_multiline(_text_of(content))
            if not text:
                continue
            stats.user_turns += 1

            # The request itself: first line, verbatim
            first_line = text.split(". ")[0][:280]
            stats.requests += 1
            _add(f"USER-REQUEST-{_short_hash(first_line)}",
                 {"request": first_line, "turn": str(turn)},
                 turn=turn, ts=ts, salience=2.0)

            # Constraints: verbatim, never compressed — negations intact.
            # Skip pasted material (long messages) and timestamp-riddled
            # quoted prose: imperative sentences there aren't instructions.
            if len(text) <= _PASTED_CONTENT_THRESHOLD:
                for sentence in _sentences(text):
                    if len(_TIMESTAMP_NOISE_RE.findall(sentence)) >= 2:
                        continue
                    if _CONSTRAINT_RE.search(sentence):
                        stats.constraints += 1
                        # store the full admitted sentence — truncating
                        # below the 300-char admission cap could sever a
                        # trailing negation
                        _add(f"CONSTRAINT-{_short_hash(sentence)}",
                             {"rule": sentence, "stated_turn": str(turn)},
                             turn=turn, ts=ts, salience=3.0)

        else:  # assistant
            blocks = content if isinstance(content, list) else []
            for blk in blocks:
                if not isinstance(blk, dict):
                    continue
                btype = blk.get("type")

                if btype == "text":
                    for sentence in _sentences(_clean_multiline(blk.get("text", ""))):
                        if _FAILED_RE.search(sentence):
                            stats.failed_approaches += 1
                            _add(f"FAILED-APPROACH-{_short_hash(sentence)}",
                                 {"note": sentence[:280], "turn": str(turn)},
                                 turn=turn, ts=ts, salience=2.2)
                        elif _DECISION_RE.search(sentence):
                            stats.decisions += 1
                            _add(f"DECISION-{_short_hash(sentence)}",
                                 {"decision": sentence[:280], "turn": str(turn)},
                                 turn=turn, ts=ts, salience=2.5)

                elif btype == "tool_use":
                    tool_seq += 1
                    name = str(blk.get("name", ""))
                    tool_input = blk.get("input", {}) or {}

                    if name in _WRITE_TOOLS:
                        fpath = str(tool_input.get("file_path")
                                    or tool_input.get("notebook_path") or "")
                        if fpath:
                            rec = file_edits.setdefault(
                                fpath, {"count": 0, "last_turn": 0, "ts": ts})
                            rec["count"] += 1
                            rec["last_turn"] = turn
                            rec["ts"] = ts
                    elif name in ("TodoWrite", "TaskCreate"):
                        todos = tool_input.get("todos")
                        if isinstance(todos, list):
                            for todo in todos:
                                subject = _clean(str(todo.get("content", "")), 200)
                                if subject:
                                    stats.tasks += 1
                                    _add(f"TASK-{_short_hash(subject)}",
                                         {"task": subject,
                                          "status": str(todo.get("status", "")),
                                          "turn": str(turn)},
                                         turn=turn, ts=ts, salience=1.6,
                                         update=True)
                        else:
                            subject = _clean(str(tool_input.get("subject", "")), 200)
                            if subject:
                                stats.tasks += 1
                                _add(f"TASK-{_short_hash(subject)}",
                                     {"task": subject, "turn": str(turn)},
                                     turn=turn, ts=ts, salience=1.6)
                    elif name == "Bash":
                        desc = _clean(str(tool_input.get("description", "")), 160)
                        if desc:
                            stats.bash_commands += 1
                            _add(f"TOOL-BASH-{tool_seq:04d}",
                                 {"ran": desc,
                                  "command": _clean(
                                      str(tool_input.get("command", "")), 160),
                                  "turn": str(turn)},
                                 turn=turn, ts=ts, salience=1.0)

    # One entity per touched file, edit counts aggregated
    for fpath, rec in sorted(file_edits.items()):
        stats.files_changed += 1
        _add(_file_entity_name(fpath),
             {"path": fpath, "edits": str(rec["count"]),
              "last_turn": str(rec["last_turn"])},
             turn=rec["last_turn"], ts=rec["ts"], salience=1.4)

    corpus.source_token_count = source_words
    corpus.source_files = [src_file]

    return ParsedTranscript(
        corpus=corpus,
        stats=stats,
        session_id=session_id,
        last_turn=len(entries),
    )
