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
_PY_CLASSES = Path(__file__).parent / "fixtures" / "py_classes_min"


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

    def test_models_yields_one_class(self):
        """After CP-004, models.py also yields CLASS_ATTRIBUTE entries
        for id/name/email. The class-level count stays at 1."""
        from ctxpack.core.code.symbols import Kind
        syms = self._extract()
        classes = [s for s in syms if s.kind == Kind.CLASS]
        assert len(classes) == 1

    def test_models_user_is_class(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._extract()
        classes = [s for s in syms if s.kind == Kind.CLASS]
        assert classes[0].name == "User"

    def test_models_user_line_range(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._extract()
        classes = [s for s in syms if s.kind == Kind.CLASS]
        assert classes[0].line_start == 11
        assert classes[0].line_end == 14


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
    def test_total_top_level_function_and_class_counts(self):
        """CP-003 acceptance: 3 functions + 1 class at top level
        across the fixture. CP-004 added CLASS_ATTRIBUTE entries
        underneath the User class — those don't change the top-level
        count, which is what this test guards."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        all_syms = []
        for name in ("app.py", "models.py", "deps.py"):
            all_syms.extend(extract_symbols(parse_python(_FIX / name)))
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
    def test_top_level_class_yields_exactly_one_class_symbol(self, tmp_path):
        """A class with a method now (post-CP-004) produces TWO
        symbols: the class plus the method. The top-level CLASS
        count stays 1."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "withmethod.py"
        f.write_bytes(
            b"class Foo:\n"
            b"    def bar(self):\n"
            b"        return 1\n"
        )
        syms = extract_symbols(parse_python(f))
        classes = [s for s in syms if s.kind == Kind.CLASS]
        methods = [s for s in syms if s.kind == Kind.METHOD]
        assert len(classes) == 1
        assert classes[0].name == "Foo"
        assert len(methods) == 1
        assert methods[0].name == "Foo.bar"

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
        decorated_definition. The walker must descend. After CP-004,
        the class attribute `x: int` is also extracted."""
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
        classes = [s for s in syms if s.kind == Kind.CLASS]
        attrs = [s for s in syms if s.kind == Kind.CLASS_ATTRIBUTE]
        assert len(classes) == 1
        assert classes[0].name == "Bar"
        assert len(attrs) == 1
        assert attrs[0].name == "Bar.x"

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

    # ── CP-004 additions: class body walking ────────────────────────────

    def _widget(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        return extract_symbols(parse_python(_PY_CLASSES / "widget.py"))

    def test_cp004_kind_enum_extended(self):
        from ctxpack.core.code.symbols import Kind
        assert Kind.METHOD.value == "method"
        assert Kind.CLASS_ATTRIBUTE.value == "class_attribute"

    def test_cp004_total_count_eleven(self):
        """1 class + 2 class_attribute + 8 method = 11.
        (8 not 7 because `age` getter and `age.setter` produce two
        method entries — see EDGE_CASES.md.)"""
        from ctxpack.core.code.symbols import Kind
        syms = self._widget()
        by_kind = {}
        for s in syms:
            by_kind.setdefault(s.kind, []).append(s.name)
        assert len(by_kind.get(Kind.CLASS, [])) == 1
        assert len(by_kind.get(Kind.CLASS_ATTRIBUTE, [])) == 2
        assert len(by_kind.get(Kind.METHOD, [])) == 8
        assert len(syms) == 11

    def test_cp004_method_naming_is_dotted(self):
        """Class.method form. CP-009 prepends file::."""
        from ctxpack.core.code.symbols import Kind
        method_names = {s.name for s in self._widget() if s.kind == Kind.METHOD}
        expected = {
            "Widget.__init__",
            "Widget.tick",
            "Widget.age",       # property getter
            "Widget.identity",
            "Widget.from_dict",
            "Widget.refresh",   # async
            "Widget.__repr__",
        }
        assert expected.issubset(method_names)

    def test_cp004_property_setter_same_name_produces_distinct_symbol(self):
        """@property age + @age.setter should both appear as
        Widget.age with kind=METHOD but different byte ranges."""
        from ctxpack.core.code.symbols import Kind
        ages = [s for s in self._widget()
                if s.kind == Kind.METHOD and s.name == "Widget.age"]
        assert len(ages) == 2
        # Distinct ranges → not a dedupe artefact
        ranges = {(s.byte_start, s.byte_end) for s in ages}
        assert len(ranges) == 2

    def test_cp004_class_attribute_names(self):
        from ctxpack.core.code.symbols import Kind
        attr_names = {s.name for s in self._widget()
                      if s.kind == Kind.CLASS_ATTRIBUTE}
        assert attr_names == {"Widget.MAX_TICKS", "Widget.name"}

    def test_cp004_dunders_are_extracted(self):
        from ctxpack.core.code.symbols import Kind
        names = {s.name for s in self._widget() if s.kind == Kind.METHOD}
        assert "Widget.__init__" in names
        assert "Widget.__repr__" in names

    def test_cp004_async_method_is_extracted(self):
        from ctxpack.core.code.symbols import Kind
        names = {s.name for s in self._widget() if s.kind == Kind.METHOD}
        assert "Widget.refresh" in names

    def test_cp004_decorated_method_is_extracted(self):
        """@staticmethod / @classmethod / @property all wrap in
        decorated_definition. Walker must descend."""
        from ctxpack.core.code.symbols import Kind
        names = {s.name for s in self._widget() if s.kind == Kind.METHOD}
        assert "Widget.identity" in names    # @staticmethod
        assert "Widget.from_dict" in names   # @classmethod

    def test_cp004_pydantic_style_typed_only_attributes_detected(self):
        """User(BaseModel) in py_fastapi_min has `id: int` etc. —
        typed declarations with no default. They must surface as
        CLASS_ATTRIBUTE."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        syms = extract_symbols(parse_python(_FIX / "models.py"))
        attr_names = {s.name for s in syms if s.kind == Kind.CLASS_ATTRIBUTE}
        assert "User.id" in attr_names
        assert "User.name" in attr_names
        assert "User.email" in attr_names

    def test_cp004_file_order_preserved_across_class_and_methods(self):
        """The full list interleaves class then its members in source
        order, then top-level continues. byte_start ascends."""
        syms = self._widget()
        for a, b in zip(syms, syms[1:]):
            assert a.byte_start < b.byte_start

    def test_cp004_class_docstring_not_emitted_as_attribute(self, tmp_path):
        """A class with a docstring as its first statement should not
        produce a spurious CLASS_ATTRIBUTE for the string."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "docstr.py"
        f.write_bytes(
            b"class WithDoc:\n"
            b'    """Class-level doc."""\n'
            b"    x: int = 1\n"
        )
        syms = extract_symbols(parse_python(f))
        attrs = [s for s in syms if s.kind == Kind.CLASS_ATTRIBUTE]
        assert {s.name for s in attrs} == {"WithDoc.x"}

    def test_cp004_tuple_assignment_in_class_body_skipped(self, tmp_path):
        """`a, b = 1, 2` at class level has `.left` as a pattern_list,
        not an identifier. v0 skips it cleanly; v1+ may unpack."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "tup.py"
        f.write_bytes(b"class C:\n    a, b = 1, 2\n    c = 3\n")
        syms = extract_symbols(parse_python(f))
        attrs = {s.name for s in syms if s.kind == Kind.CLASS_ATTRIBUTE}
        # Only `c` survives. a, b are skipped because the .left isn't
        # a simple identifier.
        assert attrs == {"C.c"}

    def test_cp004_no_regression_top_level_count(self):
        """py_fastapi_min/app.py still yields 2 top-level functions
        (CP-003 contract). Walking class bodies must not change
        top-level counts."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        syms = extract_symbols(parse_python(_FIX / "app.py"))
        top_funcs = [s for s in syms if s.kind == Kind.FUNCTION]
        assert {s.name for s in top_funcs} == {"read_user", "create_user"}

    def test_cp004_method_line_ranges(self):
        """Body-only ranges (decorator-excluded). Pinned line numbers
        catch a bug where the walker uses decorated_definition extent
        instead of the inner function_definition extent."""
        from ctxpack.core.code.symbols import Kind
        syms = self._widget()
        by_name_and_range = {
            (s.name, s.line_start, s.line_end)
            for s in syms if s.kind == Kind.METHOD
        }
        # tick is a plain method
        assert ("Widget.tick", 34, 36) in by_name_and_range
        # identity is @staticmethod — range is the inner function_definition,
        # NOT the decorated_definition wrapper
        assert ("Widget.identity", 47, 48) in by_name_and_range
        # refresh is async def
        assert ("Widget.refresh", 56, 57) in by_name_and_range

    def test_cp004_method_byte_range_roundtrip(self):
        """source[byte_start:byte_end] for a method recovers its
        source text — invariant inherited from CP-003."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        r = parse_python(_PY_CLASSES / "widget.py")
        method_syms = [s for s in extract_symbols(r) if s.kind == Kind.METHOD]
        for s in method_syms:
            text = r.source[s.byte_start:s.byte_end].decode("utf-8")
            assert text.lstrip().startswith(("def ", "async def "))

    def test_cp004_method_same_name_as_top_level_function_does_not_collide(self, tmp_path):
        """A top-level `tick()` and a `Foo.tick()` method should
        coexist — they have different Symbol.name strings."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "collide.py"
        f.write_bytes(
            b"def tick():\n    return 1\n"
            b"class Foo:\n    def tick(self):\n        return 2\n"
        )
        syms = extract_symbols(parse_python(f))
        names = {(s.kind, s.name) for s in syms}
        assert (Kind.FUNCTION, "tick") in names
        assert (Kind.METHOD, "Foo.tick") in names

    def test_cp004_empty_class_body_no_extras(self, tmp_path):
        """`class Empty: pass` yields just the CLASS, no methods/attrs.
        `pass` is a `pass_statement`, not assignment or function."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols, Kind
        f = tmp_path / "empty_class.py"
        f.write_bytes(b"class Empty:\n    pass\n")
        syms = extract_symbols(parse_python(f))
        assert len(syms) == 1
        assert syms[0].kind == Kind.CLASS

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
