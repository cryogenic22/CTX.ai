"""IncrementalPacker — file-level change detection for fast re-packs.

A pack run today re-parses every YAML / Markdown / JSON / TOML / CSV file
in the corpus regardless of whether it changed since the last run. On
small corpora that is fine; on the kinds of corpora the AMBIENT layer
expects (live state pulled at hydrate time) it is not.

This module provides the cache layer only — callers decide what to do
with the change set:

    packer = IncrementalPacker(cache_path=".ctx-cache/state.db")
    cs = packer.classify(corpus_files)
    # cs.unchanged → re-use prior IR
    # cs.modified  → re-parse
    # cs.new       → parse fresh
    # cs.deleted   → drop from prior IR
    ...do the actual work...
    packer.mark_packed(cs.new + cs.modified)

The merge step — combining cached IR for unchanged files with newly
parsed IR for changed files — is intentionally out of scope. It belongs
in the compressor and is more invasive.

State is stored in a SQLite DB (one row per file). Pure stdlib; no
external dependencies.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence, Union

PathLike = Union[str, Path]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_state (
    rel_path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    mtime REAL NOT NULL,
    last_packed_at REAL NOT NULL
)
"""

_BUFFER_SIZE = 65536  # 64K read buffer for SHA-256


# ── Change set ──────────────────────────────────────────────────────────


@dataclass
class ChangeSet:
    """Result of classifying a list of files against the cache."""

    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Number of files the caller asked us to classify."""
        return len(self.new) + len(self.modified) + len(self.unchanged)

    @property
    def skip_count(self) -> int:
        """Files that don't need re-parsing."""
        return len(self.unchanged)

    @property
    def work_count(self) -> int:
        """Files that need to be parsed (new + modified)."""
        return len(self.new) + len(self.modified)


# ── Packer ──────────────────────────────────────────────────────────────


class IncrementalPacker:
    """SQLite-backed file-state cache.

    Not thread-safe. Callers are expected to use one instance per
    process; concurrent writers to the same cache file will not corrupt
    SQLite but may produce stale classifications.
    """

    def __init__(self, *, cache_path: PathLike) -> None:
        self.cache_path = Path(cache_path)
        self._conn: sqlite3.Connection | None = None

    # ── Connection helpers ────

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # ``isolation_level=None`` so we manage transactions explicitly
        # via ``with conn:``. Faster on bursty writes.
        conn = sqlite3.connect(str(self.cache_path), isolation_level=None)
        conn.execute(_SCHEMA)
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Classification ────

    def classify(self, files: Sequence[PathLike]) -> ChangeSet:
        """Bucket each file by whether the cache has seen it before."""
        conn = self._connect()
        cs = ChangeSet()
        seen_paths: set[str] = set()

        # Snapshot what the cache currently knows.
        cached = {
            row[0]: (row[1], row[2])  # rel_path → (sha256, mtime)
            for row in conn.execute("SELECT rel_path, sha256, mtime FROM file_state")
        }

        for f in files:
            path = str(f)
            seen_paths.add(path)
            cur_mtime = os.path.getmtime(path)
            cached_entry = cached.get(path)

            if cached_entry is None:
                cs.new.append(path)
                continue

            cached_sha, cached_mtime = cached_entry
            # Fast path: mtime unchanged → assume content unchanged
            if cur_mtime == cached_mtime:
                cs.unchanged.append(path)
                continue

            # Slow path: mtime moved, hash to confirm
            cur_sha = _hash_file(path)
            if cur_sha == cached_sha:
                cs.unchanged.append(path)
            else:
                cs.modified.append(path)

        # Anything in cache that the caller didn't list is deleted.
        for path in cached:
            if path not in seen_paths:
                cs.deleted.append(path)

        # Drop deleted entries from the cache so they don't keep
        # appearing in future classifications.
        if cs.deleted:
            with conn:
                conn.executemany(
                    "DELETE FROM file_state WHERE rel_path = ?",
                    [(p,) for p in cs.deleted],
                )

        return cs

    # ── Recording a successful pack ────

    def mark_packed(self, files: Iterable[PathLike]) -> None:
        """Record that ``files`` have been packed at the current state."""
        conn = self._connect()
        now = time.time()
        rows = []
        for f in files:
            path = str(f)
            rows.append(
                (path, _hash_file(path), os.path.getmtime(path), now)
            )
        if not rows:
            return
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO file_state "
                "(rel_path, sha256, mtime, last_packed_at) VALUES (?, ?, ?, ?)",
                rows,
            )

    # ── Maintenance ────

    def clear(self) -> None:
        """Wipe the cache. Forces every file to classify as ``new``."""
        conn = self._connect()
        with conn:
            conn.execute("DELETE FROM file_state")


# ── SHA-256 helper ──────────────────────────────────────────────────────


def _hash_file(path: PathLike) -> str:
    """Stream a file through SHA-256 and return its hex digest."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_BUFFER_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
