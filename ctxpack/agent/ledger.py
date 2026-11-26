"""Ledger paths, journal order, and atomic writes.

Leaf module: stdlib plus ``ctxpack.core`` only. ``checkpoint``,
``session_reader``, ``conflict_lint``, and ``brief`` import path, order,
and I/O helpers from here so they do not import each other for those
jobs.

Session filenames used to be ``session-<id[:8]>.ctx``. Two sessions that
share an 8-character prefix (Codex and custom adapters do this) overwrote
each other's ledger. New writes use the full sanitized id, or a
deterministic hash suffix when the id is long. Readers still open an
existing 8-character file when that is the only file for the session.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from typing import Optional

from ..core.errors import ParseError, classify_exception
from ..core.model import CTXDocument, KeyValue, Section
from ..core.serializer import serialize_section

SESSION_PREFIX = "session-"
SESSION_SUFFIX = ".ctx"
GIST_SUFFIX = "-gist.md"
LEGACY_STEM_LEN = 8
# Full sanitized ids are kept through this length (a UUID fits). Longer
# ids take a prefix plus a hash so two long ids cannot share a filename.
MAX_STEM_LEN = 80
_HASH_LEN = 12

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_TURN_IN_SRC_RE = re.compile(r"#turn(\d+)\b")

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


class UnsafeSessionId(ValueError):
    """Session id is not safe to use as a ledger filename."""


def ledger_stem(session_id: str) -> str:
    """Filesystem stem for ``session_id``.

    Empty becomes ``unknown``. ``/``, ``\\``, NUL, and ``..`` are rejected.
    Other characters outside ``[A-Za-z0-9._-]`` become ``-``. The full
    sanitized id is kept when it fits in :data:`MAX_STEM_LEN`; otherwise
    the stem is a prefix plus the first 12 hex chars of SHA-256 of the
    raw id, so two long ids never collide.
    """
    raw = (session_id or "").strip()
    if not raw:
        return "unknown"
    if "\x00" in raw or "/" in raw or "\\" in raw or ".." in raw or raw in {".", ".."}:
        raise UnsafeSessionId(
            f"refusing session id {raw!r}: path separator or '..'")
    sanitized = _UNSAFE_CHARS.sub("-", raw).strip(".-")
    if not sanitized or ".." in sanitized or sanitized in {".", ".."}:
        raise UnsafeSessionId(
            f"refusing session id {raw!r}: empty after sanitizing")
    if len(sanitized) <= MAX_STEM_LEN:
        return sanitized
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_HASH_LEN]
    head = sanitized[: MAX_STEM_LEN - 1 - _HASH_LEN].rstrip(".-")
    if not head:
        head = "s"
    return f"{head}-{digest}"


def legacy_stem(session_id: str) -> str:
    """Historical ``id[:8]`` filename stem, or ``""`` when that slice is unsafe.

    Used only to find a ledger written before collision-free stems.
    Never used as the name of a new file when a longer stem is required.
    """
    raw = (session_id or "").strip()
    stem = raw[:LEGACY_STEM_LEN]
    if (not stem or "/" in stem or "\\" in stem or ".." in stem
            or "\x00" in stem or not re.fullmatch(r"[A-Za-z0-9._-]+", stem)):
        return ""
    return stem


def session_ctx_name(stem: str) -> str:
    return f"{SESSION_PREFIX}{stem}{SESSION_SUFFIX}"


def session_gist_name(stem: str) -> str:
    return f"{SESSION_PREFIX}{stem}{GIST_SUFFIX}"


def ctx_path(ledger_dir: str, stem: str) -> str:
    return os.path.join(ledger_dir, session_ctx_name(stem))


def gist_path(ledger_dir: str, stem: str) -> str:
    return os.path.join(ledger_dir, session_gist_name(stem))


def list_session_stems(ledger_dir: str) -> list[str]:
    """Sorted filename stems of ``session-*.ctx`` in ``ledger_dir``."""
    try:
        names = os.listdir(ledger_dir)
    except OSError:
        return []
    stems = []
    for name in names:
        if name.startswith(SESSION_PREFIX) and name.endswith(SESSION_SUFFIX):
            stem = name[len(SESSION_PREFIX):-len(SESSION_SUFFIX)]
            if stem:
                stems.append(stem)
    return sorted(stems)


def _legacy_unambiguous(known: set[str], legacy: str) -> bool:
    """True when no longer stem shares ``legacy`` as a prefix."""
    return not any(
        stem != legacy and stem.startswith(legacy) for stem in known)


def iter_journal_session_ids(ledger_dir: str) -> list[str]:
    """Full session ids in first-checkpoint order. Bad lines are skipped."""
    order: list[str] = []
    seen: set[str] = set()
    path = os.path.join(ledger_dir, "checkpoints.jsonl")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = str(row.get("session", "") or "")
                if sid and sid not in seen:
                    seen.add(sid)
                    order.append(sid)
    except OSError:
        return []
    return order


def last_live_session_id(ledger_dir: str) -> str:
    """Full id of the last non-archive journal row, else the last row."""
    sid = ""
    sid_any = ""
    path = os.path.join(ledger_dir, "checkpoints.jsonl")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid_any = str(row.get("session", "") or "")
                if not row.get("archive"):
                    sid = sid_any
    except OSError:
        return ""
    return sid or sid_any


def stem_on_disk(ledger_dir: str, session_id: str) -> str:
    """Stem of the ctx file for ``session_id``.

    Prefer the collision-free file when it exists. Otherwise the legacy
    8-character file. Otherwise the collision-free stem (the name a new
    write would use).
    """
    try:
        stem = ledger_stem(session_id)
    except UnsafeSessionId:
        stem = ""
    if stem and os.path.isfile(ctx_path(ledger_dir, stem)):
        return stem
    legacy = legacy_stem(session_id)
    if legacy and os.path.isfile(ctx_path(ledger_dir, legacy)):
        return legacy
    return stem or legacy or "unknown"


def write_stem(ledger_dir: str, session_id: str) -> str:
    """Stem to write for ``session_id``.

    A fresh session gets :func:`ledger_stem`. Re-checkpoint of a session
    that already has only the legacy 8-character file updates that file
    in place, so the old ledger is not forked into a second copy. A
    legacy file shared with another session is left alone.
    """
    stem = ledger_stem(session_id)
    if os.path.isfile(ctx_path(ledger_dir, stem)):
        return stem
    legacy = legacy_stem(session_id)
    if not legacy or legacy == stem:
        return stem
    if not os.path.isfile(ctx_path(ledger_dir, legacy)):
        return stem
    known = set(list_session_stems(ledger_dir))
    if not _legacy_unambiguous(known, legacy):
        return stem
    owners = {
        full for full in iter_journal_session_ids(ledger_dir)
        if legacy_stem(full) == legacy
    }
    if owners and owners != {session_id}:
        return stem
    return legacy


def existing_ctx_path(ledger_dir: str, session_id: str) -> str:
    """Path of the ctx file when one is already on disk, else ``""``."""
    try:
        stem = stem_on_disk(ledger_dir, session_id)
    except UnsafeSessionId:
        return ""
    path = ctx_path(ledger_dir, stem)
    return path if os.path.isfile(path) else ""


def resolve_explicit(ledger_dir: str, session_id: str) -> tuple[str, str]:
    """``(stem, path)`` for an explicit session id. The file may be absent."""
    known = set(list_session_stems(ledger_dir))
    try:
        stem = ledger_stem(session_id)
    except UnsafeSessionId:
        stem = ""
    if stem and stem in known:
        return stem, ctx_path(ledger_dir, stem)
    legacy = legacy_stem(session_id)
    if (legacy and legacy in known
            and _legacy_unambiguous(known, legacy)):
        return legacy, ctx_path(ledger_dir, legacy)
    if session_id:
        matches = sorted(
            s for s in known
            if s == session_id or s.startswith(session_id))
        if len(matches) == 1:
            return matches[0], ctx_path(ledger_dir, matches[0])
    if stem:
        return stem, ctx_path(ledger_dir, stem)
    return "", ""


def matching_stems(stems: list[str], needle: str) -> list[str]:
    """Stems named by ``needle``: exact match, else a unique prefix.

    An ambiguous prefix matches nothing, so one 8-character query cannot
    hide two sessions that share it.
    """
    if not needle:
        return []
    exact = [stem for stem in stems if stem == needle]
    if exact:
        return exact
    prefixed = [
        stem for stem in stems
        if stem.startswith(needle) or needle.startswith(stem)
    ]
    if len(prefixed) == 1:
        return prefixed
    return []


def journal_session_order(ledger_dir: str) -> list[str]:
    """On-disk stems in first-checkpoint order.

    The journal stores the full session id. Each id is mapped to the
    file that actually exists (collision-free stem, else legacy 8-char).
    """
    order: list[str] = []
    seen: set[str] = set()
    for full in iter_journal_session_ids(ledger_dir):
        stem = stem_on_disk(ledger_dir, full)
        if stem and stem not in seen:
            seen.add(stem)
            order.append(stem)
    return order


def atomic_write_text(path: str, text: str) -> None:
    """Write ``text`` via a temp file in the same directory, then replace.

    ``newline="\\n"`` so the bytes do not depend on the platform. A crash
    before :func:`os.replace` leaves the previous file intact.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ctxpack-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def note_corrupt_ledger(path: str, exc: BaseException) -> dict[str, str]:
    """Record one unreadable ledger. The message names the basename only.

    ``ParseError`` is reported as ``parse_error``. Every other exception
    goes through :func:`classify_exception`, so a caller-minted class name
    cannot reach stderr.
    """
    if isinstance(exc, ParseError):
        reason = "parse_error"
    else:
        reason = classify_exception(exc)
    name = os.path.basename(path) or path
    print(
        f"ctxpack: corrupt ledger {name} ({reason}) — skipped; "
        f"other sessions remain readable",
        file=sys.stderr,
    )
    return {"kind": "corrupt_ledger", "path": name, "reason": reason}


def read_session_document(path: str) -> tuple[Optional[CTXDocument], Optional[dict]]:
    """Parse one session ledger. A bad file yields ``(None, diagnostic)``."""
    from ..core.parser import parse

    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        return parse(text, level=2, filename=os.path.basename(path)), None
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        return None, note_corrupt_ledger(path, exc)


# ── Section accessors (shared by brief, checkpoint, lint, session_reader) ──


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
    match = _TURN_IN_SRC_RE.search("\n".join(serialize_section(section)))
    return int(match.group(1)) if match else -1


def _sections(doc: CTXDocument) -> list[Section]:
    return [elem for elem in doc.body if isinstance(elem, Section)]
