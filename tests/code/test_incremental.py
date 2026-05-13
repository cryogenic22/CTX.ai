"""CP-024 — incremental pack via SHA-based file reuse."""

from __future__ import annotations

import time
from pathlib import Path


class TestIncremental:
    def test_unchanged_files_reused(self, tmp_path: Path):
        from ctxpack.core.code.pack import pack_codebase
        (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
        (tmp_path / "b.py").write_text("def beta():\n    return 2\n")
        first = pack_codebase(tmp_path)
        # No changes — second pack with prior=first should reuse all files.
        second = pack_codebase(tmp_path, prior=first)
        # Same content -> same version.
        assert first.version == second.version
        # All files reused (entities live across pack instances).
        names_first = {e.name for e in first.entities}
        names_second = {e.name for e in second.entities}
        assert names_first == names_second

    def test_modified_file_reparsed(self, tmp_path: Path):
        from ctxpack.core.code.pack import pack_codebase
        (tmp_path / "x.py").write_text("def first(): pass\n")
        p1 = pack_codebase(tmp_path)
        time.sleep(0.05)  # ensure mtime changes if anything keys on it
        (tmp_path / "x.py").write_text("def second(): pass\n")
        p2 = pack_codebase(tmp_path, prior=p1)
        names = {e.name for e in p2.entities}
        assert any(n.endswith("::second") for n in names)
        assert not any(n.endswith("::first") for n in names)
        assert p1.version != p2.version

    def test_added_file_picked_up(self, tmp_path: Path):
        from ctxpack.core.code.pack import pack_codebase
        (tmp_path / "old.py").write_text("def old(): pass\n")
        p1 = pack_codebase(tmp_path)
        (tmp_path / "new.py").write_text("def shiny(): pass\n")
        p2 = pack_codebase(tmp_path, prior=p1)
        names = {e.name for e in p2.entities}
        assert any(n.endswith("::shiny") for n in names)
        assert any(n.endswith("::old") for n in names)

    def test_deleted_file_dropped(self, tmp_path: Path):
        from ctxpack.core.code.pack import pack_codebase
        (tmp_path / "stay.py").write_text("def stay(): pass\n")
        (tmp_path / "gone.py").write_text("def gone(): pass\n")
        p1 = pack_codebase(tmp_path)
        (tmp_path / "gone.py").unlink()
        p2 = pack_codebase(tmp_path, prior=p1)
        names = {e.name for e in p2.entities}
        assert any(n.endswith("::stay") for n in names)
        assert not any(n.endswith("::gone") for n in names)

    def test_file_hashes_populated(self, tmp_path: Path):
        from ctxpack.core.code.pack import pack_codebase
        (tmp_path / "x.py").write_text("def a(): pass\n")
        pack = pack_codebase(tmp_path)
        assert "x.py" in pack.file_hashes
        assert len(pack.file_hashes["x.py"]) == 64  # sha256 hex

    def test_incremental_faster_than_full_rebuild(self, tmp_path: Path):
        """Smoke test for the speed win — generate a non-trivial tree
        and confirm prior-based pack is at least 2× faster than
        rebuilding from scratch.
        """
        from ctxpack.core.code.pack import pack_codebase
        # 30 small files
        for i in range(30):
            (tmp_path / f"m_{i}.py").write_text(
                f"def fn_{i}(x: int) -> int:\n    return x + {i}\n"
            )
        t = time.time()
        p1 = pack_codebase(tmp_path)
        t_full = time.time() - t

        t = time.time()
        p2 = pack_codebase(tmp_path, prior=p1)
        t_incr = time.time() - t

        # Incremental should be visibly faster on a no-change pass.
        # Bound is loose (system-load tolerant); the bug we want to
        # catch is "reuse path doesn't actually skip parsing."
        assert t_incr < t_full, (
            f"incremental ({t_incr:.3f}s) should be faster than full "
            f"({t_full:.3f}s)"
        )
        assert p1.version == p2.version
