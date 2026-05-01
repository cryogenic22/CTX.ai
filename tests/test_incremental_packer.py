"""Phase 3b — IncrementalPacker.

File-hash cache backed by SQLite. Classifies a list of source files
into ``unchanged | modified | new | deleted`` so a downstream pack can
skip work on the unchanged set. Pure stdlib (sqlite3 + hashlib).

The compile-side merge — taking ``unchanged`` IR from a prior pack and
combining with newly-parsed IR — is intentionally out of scope here.
This layer just provides the change set.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from ctxpack.core.incremental import ChangeSet, IncrementalPacker


# ── Fixtures ────────────────────────────────────────────────────────────


def _write(p: Path, content: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def packer(tmp_path: Path) -> IncrementalPacker:
    return IncrementalPacker(cache_path=tmp_path / "cache.db")


# ── Construction ────────────────────────────────────────────────────────


class TestConstruction:
    def test_creates_cache_db_lazily(self, tmp_path: Path):
        # The DB file shouldn't exist until first write.
        cache_path = tmp_path / "nested" / "state.db"
        p = IncrementalPacker(cache_path=cache_path)
        assert not cache_path.exists()
        # Trigger creation by classifying nothing.
        p.classify([])
        assert cache_path.exists()

    def test_creates_parent_dir(self, tmp_path: Path):
        cache_path = tmp_path / "deeply" / "nested" / "state.db"
        p = IncrementalPacker(cache_path=cache_path)
        p.classify([])
        assert cache_path.parent.is_dir()


# ── First-time classification ───────────────────────────────────────────


class TestFirstRun:
    def test_unknown_file_is_new(self, packer: IncrementalPacker, tmp_path: Path):
        f = _write(tmp_path / "rules.md", "## ENTITY-A\nstatus: active\n")
        cs = packer.classify([f])
        assert cs.new == [str(f)]
        assert cs.modified == []
        assert cs.unchanged == []
        assert cs.deleted == []

    def test_multiple_new_files(self, packer: IncrementalPacker, tmp_path: Path):
        f1 = _write(tmp_path / "a.md", "a")
        f2 = _write(tmp_path / "b.md", "b")
        cs = packer.classify([f1, f2])
        assert sorted(cs.new) == sorted([str(f1), str(f2)])


# ── After mark_packed ───────────────────────────────────────────────────


class TestUnchanged:
    def test_marked_file_classifies_unchanged(
        self, packer: IncrementalPacker, tmp_path: Path
    ):
        f = _write(tmp_path / "a.md", "stable")
        packer.classify([f])
        packer.mark_packed([f])
        cs = packer.classify([f])
        assert cs.unchanged == [str(f)]
        assert cs.new == []
        assert cs.modified == []

    def test_unchanged_when_mtime_changes_but_content_same(
        self, packer: IncrementalPacker, tmp_path: Path
    ):
        # Re-touching a file (e.g. via build tools) should NOT cause re-pack
        # if the SHA-256 is identical. mtime is just a fast-path hint.
        f = _write(tmp_path / "a.md", "stable content")
        packer.classify([f])
        packer.mark_packed([f])
        # Bump mtime but keep content
        new_mtime = time.time() + 100
        import os
        os.utime(f, (new_mtime, new_mtime))
        cs = packer.classify([f])
        assert cs.unchanged == [str(f)]


# ── Modified files ──────────────────────────────────────────────────────


class TestModified:
    def test_content_change_detected(
        self, packer: IncrementalPacker, tmp_path: Path
    ):
        f = _write(tmp_path / "a.md", "v1")
        packer.classify([f])
        packer.mark_packed([f])
        f.write_text("v2", encoding="utf-8")
        cs = packer.classify([f])
        assert cs.modified == [str(f)]
        assert cs.unchanged == []

    def test_whitespace_change_is_a_change(
        self, packer: IncrementalPacker, tmp_path: Path
    ):
        f = _write(tmp_path / "a.md", "x")
        packer.classify([f])
        packer.mark_packed([f])
        f.write_text("x ", encoding="utf-8")  # trailing space
        cs = packer.classify([f])
        assert cs.modified == [str(f)]


# ── Deleted files ───────────────────────────────────────────────────────


class TestDeleted:
    def test_file_removed_from_caller_set_is_deleted(
        self, packer: IncrementalPacker, tmp_path: Path
    ):
        f1 = _write(tmp_path / "a.md", "a")
        f2 = _write(tmp_path / "b.md", "b")
        packer.classify([f1, f2])
        packer.mark_packed([f1, f2])

        # Caller now passes only f1 — f2 disappeared from the corpus.
        cs = packer.classify([f1])
        assert cs.unchanged == [str(f1)]
        assert cs.deleted == [str(f2)]

    def test_mark_packed_does_not_resurrect_deleted(
        self, packer: IncrementalPacker, tmp_path: Path
    ):
        f1 = _write(tmp_path / "a.md", "a")
        f2 = _write(tmp_path / "b.md", "b")
        packer.classify([f1, f2])
        packer.mark_packed([f1, f2])

        # First reclassify drops f2 from the cache.
        cs1 = packer.classify([f1])
        assert str(f2) in cs1.deleted

        # Second reclassify with only f1 must not list f2 again — once
        # deleted, it stays deleted unless explicitly re-packed.
        cs2 = packer.classify([f1])
        assert cs2.deleted == []
        assert cs2.unchanged == [str(f1)]


# ── Persistence across instances ────────────────────────────────────────


class TestPersistence:
    def test_state_survives_restart(self, tmp_path: Path):
        cache = tmp_path / "cache.db"
        f = _write(tmp_path / "a.md", "stable")

        p1 = IncrementalPacker(cache_path=cache)
        p1.classify([f])
        p1.mark_packed([f])

        p2 = IncrementalPacker(cache_path=cache)
        cs = p2.classify([f])
        assert cs.unchanged == [str(f)]

    def test_clear_wipes_cache(self, packer: IncrementalPacker, tmp_path: Path):
        f = _write(tmp_path / "a.md", "x")
        packer.classify([f])
        packer.mark_packed([f])
        packer.clear()
        cs = packer.classify([f])
        assert cs.new == [str(f)]
        assert cs.unchanged == []


# ── Stats ───────────────────────────────────────────────────────────────


class TestChangeSetStats:
    def test_changeset_has_total_and_skip_count(
        self, packer: IncrementalPacker, tmp_path: Path
    ):
        f1 = _write(tmp_path / "a.md", "a")
        f2 = _write(tmp_path / "b.md", "b")
        packer.classify([f1, f2])
        packer.mark_packed([f1, f2])
        f1.write_text("a-modified", encoding="utf-8")

        cs = packer.classify([f1, f2])
        assert cs.total == 2
        assert cs.skip_count == 1  # f2 unchanged
        assert cs.work_count == 1  # f1 modified

    def test_empty_changeset_stats(self):
        cs = ChangeSet()
        assert cs.total == 0
        assert cs.skip_count == 0
        assert cs.work_count == 0

    def test_skip_ratio(self, packer: IncrementalPacker, tmp_path: Path):
        files = [
            _write(tmp_path / f"f{i}.md", f"content-{i}") for i in range(10)
        ]
        packer.classify(files)
        packer.mark_packed(files)
        # Modify only 2 of 10
        files[0].write_text("changed-0", encoding="utf-8")
        files[1].write_text("changed-1", encoding="utf-8")
        cs = packer.classify(files)
        assert cs.skip_count == 8
        assert cs.work_count == 2
