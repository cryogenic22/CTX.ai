"""Capture exclusion config.

Harness text, pasted briefings, and probe exchanges are not ledger facts.
Defaults are deterministic and overridable from a repo ``ctxpack.toml``
``[capture]`` table or from checkpoint CLI flags. A missing file means
the defaults. File order is preserved; nothing is sorted by hash.

Block delimiters are matched literally (case-sensitive). An empty end
delimiter consumes through the end of the turn, and an unclosed end
delimiter does the same (fail closed: a pasted briefing cannot leak
facts after a missing close). Turn prefixes are matched on the first
non-empty line, case-insensitively, after a leading list marker is
removed. Probe prefixes also mark the following assistant text as an
answer to the probe, which is not mined.

Commit-subject prefixes use the same predicate. Commit mining itself is
not wired (the L1 commit adapter stays unsupported); the predicate is
the rule that miner must call.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from typing import Iterable, Optional, Sequence

from ..core.packer.toml_parser import toml_parse

# First-line prefixes whose whole turn is never mined.
DEFAULT_IGNORE_TURN_PREFIXES: tuple[str, ...] = (
    "recall:",
    "hooks:",
    "harness:",
    "recall probe",
    "audit check prompt:",
)

# Prefixes that also suppress the following assistant text (the answer).
DEFAULT_PROBE_PREFIXES: tuple[str, ...] = (
    "recall:",
    "recall probe",
    "audit check prompt:",
)

DEFAULT_IGNORE_COMMIT_SUBJECT_PREFIXES: tuple[str, ...] = (
    "recall:",
    "hooks:",
    "harness:",
)

# (start, end). Empty end → through the end of the turn.
DEFAULT_IGNORE_BLOCKS: tuple[tuple[str, str], ...] = (
    ("CTX BRIEFING", ""),
    ("HARNESS SESSION MESSAGE", ""),
    ("<ctx-briefing>", "</ctx-briefing>"),
    # Our own gist headers. A pasted briefing is the feedback loop that
    # re-banks last session's constraints as new facts.
    ("# Session memory", ""),
    ("# Project memory", ""),
)

_CONFIG_NAMES = ("ctxpack.toml", ".ctxpack.toml")
_LEADING_LIST_RE = re.compile(r"^(?:(?:[-*•>]|\d{1,3}[.)])\s+)+")


def _strip_list_marker(line: str) -> str:
    return _LEADING_LIST_RE.sub("", line).strip()


@dataclass(frozen=True)
class CaptureConfig:
    """What the transcript parser must not bank.

    ``ignore_blocks`` entries are ``(start, end)`` delimiter pairs.
    ``capture_tool_bash`` defaults to True: one TOOL-BASH row per shell
    command, the historical behavior. Set it false to skip those rows.
    """

    ignore_blocks: tuple[tuple[str, str], ...] = DEFAULT_IGNORE_BLOCKS
    ignore_turn_prefixes: tuple[str, ...] = DEFAULT_IGNORE_TURN_PREFIXES
    probe_prefixes: tuple[str, ...] = DEFAULT_PROBE_PREFIXES
    ignore_commit_subject_prefixes: tuple[str, ...] = (
        DEFAULT_IGNORE_COMMIT_SUBJECT_PREFIXES)
    capture_tool_bash: bool = True


def default_capture_config() -> CaptureConfig:
    return CaptureConfig()


def _as_str_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else default
    if isinstance(value, (list, tuple)):
        out = tuple(str(item).strip() for item in value if str(item).strip())
        return out
    return default


def _parse_block_item(item: str) -> tuple[str, str]:
    """``start:::end``. A missing end (``start:::`` or no separator) runs
    to the end of the turn. Both pieces are non-empty strings when the
    end is present, so a 3.10 TOML subset that drops ``""`` array items
    cannot shift the pairing.
    """
    start, sep, end = str(item).partition(":::")
    if not sep:
        start, end = str(item), ""
    return start.strip(), end.strip()


def _blocks_from_table(table: dict) -> tuple[tuple[str, str], ...]:
    """``ignore_blocks`` is a list of ``start:::end`` strings.

    A missing key keeps the default. A present key replaces the default
    even when the list is empty (an explicit empty list mines blocks).
    """
    if "ignore_blocks" not in table:
        return DEFAULT_IGNORE_BLOCKS
    raw = table.get("ignore_blocks")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return DEFAULT_IGNORE_BLOCKS
    pairs: list[tuple[str, str]] = []
    for item in raw:
        start, end = _parse_block_item(str(item))
        if start:
            pairs.append((start, end))
    return tuple(pairs)


def load_capture_config(directory: str = ".") -> CaptureConfig:
    """Load ``[capture]`` from ``ctxpack.toml`` or ``.ctxpack.toml``.

    Only ``directory`` itself is searched (not parents). ``ctxpack.toml``
    wins when both names exist. A missing file or a missing ``[capture]``
    table returns the defaults. Keys that are present replace that
    default; keys that are absent keep it.
    """
    path = ""
    for name in _CONFIG_NAMES:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            path = candidate
            break
    if not path:
        return default_capture_config()
    with open(path, encoding="utf-8") as f:
        data = toml_parse(f.read(), filename=path)
    table = data.get("capture") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return default_capture_config()
    tool_bash = table.get("capture_tool_bash", True)
    if not isinstance(tool_bash, bool):
        tool_bash = str(tool_bash).strip().lower() not in {"0", "false", "no"}
    return CaptureConfig(
        ignore_blocks=_blocks_from_table(table),
        ignore_turn_prefixes=_as_str_tuple(
            table.get("ignore_turn_prefixes"), DEFAULT_IGNORE_TURN_PREFIXES),
        probe_prefixes=_as_str_tuple(
            table.get("probe_prefixes"), DEFAULT_PROBE_PREFIXES),
        ignore_commit_subject_prefixes=_as_str_tuple(
            table.get("ignore_commit_subject_prefixes"),
            DEFAULT_IGNORE_COMMIT_SUBJECT_PREFIXES),
        capture_tool_bash=bool(tool_bash),
    )


def with_cli_overrides(
    base: CaptureConfig,
    *,
    extra_turn_prefixes: Sequence[str] = (),
    extra_blocks: Sequence[str] = (),
    capture_tool_bash: Optional[bool] = None,
) -> CaptureConfig:
    """Append CLI prefixes and ``start:::end`` blocks. Does not reorder."""
    prefixes = list(base.ignore_turn_prefixes)
    for raw in extra_turn_prefixes:
        text = str(raw).strip()
        if text and text not in prefixes:
            prefixes.append(text)
    blocks = list(base.ignore_blocks)
    for raw in extra_blocks:
        start, sep, end = str(raw).partition(":::")
        if not sep:
            start, end = str(raw), ""
        start, end = start.strip(), end.strip()
        if start and (start, end) not in blocks:
            blocks.append((start, end))
    tool = base.capture_tool_bash if capture_tool_bash is None else capture_tool_bash
    return replace(
        base,
        ignore_turn_prefixes=tuple(prefixes),
        ignore_blocks=tuple(blocks),
        capture_tool_bash=tool,
    )


def _first_content_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _matches_prefix(line: str, prefixes: Iterable[str]) -> bool:
    if not line:
        return False
    folded = _strip_list_marker(line).lower()
    for prefix in prefixes:
        p = str(prefix).strip().lower()
        if p and folded.startswith(p):
            return True
    return False


def _any_line_matches(text: str, prefixes: Iterable[str]) -> bool:
    prefs = tuple(prefixes)
    for line in text.splitlines():
        if _matches_prefix(line.strip(), prefs):
            return True
    return False


def commit_subject_excluded(subject: str, config: Optional[CaptureConfig] = None) -> bool:
    """True when a commit subject must not be mined for facts."""
    cfg = config or default_capture_config()
    return _matches_prefix(str(subject or "").strip(), cfg.ignore_commit_subject_prefixes)


def strip_blocks(text: str, blocks: Sequence[tuple[str, str]]) -> tuple[str, bool]:
    """Remove delimited regions. Returns ``(remaining, removed_any)``.

    The earliest start wins; equal indexes keep config order. Each pass
    shortens the text, so the loop is bounded by the input length.
    """
    had = False
    guard = max(len(text), 1)
    for _ in range(guard):
        earliest: Optional[tuple[int, int, int]] = None
        for order, (start, end) in enumerate(blocks):
            if not start:
                continue
            idx = text.find(start)
            if idx < 0:
                continue
            if end:
                end_at = text.find(end, idx + len(start))
                if end_at < 0:
                    end_at = len(text)
                else:
                    end_at += len(end)
            else:
                end_at = len(text)
            cand = (idx, end_at, order)
            if earliest is None or cand < earliest:
                earliest = cand
        if earliest is None:
            break
        had = True
        text = text[:earliest[0]] + text[earliest[1]:]
        if not text:
            break
    return text, had


def _earliest_block_start(text: str, blocks: Sequence[tuple[str, str]]) -> Optional[int]:
    found: Optional[tuple[int, int]] = None
    for order, (start, _end) in enumerate(blocks):
        if not start:
            continue
        idx = text.find(start)
        if idx < 0:
            continue
        cand = (idx, order)
        if found is None or cand < found:
            found = cand
    return None if found is None else found[0]


def _drop_briefing_preface(
    original: str,
    stripped: str,
    blocks: Sequence[tuple[str, str]],
) -> str:
    """Drop a one-line introducer that only announces a removed block.

    ``Pasting prior startup briefing block ...:`` before ``# Session memory``
    is harness framing, not a request. A preface that does not end in
    ``:`` is kept, and so is any text that follows the block.
    """
    idx = _earliest_block_start(original, blocks)
    if idx is None:
        return stripped
    preface = original[:idx].strip()
    if not preface or "\n" in preface or not preface.endswith(":"):
        return stripped
    remaining = stripped.strip()
    if remaining == preface:
        return ""
    if remaining.startswith(preface):
        return remaining[len(preface):].lstrip()
    return stripped


def prepare_user_turn(
    text: str,
    config: Optional[CaptureConfig] = None,
) -> tuple[Optional[str], bool]:
    """Return ``(text to mine or None, skip the next assistant text)``.

    ``None`` means the turn contributes no facts. The flag is set only
    for a probe exchange (a probe prefix on any line, or a fully
    excluded turn whose first line is a probe prefix) so the assistant's
    recall answer is not banked as a decision.
    """
    cfg = config or default_capture_config()
    original = text or ""
    stripped, had_block = strip_blocks(original, cfg.ignore_blocks)
    first = _first_content_line(original)
    prefix_excluded = _matches_prefix(first, cfg.ignore_turn_prefixes)
    probe = _any_line_matches(original, cfg.probe_prefixes)
    if prefix_excluded:
        return None, probe
    if had_block:
        stripped = _drop_briefing_preface(original, stripped, cfg.ignore_blocks)
        if not stripped.strip():
            return None, probe
    return stripped, False
