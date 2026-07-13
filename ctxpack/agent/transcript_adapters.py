"""Transcript-format adapters: many agent CLIs, ONE canonical entry
shape, one extraction pipeline.

Every adapter normalizes its source format into Claude-Code-shaped
entry dicts (``type`` user/assistant, ``message.content`` blocks,
``timestamp``) so the whole downstream IR machinery — markers,
literals, incidents, constraints, sidechain verdicts — works
unchanged for every agent. New formats are new adapters (or a
declarative spec for the generic adapter), never new extraction code.

Built-ins (auto-detected):
- ``claude-code`` — Claude Code session JSONL, byte-identical
  passthrough of the historical filtering.
- ``codex`` — Codex CLI rollout JSONL (``session_meta`` /
  ``response_item`` / ``event_msg`` envelopes). Only the
  ``response_item`` stream is consumed: it is the model-visible
  canonical record; ``event_msg`` user/agent messages duplicate it
  and the rest is telemetry. Encrypted ``reasoning`` items are
  skipped. Disclosed v1 limits: tool errors are not banked as ERROR
  entities (Codex outputs carry no is_error flag) and role=user
  envelope blocks (``<user_instructions>`` etc.) are skipped by tag
  shape.

Generic (explicit only, NEVER auto-detected — an unknown format must
fail loud, not be guessed at): ``GenericJSONLAdapter`` driven by a
small JSON spec mapping role/text/session-id/timestamp fields. This
is the no-hardcoding path for any other agent.

Detection is fail-loud: a transcript matching no known signature
raises TranscriptFormatError instead of silently parsing to an empty
corpus (the hollow-ledger failure class: the bracket blast-radius
bug and the Codex non-install decision are both incidents of it).

Zero runtime dependencies (stdlib only).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional


class TranscriptFormatError(RuntimeError):
    """The transcript matches no known format — refuse loudly."""


@dataclass
class NormalizedTranscript:
    """Adapter output: canonical entries + identity hints."""

    entries: list = field(default_factory=list)
    sidechain_entries: list = field(default_factory=list)
    session_id: str = ""
    adapter: str = ""
    raw_lines: int = 0  # parseable JSONL objects seen (hollow guard)


def _read_jsonl(path: str) -> "list[dict]":
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict):
                rows.append(d)
    return rows


# ── Claude Code (passthrough — must stay byte-identical) ────────────


class ClaudeCodeAdapter:
    name = "claude-code"

    @staticmethod
    def sniff(d: dict) -> bool:
        # Real CC lines carry uuid/sessionId; minimal CC-shaped entries
        # (tests, synthetic benchmarks) carry type+message. Both count.
        if d.get("type") in ("user", "assistant") and "message" in d:
            return True
        return "sessionId" in d or "parentUuid" in d or "uuid" in d

    def normalize(self, rows: "list[dict]") -> NormalizedTranscript:
        out = NormalizedTranscript(adapter=self.name, raw_lines=len(rows))
        for d in rows:
            if d.get("type") not in ("user", "assistant"):
                continue
            if d.get("isMeta"):
                continue  # harness chatter (task-notifications) — never banked
            if d.get("isSidechain"):
                # Subagent/workflow turns are dropped from the main parse,
                # but a marker-led verdict in one is a load-bearing finding
                # the main thread never sees (feedback #5). Keep assistant
                # sidechains for the narrow verdict-only pass.
                if d.get("type") == "assistant":
                    out.sidechain_entries.append(d)
                continue
            out.entries.append(d)
            if not out.session_id:
                out.session_id = str(d.get("sessionId", ""))
        return out


# ── Codex CLI rollout ────────────────────────────────────────────────

_CODEX_TYPES = ("session_meta", "response_item", "event_msg",
                "turn_context", "world_state", "compacted")
# role=user envelope blocks Codex injects around the conversation
# (<user_instructions>, <permissions instructions>, <environment_context>)
_CODEX_ENVELOPE_RE = re.compile(r"\s*<[a-zA-Z_][a-zA-Z0-9_ -]*>")


class CodexAdapter:
    name = "codex"

    @staticmethod
    def sniff(d: dict) -> bool:
        return (d.get("type") in _CODEX_TYPES
                and isinstance(d.get("payload"), dict))

    def normalize(self, rows: "list[dict]") -> NormalizedTranscript:
        out = NormalizedTranscript(adapter=self.name, raw_lines=len(rows))
        cwd = ""
        for d in rows:
            ts = str(d.get("timestamp", ""))
            payload = d.get("payload")
            if not isinstance(payload, dict):
                continue
            if d.get("type") == "session_meta":
                # payload.id names THIS rollout; session_id is the parent
                # thread for subagent spawns — the file is the session.
                out.session_id = str(payload.get("id")
                                     or payload.get("session_id") or "")
                cwd = str(payload.get("cwd", ""))
                continue
            if d.get("type") != "response_item":
                continue  # event_msg duplicates/telemetry; turn_context etc.
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role")
                text = "\n".join(
                    str(blk.get("text", "")) for blk in
                    (payload.get("content") or [])
                    if isinstance(blk, dict)
                    and blk.get("type") in ("input_text", "output_text")
                ).strip()
                if not text or role not in ("user", "assistant"):
                    continue  # developer/system envelopes never bank
                if role == "user" and _CODEX_ENVELOPE_RE.match(text):
                    continue  # instruction/environment wrapper, not the user
                out.entries.append({
                    "type": role, "timestamp": ts,
                    "message": {"content": [{"type": "text", "text": text}]},
                })
            elif ptype in ("function_call", "custom_tool_call"):
                raw_args = payload.get("arguments", payload.get("input", ""))
                try:
                    tool_input = json.loads(raw_args) if isinstance(
                        raw_args, str) else raw_args
                except json.JSONDecodeError:
                    tool_input = None
                if not isinstance(tool_input, dict):
                    tool_input = {"input": str(raw_args)[:400]}
                out.entries.append({
                    "type": "assistant", "timestamp": ts,
                    "message": {"content": [{
                        "type": "tool_use",
                        "name": str(payload.get("name", "")),
                        "input": tool_input,
                    }]},
                })
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                raw_out = payload.get("output", "")
                if isinstance(raw_out, list):
                    raw_out = "\n".join(
                        str(blk.get("text", "")) for blk in raw_out
                        if isinstance(blk, dict))
                out.entries.append({
                    "type": "user", "timestamp": ts,
                    "message": {"content": [{
                        "type": "tool_result",
                        "content": str(raw_out)[:2000],
                    }]},
                })
            # reasoning: encrypted — nothing recoverable, skipped
        if cwd and out.entries:
            out.entries[0].setdefault("cwd", cwd)
        return out


# ── Generic (spec-driven; explicit only, never sniffed) ─────────────


_GENERIC_REQUIRED = ("role_path", "user_values", "assistant_values",
                     "text_path")


def _dig(obj: Any, dotted: str) -> Any:
    """Resolve a dotted path (``payload.message.role``); list indices
    are numeric segments. Returns None on any miss."""
    cur = obj
    for seg in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(seg)
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            return None
    return cur


def _coerce_text(value: Any) -> str:
    """str → itself; list → joined strs / dicts' ``text`` fields."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(
                    item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


class GenericJSONLAdapter:
    """Field-map adapter for any role/text JSONL format. Built from a
    spec dict; used ONLY when the caller supplies the spec — unknown
    formats fail loud rather than being guessed at."""

    def __init__(self, spec: dict):
        missing = [k for k in _GENERIC_REQUIRED if not spec.get(k)]
        if missing:
            raise TranscriptFormatError(
                f"generic transcript spec is missing required keys: "
                f"{missing} (required: {list(_GENERIC_REQUIRED)})")
        self.spec = spec
        self.name = str(spec.get("name", "generic"))

    def normalize(self, rows: "list[dict]") -> NormalizedTranscript:
        out = NormalizedTranscript(adapter=self.name, raw_lines=len(rows))
        s = self.spec
        for d in rows:
            role = _dig(d, s["role_path"])
            if role in s["user_values"]:
                etype = "user"
            elif role in s["assistant_values"]:
                etype = "assistant"
            else:
                continue
            text = _coerce_text(_dig(d, s["text_path"])).strip()
            if not text:
                continue
            entry = {
                "type": etype,
                "timestamp": str(_dig(d, s["timestamp_path"]) or "")
                if s.get("timestamp_path") else "",
                "message": {"content": [{"type": "text", "text": text}]},
            }
            if not out.session_id and s.get("session_id_path"):
                out.session_id = str(_dig(d, s["session_id_path"]) or "")
            if not out.entries and s.get("cwd_path"):
                cwd = _dig(d, s["cwd_path"])
                if cwd:
                    entry["cwd"] = str(cwd)
            out.entries.append(entry)
        return out


def load_format_spec(path: str) -> GenericJSONLAdapter:
    try:
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise TranscriptFormatError(
            f"cannot load transcript format spec {path!r}: {exc}") from exc
    if not isinstance(spec, dict):
        raise TranscriptFormatError(
            f"transcript format spec {path!r} must be a JSON object")
    return GenericJSONLAdapter(spec)


# ── Detection + entry point ─────────────────────────────────────────

_BUILTIN_ADAPTERS = (ClaudeCodeAdapter(), CodexAdapter())
_DETECT_SAMPLE = 100


def detect_adapter(rows: "list[dict]", *, path: str = ""):
    """Pick the built-in adapter whose signature dominates the sample.

    Fail-loud: no match raises TranscriptFormatError naming the file,
    the known formats, and the generic-spec escape hatch — a foreign
    transcript must never silently parse to an empty corpus."""
    sample = rows[:_DETECT_SAMPLE]
    if not sample:
        # empty file: historical behavior (empty CC parse) — the hollow
        # guard upstream decides whether that is acceptable
        return _BUILTIN_ADAPTERS[0]
    hits = {a.name: sum(1 for d in sample if a.sniff(d))
            for a in _BUILTIN_ADAPTERS}
    best = max(_BUILTIN_ADAPTERS, key=lambda a: hits[a.name])
    if hits[best.name] == 0:
        known = ", ".join(a.name for a in _BUILTIN_ADAPTERS)
        raise TranscriptFormatError(
            f"unrecognized transcript format{f' in {path}' if path else ''}: "
            f"none of the first {len(sample)} JSONL objects match a known "
            f"agent signature (known: {known}). For another agent's "
            f"format, supply a field-map spec via --format-spec (see "
            f"GenericJSONLAdapter in ctxpack/agent/transcript_adapters.py). "
            f"Refusing to parse — a wrong-format parse would bank an "
            f"empty, misleading ledger.")
    return best


def load_transcript(path: str, *,
                    format_spec: Optional[str] = None,
                    ) -> NormalizedTranscript:
    """Read + normalize a transcript of ANY supported format into
    canonical Claude-Code-shaped entries (the single parser input)."""
    rows = _read_jsonl(path)
    if format_spec:
        adapter = load_format_spec(format_spec)
    else:
        adapter = detect_adapter(rows, path=path)
    return adapter.normalize(rows)
