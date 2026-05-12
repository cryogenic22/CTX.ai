"""CP-009 — file::dotted symbol naming + overload disambiguation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestQualifiedName:
    def test_top_level_function(self):
        from ctxpack.core.code.naming import qualified_name
        from ctxpack.core.code.symbols import Symbol, Kind
        s = Symbol(name="main", kind=Kind.FUNCTION,
                   line_start=1, line_end=1, byte_start=0, byte_end=1)
        assert qualified_name("src/foo.py", s) == "src/foo.py::main"

    def test_method(self):
        from ctxpack.core.code.naming import qualified_name
        from ctxpack.core.code.symbols import Symbol, Kind
        s = Symbol(name="Widget.tick", kind=Kind.METHOD,
                   line_start=1, line_end=1, byte_start=0, byte_end=1)
        assert qualified_name("src/foo.py", s) == "src/foo.py::Widget.tick"

    def test_windows_backslashes_normalised(self):
        from ctxpack.core.code.naming import qualified_name
        from ctxpack.core.code.symbols import Symbol, Kind
        s = Symbol(name="main", kind=Kind.FUNCTION,
                   line_start=1, line_end=1, byte_start=0, byte_end=1)
        assert qualified_name(r"src\foo.py", s) == "src/foo.py::main"

    def test_path_object_accepted(self):
        from ctxpack.core.code.naming import qualified_name
        from ctxpack.core.code.symbols import Symbol, Kind
        s = Symbol(name="x", kind=Kind.FUNCTION,
                   line_start=1, line_end=1, byte_start=0, byte_end=1)
        result = qualified_name(Path("src") / "foo.py", s)
        assert result == "src/foo.py::x"


class TestDisambiguation:
    def test_overloads_get_suffix_in_file_order(self):
        from ctxpack.core.code.naming import qualified_names_for_module
        from ctxpack.core.code.symbols import Symbol, Kind
        s1 = Symbol(name="foo", kind=Kind.FUNCTION,
                    line_start=1, line_end=1, byte_start=10, byte_end=20)
        s2 = Symbol(name="foo", kind=Kind.FUNCTION,
                    line_start=5, line_end=5, byte_start=30, byte_end=40)
        s3 = Symbol(name="foo", kind=Kind.FUNCTION,
                    line_start=9, line_end=9, byte_start=50, byte_end=60)
        pairs = qualified_names_for_module("a.py", [s1, s2, s3])
        names = [n for _, n in pairs]
        assert names == ["a.py::foo", "a.py::foo#1", "a.py::foo#2"]

    def test_no_collision_no_suffix(self):
        from ctxpack.core.code.naming import qualified_names_for_module
        from ctxpack.core.code.symbols import Symbol, Kind
        s1 = Symbol(name="alpha", kind=Kind.FUNCTION,
                    line_start=1, line_end=1, byte_start=0, byte_end=5)
        s2 = Symbol(name="beta", kind=Kind.FUNCTION,
                    line_start=3, line_end=3, byte_start=10, byte_end=15)
        pairs = qualified_names_for_module("a.py", [s1, s2])
        names = [n for _, n in pairs]
        assert names == ["a.py::alpha", "a.py::beta"]

    def test_different_scopes_no_collision(self):
        """`foo` and `Widget.foo` are different scopes — no suffix needed."""
        from ctxpack.core.code.naming import qualified_names_for_module
        from ctxpack.core.code.symbols import Symbol, Kind
        f = Symbol(name="foo", kind=Kind.FUNCTION,
                   line_start=1, line_end=1, byte_start=0, byte_end=5)
        m = Symbol(name="Widget.foo", kind=Kind.METHOD,
                   line_start=5, line_end=5, byte_start=20, byte_end=25)
        pairs = qualified_names_for_module("a.py", [f, m])
        names = [n for _, n in pairs]
        assert names == ["a.py::foo", "a.py::Widget.foo"]

    def test_suffix_starts_at_one(self):
        """Two identical names: the first is unsuffixed, the second gets #1.
        Confirms we don't start at #0 (which would be confusing) or #2."""
        from ctxpack.core.code.naming import qualified_names_for_module
        from ctxpack.core.code.symbols import Symbol, Kind
        a = Symbol(name="x", kind=Kind.FUNCTION,
                   line_start=1, line_end=1, byte_start=0, byte_end=5)
        b = Symbol(name="x", kind=Kind.FUNCTION,
                   line_start=2, line_end=2, byte_start=10, byte_end=15)
        pairs = qualified_names_for_module("a.py", [a, b])
        names = [n for _, n in pairs]
        assert names == ["a.py::x", "a.py::x#1"]


class TestSerialization:
    def test_roundtrip_through_json(self):
        from ctxpack.core.code.naming import qualified_name
        from ctxpack.core.code.symbols import Symbol, Kind
        s = Symbol(name="Widget.refresh", kind=Kind.METHOD,
                   line_start=1, line_end=1, byte_start=0, byte_end=1)
        name = qualified_name("ctxpack/core/code.py", s)
        encoded = json.dumps({"name": name})
        decoded = json.loads(encoded)
        assert decoded["name"] == name


class TestRealCodebase:
    def test_no_collisions_on_ctx_mod_self(self):
        """Sanity: on CTX_mod itself, every per-file qualified-name
        set is internally unique (collisions resolved by suffixing)."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.naming import qualified_names_for_module
        root = Path(__file__).parent.parent.parent / "ctxpack"
        for f in root.rglob("*.py"):
            r = parse_python(f)
            syms = extract_symbols(r)
            pairs = qualified_names_for_module(
                str(f.relative_to(root.parent)), syms
            )
            names = [n for _, n in pairs]
            assert len(names) == len(set(names)), (
                f"Duplicate qualified names in {f}: "
                f"{[n for n in names if names.count(n) > 1]}"
            )
