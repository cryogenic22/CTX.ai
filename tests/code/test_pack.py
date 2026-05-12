"""High-level Pack pipeline + MCP-shaped helpers."""

from __future__ import annotations

from pathlib import Path

import pytest


_FIXTURES_ROOT = Path(__file__).parent / "fixtures"


class TestPackCodebase:
    def test_packs_fastapi_min(self):
        from ctxpack.core.code.pack import pack_codebase
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        # 3 files (no fixture init in this dir)
        assert len(pack.files) >= 3
        # At least the obvious symbols are emitted
        names = {e.name for e in pack.entities}
        assert any(n.endswith("::read_user") for n in names)
        assert any(n.endswith("::create_user") for n in names)
        assert any(n.endswith("::User") for n in names)
        assert any(n.endswith("::get_db") for n in names)
        # Pack version is a sha256 hex string
        assert len(pack.version) == 64

    def test_pack_warnings_collected(self, tmp_path: Path):
        from ctxpack.core.code.pack import pack_codebase
        (tmp_path / "good.py").write_text("def foo():\n    return 1\n")
        (tmp_path / "broken.py").write_text("def broken(\n    pass\n")
        pack = pack_codebase(tmp_path)
        # broken.py triggers a parse warning, not a crash
        assert any(w.file.endswith("broken.py") for w in pack.warnings)
        # good.py's symbol is still present
        assert any(e.name.endswith("::foo") for e in pack.entities)

    def test_pack_excludes_pycache(self, tmp_path: Path):
        from ctxpack.core.code.pack import pack_codebase
        (tmp_path / "main.py").write_text("def x(): pass\n")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "x.cpython-313.pyc").write_text("")
        pack = pack_codebase(tmp_path)
        assert "main.py" in pack.files
        assert all("__pycache__" not in f for f in pack.files)


class TestVersion:
    def test_version_is_stable_across_runs(self):
        from ctxpack.core.code.pack import pack_codebase
        a = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        b = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        assert a.version == b.version

    def test_version_changes_when_content_changes(self, tmp_path: Path):
        from ctxpack.core.code.pack import pack_codebase
        (tmp_path / "x.py").write_text("def a(): pass\n")
        v1 = pack_codebase(tmp_path).version
        (tmp_path / "x.py").write_text("def a():\n    return 2\n")
        v2 = pack_codebase(tmp_path).version
        assert v1 != v2

    def test_version_probe(self):
        from ctxpack.core.code.pack import pack_codebase, pack_version
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = pack_version(pack)
        assert result["pack_version"] == pack.version
        assert result["entities"] == len(pack.entities)
        assert result["files"] == len(pack.files)


class TestListSymbols:
    def test_returns_module_symbols(self):
        from ctxpack.core.code.pack import pack_codebase, list_symbols
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = list_symbols(pack, "app.py")
        assert "error" not in result
        names = {s["name"] for s in result["symbols"]}
        assert any(n.endswith("::read_user") for n in names)
        assert result["pack_version"] == pack.version

    def test_unknown_module_returns_error(self):
        from ctxpack.core.code.pack import pack_codebase, list_symbols
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = list_symbols(pack, "nonexistent.py")
        assert result["error"]["code"] == "unknown_module"

    def test_invalid_k_returns_error(self):
        from ctxpack.core.code.pack import pack_codebase, list_symbols
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = list_symbols(pack, "app.py", k=0)
        assert result["error"]["code"] == "invalid_input"

    def test_k_truncates(self):
        from ctxpack.core.code.pack import pack_codebase, list_symbols
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = list_symbols(pack, "app.py", k=1)
        assert len(result["symbols"]) == 1


class TestHydrateSymbol:
    def test_returns_fields(self):
        from ctxpack.core.code.pack import pack_codebase, hydrate_symbol
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        ent = next(e for e in pack.entities if e.name.endswith("::read_user"))
        result = hydrate_symbol(pack, ent.name)
        assert "error" not in result
        assert "signature" in result["fields"]
        assert "body" in result["fields"]
        assert result["fields"]["http_method"] == "GET"

    def test_unknown_symbol_returns_error(self):
        from ctxpack.core.code.pack import pack_codebase, hydrate_symbol
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = hydrate_symbol(pack, "nonexistent::sym")
        assert result["error"]["code"] == "unknown_symbol"

    def test_invalid_depth(self):
        from ctxpack.core.code.pack import pack_codebase, hydrate_symbol
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        ent = next(iter(pack.entities))
        assert hydrate_symbol(pack, ent.name, depth=5)["error"]["code"] == "invalid_input"

    def test_depth_one_returns_neighbours_key(self):
        from ctxpack.core.code.pack import pack_codebase, hydrate_symbol
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        ent = next(e for e in pack.entities if e.name.endswith("::read_user"))
        result = hydrate_symbol(pack, ent.name, depth=1)
        assert "neighbours" in result
        assert "callers" in result["neighbours"]
        assert "callees" in result["neighbours"]


class TestSearchSymbols:
    def test_finds_by_name_substring(self):
        from ctxpack.core.code.pack import pack_codebase, search_symbols
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = search_symbols(pack, "user")
        assert "error" not in result
        names = {s["name"] for s in result["symbols"]}
        assert any("read_user" in n for n in names)
        assert any("create_user" in n for n in names)

    def test_empty_query_errors(self):
        from ctxpack.core.code.pack import pack_codebase, search_symbols
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = search_symbols(pack, "   ")
        assert result["error"]["code"] == "invalid_input"

    def test_no_match_returns_empty_not_error(self):
        from ctxpack.core.code.pack import pack_codebase, search_symbols
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = search_symbols(pack, "nothingmatchesthis")
        assert "error" not in result
        assert result["symbols"] == []


class TestRawFile:
    def test_returns_content(self):
        from ctxpack.core.code.pack import pack_codebase, raw_file
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = raw_file(pack, "deps.py")
        assert "error" not in result
        assert "def get_db" in result["content"]

    def test_path_traversal_blocked(self):
        from ctxpack.core.code.pack import pack_codebase, raw_file
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = raw_file(pack, "../../etc/passwd")
        assert result["error"]["code"] == "path_outside_root"

    def test_missing_file_returns_error(self):
        from ctxpack.core.code.pack import pack_codebase, raw_file
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        result = raw_file(pack, "nonexistent.py")
        assert "error" in result


class TestManifest:
    def test_manifest_includes_pack_version(self):
        from ctxpack.core.code.pack import pack_codebase, render_manifest
        pack = pack_codebase(_FIXTURES_ROOT / "py_fastapi_min")
        m = render_manifest(pack)
        assert m["pack_version"] == pack.version
        assert m["served"]["files"] == len(pack.files)
        assert "escape_hatch" in m
