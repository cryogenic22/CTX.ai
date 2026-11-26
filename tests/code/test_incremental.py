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

    def test_incremental_skips_parsing_unchanged_files(self, tmp_path: Path, monkeypatch):
        """A no-change re-pack must not parse. Wall-clock comparisons of
        a 30-file tree are noise on a fast runner (macOS py3.10 measured
        full 9ms, incremental 13ms).
        """
        import ctxpack.core.code.pack as pack_mod

        calls = {"n": 0}
        real = pack_mod.parse_python

        def counting(path):
            calls["n"] += 1
            return real(path)

        monkeypatch.setattr(pack_mod, "parse_python", counting)
        for i in range(30):
            (tmp_path / f"m_{i}.py").write_text(
                f"def fn_{i}(x: int) -> int:\n    return x + {i}\n"
            )
        p1 = pack_mod.pack_codebase(tmp_path)
        assert calls["n"] == 30

        calls["n"] = 0
        p2 = pack_mod.pack_codebase(tmp_path, prior=p1)
        assert calls["n"] == 0
        assert p1.version == p2.version
