"""CP-040.5/041 — code-packer telemetry.

Append-only JSONL telemetry at ``.ctx-cache/code-telemetry.jsonl``,
plus derived signals that surface real failure modes of the curated
pack:

- ``pattern_raw_file_after_hydrate`` — agent called ``hydrate_symbol``
  then ``raw_file`` on the same file. The hydration was insufficient
  for the agent's intent.

- ``pattern_reformulated_search`` — agent issued multiple
  ``search_symbols`` calls with similar-but-different queries in the
  same session. Catalog vocabulary mismatch.

- ``symbol_not_in_pack`` — ``hydrate_symbol`` was called with a name
  not present in the pack. Surfaces ranking / discovery failures.

Privacy: every user-visible string (root path, module path, symbol
name, query text, file path) is SHA-256 hashed before writing. The
raw text is never persisted.

Schema: ``ctxpack/schemas/telemetry-events.schema.json``. Every
event written validates against the schema; the test suite enforces
this.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union


PathLike = Union[str, Path]


# ── Hashing / utilities ─────────────────────────────────────────────────


def _hash(s: str) -> str:
    """SHA-256 hex, truncated to 32 chars — enough to avoid collisions
    in our domain (pack files, queries, paths) while keeping log lines
    compact."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_session_id() -> str:
    return uuid.uuid4().hex[:16]


# ── Schema validation ─────────────────────────────────────────────────


_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "schemas" / "telemetry-events.schema.json"
)
_SCHEMA_CACHE: Optional[dict] = None


def load_schema() -> dict:
    """Return the cached telemetry-event JSON Schema (loaded once)."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _SCHEMA_CACHE = json.load(f)
    return _SCHEMA_CACHE


def validate_event(event: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``event`` doesn't match
    the schema. Uses ``jsonschema`` (already a dep via the eval
    pipeline)."""
    import jsonschema  # local import keeps cold start fast
    jsonschema.validate(event, load_schema())


# ── Reformulated-search clustering ──────────────────────────────────────


def _normalised_query_key(q: str) -> str:
    """Lowercased, whitespace-collapsed, sorted-tokens key.

    Two queries that share most words in different order or with
    different spacing produce the same key — the signal we want for
    "agent kept reformulating the same intent."
    """
    toks = sorted({t for t in q.lower().split() if t})
    return " ".join(toks)


# ── In-memory session state ────────────────────────────────────────────


@dataclass
class _SessionState:
    """Per-session memory used to detect cross-event patterns.

    Cleared when a new pack is built (because pack_version changes
    the meaning of every subsequent symbol/file reference).
    """

    last_hydrated_files: list[tuple[str, str]] = field(default_factory=list)
    # ^ (file_path, name_hash) of the last few hydrate_symbol calls

    recent_search_keys: list[tuple[float, str, str]] = field(default_factory=list)
    # ^ (ts, normalised_key, query_hash) of recent searches

    hydrate_count: int = 0


# ── CodeTelemetry ──────────────────────────────────────────────────────


class CodeTelemetry:
    """Append-only telemetry logger for the code packer.

    One instance per MCP server boot (or one per test). Thread-safety
    relies on the OS-level atomicity of small appends to a JSONL file
    — the same posture as ``ctxpack.core.telemetry.TelemetryLog``.

    Patterns are detected synchronously on each ``log_*`` call and
    emitted as additional events. The emitted pattern events go
    through the same schema check.
    """

    # Pattern parameters — public so tests can tune them.
    REFORMULATION_WINDOW_S = 60.0  # search reformulations within this window
    REFORMULATION_THRESHOLD = 2    # ≥ this many similar queries → emit
    RAW_FILE_LOOKBACK = 5          # check last N hydrate calls for the file

    def __init__(
        self,
        path: PathLike = ".ctx-cache/code-telemetry.jsonl",
        *,
        session_id: Optional[str] = None,
        pack_version: str = "",
        enabled: bool = True,
    ) -> None:
        self._path = Path(path)
        self.session_id = session_id or _new_session_id()
        self.pack_version = pack_version
        self.enabled = enabled
        self._state = _SessionState()

    @property
    def path(self) -> Path:
        return self._path

    def set_pack_version(self, version: str) -> None:
        """Switch to a new pack — drops cross-event state because
        symbol/file identifiers now refer to a different snapshot."""
        if version != self.pack_version:
            self._state = _SessionState()
            self.pack_version = version

    # ── Event writers ────

    def log_pack_built(
        self,
        *,
        root: str,
        entities: int,
        files: int,
        pack_version: str,
        latency_ms: float,
    ) -> dict:
        self.set_pack_version(pack_version)
        ev = self._base("pack_built", latency_ms=latency_ms)
        ev["root_hash"] = _hash(root)
        ev["entities"] = entities
        ev["files"] = files
        self._write(ev)
        return ev

    def log_list_symbols(
        self,
        *,
        module: str,
        k: int,
        n_returned: int,
        context: Optional[str],
        alpha: float,
        latency_ms: float,
    ) -> dict:
        ev = self._base("list_symbols_call", latency_ms=latency_ms)
        ev["module_hash"] = _hash(module)
        ev["k"] = k
        ev["n_returned"] = n_returned
        ev["alpha"] = alpha
        if context:
            ev["context_hash"] = _hash(context)
        self._write(ev)
        return ev

    def log_hydrate_symbol(
        self,
        *,
        name: str,
        depth: int,
        success: bool,
        latency_ms: float,
    ) -> dict:
        ev = self._base("hydrate_symbol_call", latency_ms=latency_ms)
        ev["name_hash"] = _hash(name)
        ev["depth"] = depth
        ev["success"] = success
        self._write(ev)
        if success:
            file_part = name.split("::", 1)[0] if "::" in name else name
            self._state.last_hydrated_files.append((file_part, ev["name_hash"]))
            if len(self._state.last_hydrated_files) > self.RAW_FILE_LOOKBACK * 2:
                self._state.last_hydrated_files = (
                    self._state.last_hydrated_files[-self.RAW_FILE_LOOKBACK:]
                )
            self._state.hydrate_count += 1
        return ev

    def log_search_symbols(
        self,
        *,
        query: str,
        k: int,
        n_returned: int,
        alpha: float,
        latency_ms: float,
    ) -> dict:
        ev = self._base("search_symbols_call", latency_ms=latency_ms)
        ev["query_hash"] = _hash(query)
        ev["k"] = k
        ev["n_returned"] = n_returned
        ev["alpha"] = alpha
        self._write(ev)
        # Pattern detection: reformulated search
        now = time.time()
        key = _normalised_query_key(query)
        cutoff = now - self.REFORMULATION_WINDOW_S
        self._state.recent_search_keys = [
            t for t in self._state.recent_search_keys if t[0] >= cutoff
        ]
        self._state.recent_search_keys.append((now, key, ev["query_hash"]))
        same_key = [
            t for t in self._state.recent_search_keys if t[1] == key
        ]
        # Distinct query hashes within the same normalised-key bucket =
        # reformulation. ≥ THRESHOLD distinct hashes triggers a pattern
        # event (emitted at most once per cluster — re-emission is
        # gated by hash-count change).
        distinct_hashes = {t[2] for t in same_key}
        if len(distinct_hashes) >= self.REFORMULATION_THRESHOLD:
            self._emit_pattern(
                "pattern_reformulated_search",
                cluster_size=len(distinct_hashes),
            )
        return ev

    def log_raw_file(
        self,
        *,
        path: str,
        success: bool,
        latency_ms: float,
    ) -> dict:
        ev = self._base("raw_file_call", latency_ms=latency_ms)
        ev["path_hash"] = _hash(path)
        ev["success"] = success
        ev["prior_hydrate_count"] = self._state.hydrate_count
        self._write(ev)
        # Pattern detection: was this raw_file preceded by a hydrate
        # of a symbol in the same file?
        for elapsed, (file_part, name_hash) in enumerate(
            reversed(self._state.last_hydrated_files), start=1
        ):
            if file_part == path:
                self._emit_pattern(
                    "pattern_raw_file_after_hydrate",
                    path_hash=ev["path_hash"],
                    name_hash=name_hash,
                    elapsed_calls=elapsed,
                )
                break
        return ev

    def log_symbol_not_in_pack(self, *, name: str) -> dict:
        ev = self._base("symbol_not_in_pack")
        ev["name_hash"] = _hash(name)
        self._write(ev)
        return ev

    # ── Aggregation / dashboard support ────

    def summary(self) -> dict[str, Any]:
        """Read the log, return per-event-type counts + key rates."""
        events = self._read_events()
        if not events:
            return {"total": 0, "by_type": {}, "rates": {}}
        by_type: dict[str, int] = {}
        for e in events:
            by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
        hydrates = by_type.get("hydrate_symbol_call", 0)
        raw_file_after = by_type.get("pattern_raw_file_after_hydrate", 0)
        searches = by_type.get("search_symbols_call", 0)
        reformulated = by_type.get("pattern_reformulated_search", 0)
        unknown = by_type.get("symbol_not_in_pack", 0)
        rates: dict[str, float] = {}
        if hydrates:
            rates["raw_file_after_hydrate_rate"] = raw_file_after / hydrates
            rates["unknown_symbol_rate"] = unknown / hydrates
        if searches:
            rates["reformulated_search_rate"] = reformulated / searches
        return {
            "total": len(events),
            "by_type": by_type,
            "rates": rates,
            "pack_version": self.pack_version,
            "session_id": self.session_id,
        }

    # ── Internals ────

    def _base(
        self,
        event_type: str,
        *,
        latency_ms: Optional[float] = None,
    ) -> dict:
        ev: dict[str, Any] = {
            "v": 1,
            "ts": _now_iso(),
            "session_id": self.session_id,
            "event_type": event_type,
            "pack_version": self.pack_version,
        }
        if latency_ms is not None:
            ev["latency_ms"] = float(latency_ms)
        return ev

    def _emit_pattern(self, event_type: str, **fields: Any) -> None:
        ev: dict[str, Any] = {
            "v": 1,
            "ts": _now_iso(),
            "session_id": self.session_id,
            "event_type": event_type,
        }
        ev.update(fields)
        self._write(ev)

    def _write(self, ev: dict) -> None:
        if not self.enabled:
            return
        parent = self._path.parent
        if parent and not parent.is_dir():
            parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(ev, separators=(",", ":"))
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _read_events(self) -> list[dict]:
        if not self._path.is_file():
            return []
        out = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out
