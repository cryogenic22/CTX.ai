"""Claude Code session transcript → IRCorpus.

Parses the session JSONL that Claude Code writes (the ``transcript_path``
every hook receives) into the packer IR, extracting ONLY structurally
identifiable, load-bearing facts — the deterministic-extraction contract:

- USER-REQUEST     what the user asked for (first line of each user turn)
- CONSTRAINT       imperative/negation sentences from USER turns, verbatim
                   (never prose-compressed — negations must survive), plus
                   explicit "Constraint:"-marked sentences from ASSISTANT
                   turns (agent-stated operating rules)
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

from ..core import factid
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
#
# The marker is anchored to the sentence START (optionally behind a bullet
# or bold prefix): dogfood showed the unanchored form fires on backticked
# *mentions* of the convention and on list-introducer lines that merely
# end in "verdict:". Matching runs against backtick-stripped prose (see
# _prose_of) so quoted code spans can't trigger any extractor.
_DECISION_MARKER_RE = re.compile(
    r"(?i)^(?:[-*•>]\s*)*(?:\*{1,2}|_{1,2})?"
    r"(?:decision|conclusion|verdict|confirmed)(?:\*{1,2}|_{1,2})?\s*:"
)
# Agent-stated operating rules: the explicit "Constraint:" convention,
# mirroring "Decision:" (same anchoring, same use-vs-mention guard). In
# agent-driven sessions the load-bearing constraints are often stated by
# the ASSISTANT (conservation rules, DoD, review gates) — cohort evidence:
# 49 decisions banked vs 1 constraint across 10 sessions, because the
# user-imperative extractor is the only constraint path. Marker-only on
# purpose: no verb heuristics — over-extraction of "rules" from ordinary
# prose is worse than asking sessions to mark them.
_CONSTRAINT_MARKER_RE = re.compile(
    r"(?i)^(?:[-*•>]\s*)*(?:\*{1,2}|_{1,2})?"
    r"(?:constraint|invariant)(?:\*{1,2}|_{1,2})?\s*:"
)

# Memory-incident telemetry: the explicit "ctx-incident:" convention —
# the ledger's own feedback loop (did ctx save/miss/mislead?). Same
# anchoring and use-vs-mention guard as Decision:/Constraint:. Payload is
# pipe-delimited key="value" pairs; only type + fact are REQUIRED — a
# demanding grammar would bias telemetry toward conscientious sessions.
# Fail-open: a marked line with a malformed payload is still banked
# (parse_ok=false, verbatim RAW kept) — a lost incident is itself the
# event this exists to record.
_INCIDENT_MARKER_RE = re.compile(
    r"(?i)^(?:[-*•>]\s*)*(?:\*{1,2}|_{1,2})?"
    r"ctx-incident(?:\*{1,2}|_{1,2})?\s*:\s*"
)
_INCIDENT_TYPES = frozenset((
    "saved",           # ledger supplied a fact the session would have lost
    "missed",          # fact should have been in the ledger and wasn't
    "stale",           # ledger served a superseded value as current
    "wrong",           # ledger fact was incorrect
    "conflicting",     # ledger returned contradictory facts
    "native-better",   # compaction summary / grep would have done better
    "user-corrected",  # the user had to correct the agent's recall
))
_INCIDENT_KV_RE = re.compile(r'^([A-Za-z][\w-]*)\s*=\s*(?:"([^"]*)"?|(.*))$')
_INCIDENT_FIELD_KEYS = ("fact", "expected", "got", "source", "evidence")


def _parse_incident_line(line: str) -> "dict | None":
    """None if the line is not incident-marked; otherwise a record —
    fail-open, so a malformed payload still comes back with
    parse_ok=False rather than vanishing."""
    if not _INCIDENT_MARKER_RE.match(_prose_of(line)):
        return None  # includes backtick-quoted mentions of the convention
    m = _INCIDENT_MARKER_RE.match(line)
    if not m:  # marker was only visible in blanked prose — quoted material
        return None
    parts = [p.strip() for p in line[m.end():].split("|")]
    itype = parts[0].lower().rstrip(".") if parts else ""
    fields: dict[str, str] = {}
    for part in parts[1:]:
        kv = _INCIDENT_KV_RE.match(part)
        if kv:
            value = kv.group(2) if kv.group(2) is not None else kv.group(3)
            fields[kv.group(1).lower()] = (value or "").strip().strip('"')[:300]
    parse_ok = itype in _INCIDENT_TYPES and bool(fields.get("fact"))
    return {"type": itype[:40], "fields": fields, "parse_ok": parse_ok}


_DECISION_VERB_RE = re.compile(
    r"(?i)\b(?:decided to|i'?ll (?:use|go with|take)|going with|"
    r"we'?ll (?:use|go with)|chose|choosing|settled on|"
    r"root cause\s*(?:is|was|:)|"  # assertion only — bare noun phrase
    # ("found the root cause") is a mention, not a stated conclusion
    r"caused by|the fix (?:is|was)|fixed by|renamed?|instead of using|"
    r"switch(?:ed|ing) to|the right (?:move|approach|fix) is|"
    r"key finding)"
)

# Inline code spans are quoted material, not statements by the assistant:
# "state `Decision: ...` lines" mentions the convention, it doesn't use it.
_INLINE_CODE_RE = re.compile(r"`[^`]*`")

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
# Harness-injected user-role messages (background-task completion notices
# etc.) are not things the user asked for. Whole block goes, tolerating a
# missing close tag — dogfood found one extracted as a USER-REQUEST.
_HARNESS_BLOCK_RE = re.compile(
    r"<(task-notification|task-reminder)>.*?(?:</\1>|\Z)", re.DOTALL,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# Tools whose invocations mutate state and deserve per-file tracking
_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# ── Read-path adoption telemetry (P4) ──
# Counted per tool_use and carried into checkpoints.jsonl via
# TranscriptStats: ledger_reads = the session used the checkpoint read
# path; transcript_greps = it fell back to the raw transcript despite the
# read path existing. The fallback rate is the earliest honest signal of
# whether the ledger earns its keep (CP-041's negative-value signal).

_LEDGER_READ_CMD_RE = re.compile(
    r"ctxpack(?:\.cli\.main)?['\"]?\s+session\b")
# MCP spellings: mcp__ctxpack__ctx/session_recall etc., normalized below
_LEDGER_TOOL_SUFFIXES = (
    "ctx_session_recall", "ctx_session_timeline", "ctx_session_decisions",
    "ctx_why", "ctx_graph_query", "ctx_session_literals", "ctx_resume",
)
_READONLY_PATH_TOOLS = {"Grep", "Read", "Glob"}


def _is_ledger_read_command(command: str) -> bool:
    c = " ".join(command.lower().split())
    if _LEDGER_READ_CMD_RE.search(c):
        return True
    return ("ctxpack" in c and "hydrate" in c
            and ".claude/ctx" in c.replace("\\", "/"))


def _touches_raw_transcript(text: str) -> bool:
    t = text.lower().replace("\\", "/")
    return ".claude/projects" in t and ".jsonl" in t


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
    literals: int = 0
    # Read-path adoption (P4): ledger reads vs raw-transcript fallbacks
    ledger_reads: int = 0
    transcript_greps: int = 0
    # Memory-incident telemetry (ctx-incident: convention); by-type counts
    # keyed by incident type, with malformed payloads under "unparsed"
    incidents: int = 0
    incident_types: dict = field(default_factory=dict)

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
    text = _HARNESS_BLOCK_RE.sub("", text)
    text = " ".join(text.split())
    return text[:limit]


def _clean_multiline(text: str, limit: int = 100_000) -> str:
    """Like _clean but preserves line breaks — used before sentence
    splitting so bullet-list items stay separate sentences instead of
    merging into one over-length (and therefore dropped) blob."""
    text = _SYS_REMINDER_RE.sub("", text)
    text = _TAGGED_META_RE.sub("", text)
    text = _HARNESS_BLOCK_RE.sub("", text)
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


def _prose_of(sentence: str) -> str:
    """The sentence with inline code spans blanked — extractors match on
    this so backtick-quoted mentions can't fire, while the verbatim
    sentence is still what gets stored."""
    return _INLINE_CODE_RE.sub(" ", sentence)


def _is_decision(sentence: str) -> bool:
    prose = _prose_of(sentence)
    return bool(_DECISION_MARKER_RE.match(prose) or _DECISION_VERB_RE.search(prose))


# ── Literal (verbatim-identifier) extraction ──
# Load-bearing identifiers must survive a compaction fold VERBATIM so the agent
# writes correct ids from the ledger instead of reconstructing them from a
# paraphrase ("the frequency was about 0.19"). ONLY high-precision, low-ambiguity
# classes — over-extraction is the failure mode the decision/constraint
# extractors guard against, and it applies here too. Unlike prose facts these
# are matched on the RAW text (backticks kept — ids live in backticks). No
# per-turn cap: silently dropping an id defeats the ledger's whole purpose;
# precision + dedup bound the count, and a display budget is enforced on the
# GIST (checkpoint.build_gist), not by discarding literals at extraction.
_LITERAL_URL_RE = re.compile(r"https?://[^\s)\]}>\"'`]+")
_LITERAL_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# Domain identifiers (bioinformatics/registry ids seen in real sessions) — a
# tagged prefix removes ambiguity entirely.
_LITERAL_DOMAIN_ID_RE = re.compile(
    r"\b(?:NCT|PMID|CHEMBL|ENSG|ENST|ENSP)\s?\d+\b|\bGO:\d{7}\b|\brs\d+\b")
# A filesystem path: at least one slash segment + a dotted extension (+ optional
# :line). Distinguishes "services/llm.py:42" from prose containing a slash.
_LITERAL_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/])?(?:[\w.\-]+[/\\])+[\w.\-]+\.[A-Za-z][A-Za-z0-9]{0,5}"
    r"(?::\d+)?")
_LITERAL_VERSION_RE = re.compile(r"\bv?\d+\.\d+\.\d+(?:[-.][0-9A-Za-z]+)*\b")
# PR/issue ref: a lone #NNN (not ## markdown, not a fragment like abc#1).
_LITERAL_PR_RE = re.compile(r"(?<![\w#])#\d{1,6}\b")
# Number WITH a curated unit — bare numbers are too noisy to bank.
# Word units require a trailing boundary; ``%`` is a non-word char so it must NOT
# (the ``\b`` after ``%`` only matched when a word char followed, so "100% sure"
# silently missed). ``x`` multipliers dropped — too noisy ("5-10x", "3x") to bank.
_LITERAL_NUMBER_UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:(?:ms|ns|kb|mb|gb|tb|bpe|px|tokens?|req/min)\b|%)",
    re.IGNORECASE)
# Git SHA: 7-40 hex, but ONLY inside a backtick span or after a commit-context
# word (a bare hex run in prose is almost always not a sha), AND containing both
# a letter and a digit (rules out prose words like "deadbeef" and pure decimals).
_LITERAL_HEX_RE = re.compile(r"[0-9a-f]{7,40}", re.IGNORECASE)
_SHA_CONTEXT_RE = re.compile(
    r"(?i)\b(?:commit|sha|revision|rev|head|tip|merged?|hash)\s+[`']?"
    r"([0-9a-f]{7,40})\b")
_BACKTICK_SPAN_RE = re.compile(r"`([^`]+)`")


def _looks_like_sha(tok: str) -> bool:
    t = tok.lower()
    return (7 <= len(t) <= 40
            and all(c in "0123456789abcdef" for c in t)
            and any(c.isdigit() for c in t)
            and any(c in "abcdef" for c in t))


def _extract_literals(text: str) -> list[tuple[str, str]]:
    """(kind, value) for every high-precision identifier in ``text``, in
    position order with longest-match-wins on overlap (so a URL is not also
    mined as a path). Values are VERBATIM. Deterministic."""
    # (start, -length, priority, kind, value) — priority breaks ties so a
    # more-specific class wins an exact-span collision.
    cands: list[tuple[int, int, int, str, str]] = []

    def add(kind: str, value: str, start: int, end: int, prio: int) -> None:
        cands.append((start, -(end - start), prio, kind, value))

    for m in _LITERAL_URL_RE.finditer(text):
        v = m.group(0).rstrip(".,);:]}\"'")
        add("url", v, m.start(), m.start() + len(v), 0)
    for m in _LITERAL_UUID_RE.finditer(text):
        add("uuid", m.group(0), m.start(), m.end(), 1)
    for m in _LITERAL_DOMAIN_ID_RE.finditer(text):
        add("domain_id", m.group(0), m.start(), m.end(), 2)
    for m in _LITERAL_PATH_RE.finditer(text):
        add("path", m.group(0), m.start(), m.end(), 3)
    for m in _LITERAL_VERSION_RE.finditer(text):
        v = m.group(0)
        parts = v.lstrip("v").split(".")
        numeric = [p for p in parts if p.isdigit()]
        # Reject non-versions that share the x.y.z shape: a >=4-digit component is
        # a year (dotted date "2026.07.04") or a phone group ("555.123.4567"); 4+
        # all-numeric parts is an IP address ("192.168.0.1").
        if any(len(p) >= 4 for p in numeric) or (
                len(parts) >= 4 and len(numeric) == len(parts)):
            continue
        add("version", v, m.start(), m.end(), 4)
    for span in _BACKTICK_SPAN_RE.finditer(text):
        base = span.start(1)
        for hm in _LITERAL_HEX_RE.finditer(span.group(1)):
            if _looks_like_sha(hm.group(0)):
                add("git_sha", hm.group(0), base + hm.start(), base + hm.end(), 5)
    for m in _SHA_CONTEXT_RE.finditer(text):
        if _looks_like_sha(m.group(1)):
            add("git_sha", m.group(1), m.start(1), m.end(1), 5)
    for m in _LITERAL_PR_RE.finditer(text):
        if len(m.group(0)) - 1 == 6:  # "#RRGGBB"-length all-digit token = colour
            continue
        add("pr", m.group(0), m.start(), m.end(), 6)
    for m in _LITERAL_NUMBER_UNIT_RE.finditer(text):
        add("number_unit", m.group(0), m.start(), m.end(), 7)

    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    out: list[tuple[str, str]] = []
    last_end = -1
    for start, neg_len, _prio, kind, value in cands:
        if start < last_end:
            continue
        out.append((kind, value))
        last_end = start - neg_len
    return out


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


# Incident fact= payloads resolve against these fact kinds' primary field
_INCIDENT_LINK_KINDS = {"DECISION": "DECISION", "CONSTRAINT": "RULE",
                        "LITERAL": "VALUE", "FAILED-APPROACH": "NOTE"}
_INCIDENT_LINK_MIN_LEN = 6  # below this, containment matches are noise


def _link_incidents(entities: list) -> None:
    """Spec v1.1 §8: resolve each incident's fact= text to a banked
    fact_id by conservative normalized containment — exactly one
    candidate links, anything ambiguous or unmatched stays empty
    (never guess; a wrong link is worse than no link)."""
    candidates: list[tuple[str, str]] = []
    for e in entities:
        for prefix, primary in _INCIDENT_LINK_KINDS.items():
            if not e.name.startswith(prefix + "-"):
                continue
            fid = next((f.value for f in e.fields if f.key == "FACT-ID"), "")
            val = factid.normalize_value(
                next((f.value for f in e.fields if f.key == primary), ""))
            if fid and len(val) >= _INCIDENT_LINK_MIN_LEN:
                candidates.append((fid, val))
            break
    if not candidates:
        return
    for e in entities:
        if not e.name.startswith("INCIDENT-"):
            continue
        fact_text = factid.normalize_value(
            next((f.value for f in e.fields if f.key == "FACT"), ""))
        if len(fact_text) < _INCIDENT_LINK_MIN_LEN:
            continue
        hits = {fid for fid, val in candidates
                if fact_text in val or val in fact_text}
        if len(hits) == 1:
            src = e.sources[0] if e.sources else None
            linked = next(iter(hits))
            e.fields.append(IRField(
                key="LINKED-FACT-ID", value=linked, raw_value=linked,
                source=src, salience=e.salience))


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
             salience: float, update: bool = False,
             fact: "tuple[str, str, str] | None" = None,
             basis: str = "") -> None:
        """fact=(kind, key, value) stamps the v1.1 substrate fields:
        FACT-ID (canonical content hash), BASIS (extraction mechanics,
        an enum never a float), STATUS (lifecycle, current at birth),
        EXTRACTOR (parser version — provenance, never identity)."""
        nonlocal source_words
        if fact is not None:
            kind, key, value = fact
            fields = {**fields,
                      "fact_id": factid.fact_id(kind, value, key=key),
                      "basis": basis or factid.FactBasis.STRUCTURAL.value,
                      "status": "current",
                      "extractor": factid.EXTRACTOR_VERSION}
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

    def _extract_incidents(text: str, *, turn: int, ts: str) -> str:
        """Bank ctx-incident: lines and return the text WITHOUT them, so
        downstream extractors can't re-mine incident payloads (a stale
        `got` value must not get banked as a LITERAL; payload prose must
        not trigger the constraint patterns). Lines inside ``` fences are
        quoted material — kept, never banked."""
        if "ctx-incident" not in text.lower():
            return text  # fast path: nothing marked
        kept: list[str] = []
        fenced = False
        for line in text.splitlines():
            if line.lstrip().startswith("```"):
                fenced = not fenced
                kept.append(line)
                continue
            rec = None if fenced else _parse_incident_line(line)
            if rec is None:
                kept.append(line)
                continue
            stats.incidents += 1
            tkey = rec["type"] if rec["parse_ok"] else "unparsed"
            stats.incident_types[tkey] = stats.incident_types.get(tkey, 0) + 1
            fields = {"type": rec["type"], "parse_ok":
                      "true" if rec["parse_ok"] else "false",
                      "raw": line[:400], "turn": str(turn)}
            fields.update({k: rec["fields"].get(k, "")
                           for k in _INCIDENT_FIELD_KEYS})
            _add(f"INCIDENT-{_short_hash(line)}", fields,
                 turn=turn, ts=ts, salience=2.6,
                 fact=("INCIDENT", rec["type"], line),
                 basis=factid.FactBasis.MARKER_STATED.value)
        return "\n".join(kept)

    def _add_literals(text: str, *, turn: int, ts: str) -> None:
        """Bank each verbatim identifier as a LITERAL entity (dedup first-wins;
        stats count distinct)."""
        for kind, value in _extract_literals(text):
            name = f"LITERAL-{_short_hash(value)}"
            if name not in seen_names:
                stats.literals += 1
            _add(name, {"value": value, "kind": kind, "turn": str(turn)},
                 turn=turn, ts=ts, salience=2.4,
                 fact=("LITERAL", kind, value),
                 basis=factid.FactBasis.LITERAL_EXTRACTOR.value)

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
                             turn=turn, ts=ts, salience=1.5,
                             fact=("ERROR", "", text),
                             basis=factid.FactBasis.STRUCTURAL.value)

            text = _clean_multiline(_text_of(content))
            if not text:
                continue
            stats.user_turns += 1

            # Incidents first (short turns only — the pasted-content guard
            # applies: quoted transcripts full of incident lines must not
            # double-count); the request/constraint/literal extractors see
            # the text with incident lines removed
            if len(text) <= _PASTED_CONTENT_THRESHOLD:
                text = _extract_incidents(text, turn=turn, ts=ts)
                if not text.strip():
                    continue

            # The request itself: first line, verbatim
            first_line = text.split(". ")[0][:280]
            stats.requests += 1
            _add(f"USER-REQUEST-{_short_hash(first_line)}",
                 {"request": first_line, "turn": str(turn)},
                 turn=turn, ts=ts, salience=2.0,
                 fact=("USER-REQUEST", "", first_line),
                 basis=factid.FactBasis.STRUCTURAL.value)

            # Constraints: verbatim, never compressed — negations intact.
            # Skip pasted material (long messages) and timestamp-riddled
            # quoted prose: imperative sentences there aren't instructions.
            if len(text) <= _PASTED_CONTENT_THRESHOLD:
                for sentence in _sentences(text):
                    if len(_TIMESTAMP_NOISE_RE.findall(sentence)) >= 2:
                        continue
                    if _CONSTRAINT_RE.search(_prose_of(sentence)):
                        stats.constraints += 1
                        # store the full admitted sentence — truncating
                        # below the 300-char admission cap could sever a
                        # trailing negation
                        _add(f"CONSTRAINT-{_short_hash(sentence)}",
                             {"rule": sentence, "stated_turn": str(turn)},
                             turn=turn, ts=ts, salience=3.0,
                             fact=("CONSTRAINT", "", sentence),
                             basis=factid.FactBasis.USER_IMPERATIVE.value)
                # Verbatim identifiers the user named (short turns only — a
                # pasted log is skipped by the same threshold as constraints).
                _add_literals(text, turn=turn, ts=ts)

        else:  # assistant
            blocks = content if isinstance(content, list) else []
            for blk in blocks:
                if not isinstance(blk, dict):
                    continue
                btype = blk.get("type")

                if btype == "text":
                    atext = _clean_multiline(blk.get("text", ""))
                    atext = _extract_incidents(atext, turn=turn, ts=ts)
                    for sentence in _sentences(atext):
                        if _CONSTRAINT_MARKER_RE.match(_prose_of(sentence)):
                            stats.constraints += 1
                            # full sentence, same as user-path constraints:
                            # truncation could sever a trailing negation
                            _add(f"CONSTRAINT-{_short_hash(sentence)}",
                                 {"rule": sentence, "stated_turn": str(turn)},
                                 turn=turn, ts=ts, salience=3.0,
                                 fact=("CONSTRAINT", "", sentence),
                                 basis=factid.FactBasis.MARKER_STATED.value)
                        elif _FAILED_RE.search(_prose_of(sentence)):
                            stats.failed_approaches += 1
                            _add(f"FAILED-APPROACH-{_short_hash(sentence)}",
                                 {"note": sentence[:280], "turn": str(turn)},
                                 turn=turn, ts=ts, salience=2.2,
                                 fact=("FAILED-APPROACH", "", sentence),
                                 basis=factid.FactBasis.INFERRED.value)
                        elif _is_decision(sentence):
                            stats.decisions += 1
                            # marker-stated vs verb-pattern decisions carry
                            # different bases: only `inferred` may be wrong
                            # about whether this is a fact at all
                            d_basis = (
                                factid.FactBasis.MARKER_STATED.value
                                if _DECISION_MARKER_RE.match(
                                    _prose_of(sentence))
                                else factid.FactBasis.INFERRED.value)
                            _add(f"DECISION-{_short_hash(sentence)}",
                                 {"decision": sentence[:280], "turn": str(turn)},
                                 turn=turn, ts=ts, salience=2.5,
                                 fact=("DECISION", "", sentence),
                                 basis=d_basis)
                    # Verbatim identifiers stated in the assistant's reasoning
                    # (commit shas, PR #s, versions, paths, domain ids).
                    _add_literals(atext, turn=turn, ts=ts)

                elif btype == "tool_use":
                    tool_seq += 1
                    name = str(blk.get("name", ""))
                    tool_input = blk.get("input", {}) or {}

                    # Read-path adoption counters (no entity — just stats)
                    norm_name = name.lower().replace("/", "_").replace("-", "_")
                    if ("ctxpack" in norm_name
                            and norm_name.endswith(_LEDGER_TOOL_SUFFIXES)):
                        stats.ledger_reads += 1
                    elif name in _READONLY_PATH_TOOLS:
                        target = " ".join(str(v) for v in tool_input.values())
                        if _touches_raw_transcript(target):
                            stats.transcript_greps += 1
                    elif name == "Bash":
                        cmd = str(tool_input.get("command", ""))
                        if _is_ledger_read_command(cmd):
                            stats.ledger_reads += 1
                        elif (_touches_raw_transcript(cmd)
                              and "ctxpack" not in cmd.lower()):
                            # ctxpack checkpoint/hook invocations reference
                            # the transcript path — writes, not fallbacks
                            stats.transcript_greps += 1

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

    _link_incidents(corpus.entities)
    return ParsedTranscript(
        corpus=corpus,
        stats=stats,
        session_id=session_id,
        last_turn=len(entries),
    )
