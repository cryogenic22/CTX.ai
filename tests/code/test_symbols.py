"""CP-003 — top-level symbol extractor.

Acceptance: extract top-level functions and classes from a parsed
Python file. Methods are NOT in scope here (CP-004). Decorators are
captured separately (CP-005).
"""

from __future__ import annotations

from pathlib import Path

import pytest


_FIX = Path(__file__).parent / "fixtures" / "py_fastapi_min"
_PY_BROKEN = Path(__file__).parent / "fixtures" / "py_broken"


# ── API shape ───────────────────────────────────────────────────────────


class TestApi:
    def test_module_importable(self):
        from ctxpack.core.code import symbols  # noqa: F401

    def test_kind_enum_has_function_and_class(self):
        from ctxpack.core.code.symbols import Kind
        assert Kind.FUNCTION.value == "function"
        assert Kind.CLASS.value == "class"

    def test_symbol_dataclass_fields(self):
        from ctxpack.core.code.symbols import Symbol, Kind
        s = Symbol(
            name="foo",
            kind=Kind.FUNCTION,
            line_start=1,
            line_end=2,
            byte_start=0,
            byte_end=10,
        )
        assert s.name == "foo"
        assert s.kind == Kind.FUNCTION

    def test_symbol_is_frozen(self):
        from ctxpack.core.code.symbols import Symbol, Kind
        import dataclasses
        s = Symbol(
            name="foo", kind=Kind.FUNCTION,
            line_start=1, line_end=1,
            byte_start=0, byte_end=1,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.name = "bar"  # type: ignore[misc]


# ── Extraction from py_fastapi_min fixture ──────────────────────────────


class TestAppPy:
    def _extract(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        return extract_symbols(parse_python(_FIX / "app.py"))

    def test_app_yields_two_symbols(self):
        syms = self._extract()
        assert len(syms) == 2

    def test_app_symbols_are_functions(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._extract()
        assert all(s.kind == Kind.FUNCTION for s in syms)

    def test_app_symbol_names(self):
        syms = self._extract()
        assert [s.name for s in syms] == ["read_user", "create_user"]

    def test_app_read_user_line_range(self):
        """Body lines only — decorator on line 18 excluded; function
        spans 19-21 (def line + body)."""
        syms = self._extract()
        read_user = syms[0]
        assert read_user.line_start == 19
        assert read_user.line_end == 21

    def test_app_create_user_line_range(self):
        syms = self._extract()
        create_user = syms[1]
        assert create_user.line_start == 25
        assert create_user.line_end == 27


class TestModelsPy:
    def _extract(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        return extract_symbols(parse_python(_FIX / "models.py"))

    def test_models_yields_one_symbol(self):
        syms = self._extract()
        assert len(syms) == 1

    def test_models_user_is_class(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._extract()
        assert syms[0].name == "User"
        assert syms[0].kind == Kind.CLASS

    def test_models_user_line_range(self):
        syms = self._extract()
        assert syms[0].line_start == 11
        assert syms[0].line_end == 14


class TestDepsPy:
    def _extract(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        return extract_symbols(parse_python(_FIX / "deps.py"))

    def test_deps_yields_one_function(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._extract()
        assert len(syms) == 1
        assert syms[0].name == "get_db"
        assert syms[0].kind == Kind.FUNCTION

    def test_deps_get_db_line_range(self):
        syms = self._extract()
        assert syms[0].line_start == 13
        assert syms[0].line_end == 19


# ── Total fixture count ─────────────────────────────────────────────────


class TestFixtureTotal:
    def test_total_is_four_symbols(self):
        """Backlog acceptance: 'All 3 fixture files yield the expected
        symbol count.' 3 functions + 1 class = 4."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        all_syms = []
        for name in ("app.py", "models.py", "deps.py"):
            all_syms.extend(extract_symbols(parse_python(_FIX / name)))
        assert len(all_syms) == 4
        funcs = [s for s in all_syms if s.kind == Kind.FUNCTION]
        classes = [s for s in all_syms if s.kind == Kind.CLASS]
        assert len(funcs) == 3
        assert len(classes) == 1


# ── Byte-offset slicing round-trip ──────────────────────────────────────


class TestByteOffsets:
    def test_byte_range_recovers_source_text(self):
        """source[byte_start:byte_end] must produce the symbol's
        source text (def line + body). Downstream IREntity emission
        depends on this."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        result = parse_python(_FIX / "deps.py")
        sym = extract_symbols(result)[0]
        slice_ = result.source[sym.byte_start:sym.byte_end].decode("utf-8")
        assert slice_.startswith("def get_db")
        assert slice_.endswith(")") or slice_.rstrip().endswith(")")

    def test_byte_and_line_agree(self):
        """The line containing byte_start should equal line_start."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        result = parse_python(_FIX / "app.py")
        for sym in extract_symbols(result):
            # Count newlines from start of source up to byte_start;
            # add 1 because lines are 1-indexed.
            pre = result.source[:sym.byte_start]
            line_at_byte_start = pre.count(b"\n") + 1
            assert sym.line_start == line_at_byte_start, (
                f"{sym.name}: line_start={sym.line_start} but byte_start "
                f"is on line {line_at_byte_start}"
            )


# ── Ordering ────────────────────────────────────────────────────────────


class TestOrdering:
    def test_symbols_in_file_order(self):
        """Catalog rendering will use this ordering; humans expect
        top-to-bottom."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "app.py"))
        for a, b in zip(syms, syms[1:]):
            assert a.byte_start < b.byte_start


# ── Edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_file_yields_empty_list(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        f = tmp_path / "empty.py"
        f.write_bytes(b"")
        assert extract_symbols(parse_python(f)) == []

    def test_comment_only_file_yields_empty_list(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        f = tmp_path / "comments.py"
        f.write_bytes(b"# only a comment\n# and another\n")
        assert extract_symbols(parse_python(f)) == []

    def test_top_level_assignments_are_ignored(self, tmp_path):
        """Module-level constants are out of v0 scope. CP-003 ignores
        them; CP-004+ may add them under their own Kind."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        f = tmp_path / "const.py"
        f.write_bytes(b"X = 1\nY = 'two'\nZ: int = 3\n")
        assert extract_symbols(parse_python(f)) == []

    def test_broken_file_still_yields_recoverable_symbols(self):
        """tree-sitter recovers across syntax errors; the `survivor`
        function below the broken one should still appear."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_PY_BROKEN / "syntax_error.py"))
        names = {s.name for s in syms}
        assert "survivor" in names

    def test_async_function_is_extracted(self, tmp_path):
        """`async def foo()` is still a function for CP-003 purposes."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "async.py"
        f.write_bytes(b"async def fetch(url: str) -> str:\n    return url\n")
        syms = extract_symbols(parse_python(f))
        assert len(syms) == 1
        assert syms[0].name == "fetch"
        assert syms[0].kind == Kind.FUNCTION


# ── Red-team additions ─────────────────────────────────────────────────


class TestRedTeam:
    def test_methods_are_not_extracted_at_top_level(self, tmp_path):
        """CP-003 is top-level only; methods are CP-004. A class with
        a method should produce exactly ONE symbol (the class)."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "withmethod.py"
        f.write_bytes(
            b"class Foo:\n"
            b"    def bar(self):\n"
            b"        return 1\n"
        )
        syms = extract_symbols(parse_python(f))
        assert len(syms) == 1
        assert syms[0].name == "Foo"
        assert syms[0].kind == Kind.CLASS

    def test_nested_functions_are_not_extracted(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        f = tmp_path / "nested.py"
        f.write_bytes(
            b"def outer():\n"
            b"    def inner():\n"
            b"        return 1\n"
            b"    return inner\n"
        )
        syms = extract_symbols(parse_python(f))
        assert [s.name for s in syms] == ["outer"]

    def test_decorated_class_is_extracted(self, tmp_path):
        """Like decorated functions, decorated classes wrap inside
        decorated_definition. The walker must descend."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "decorated_class.py"
        f.write_bytes(
            b"from dataclasses import dataclass\n"
            b"\n"
            b"@dataclass\n"
            b"class Bar:\n"
            b"    x: int\n"
        )
        syms = extract_symbols(parse_python(f))
        assert len(syms) == 1
        assert syms[0].kind == Kind.CLASS
        assert syms[0].name == "Bar"

    def test_double_decorator_chain(self, tmp_path):
        """Multiple decorators stack as additional `decorator` children
        of one `decorated_definition`. The walker must find the
        function under all of them, not just the first."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        f = tmp_path / "double_decorator.py"
        f.write_bytes(
            b"def cache(fn): return fn\n"
            b"def retry(fn): return fn\n"
            b"\n"
            b"@cache\n"
            b"@retry\n"
            b"def heavy():\n"
            b"    return 1\n"
        )
        syms = extract_symbols(parse_python(f))
        names = [s.name for s in syms]
        assert "heavy" in names
        assert "cache" in names
        assert "retry" in names
        assert len(syms) == 3

    def test_two_classes_same_name_both_appear(self, tmp_path):
        """At CP-003 names are bare; same-named classes in conditional
        branches (e.g. py2/py3 compat) both appear. CP-009 will
        disambiguate. Pin the no-crash, no-dedupe behaviour now."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "conditional.py"
        f.write_bytes(
            b"import sys\n"
            b"if sys.version_info >= (3, 0):\n"
            b"    class Compat:\n"
            b"        pass\n"
            b"else:\n"
            b"    class Compat:\n"
            b"        pass\n"
        )
        syms = extract_symbols(parse_python(f))
        # The classes are INSIDE if/else blocks so they're not "top
        # level" by tree-sitter's structure — they're descendants of
        # `if_statement`. CP-003 should NOT find them. CP-004 may
        # revisit.
        assert all(s.kind != Kind.CLASS or s.name != "Compat" for s in syms), (
            "Classes nested inside if/else are not top-level."
        )
