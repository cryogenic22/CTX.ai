"""CP-005 — decorator capture on functions and methods."""

from __future__ import annotations

from pathlib import Path

import pytest


_FIX = Path(__file__).parent / "fixtures" / "py_decorators_min"


class TestApi:
    def test_decorator_dataclass(self):
        from ctxpack.core.code.symbols import Decorator
        d = Decorator(name="staticmethod", args=(), kwargs=(), line=1)
        assert d.name == "staticmethod"
        assert d.args == ()
        assert d.kwargs == ()

    def test_decorator_is_frozen(self):
        from ctxpack.core.code.symbols import Decorator
        import dataclasses
        d = Decorator(name="x", line=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.name = "y"  # type: ignore[misc]

    def test_symbol_has_decorators_field(self):
        from ctxpack.core.code.symbols import Symbol, Kind
        s = Symbol(
            name="foo", kind=Kind.FUNCTION,
            line_start=1, line_end=1,
            byte_start=0, byte_end=1,
        )
        assert s.decorators == ()


class TestPlainFunction:
    def test_plain_function_has_empty_decorators(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        plain = next(s for s in syms if s.name == "plain")
        assert plain.decorators == ()


class TestSingleDecorator:
    def test_simple_route_captures_app_get(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        sr = next(s for s in syms if s.name == "simple_route")
        assert len(sr.decorators) == 1
        d = sr.decorators[0]
        assert d.name == "app.get"

    def test_simple_route_decorator_arg_is_path(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        sr = next(s for s in syms if s.name == "simple_route")
        d = sr.decorators[0]
        # Positional first arg is "/foo" — source text of the string literal
        # includes quotes.
        assert len(d.args) == 1
        assert d.args[0] == '"/foo"'

    def test_simple_route_no_kwargs(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        sr = next(s for s in syms if s.name == "simple_route")
        d = sr.decorators[0]
        assert d.kwargs == ()


class TestKwargs:
    def test_create_user_decorator_kwargs(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        cu = next(s for s in syms if s.name == "create_user")
        d = cu.decorators[0]
        assert d.name == "app.post"
        assert d.args == ('"/users/{uid}"',)
        kwargs = dict(d.kwargs)
        assert kwargs["tags"] == '["users"]'
        assert kwargs["status_code"] == "201"


class TestMultipleDecorators:
    def test_heavy_has_three_decorators_in_source_order(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        heavy = next(s for s in syms if s.name == "heavy")
        names = [d.name for d in heavy.decorators]
        assert names == ["cache", "retry", "validators.email"]

    def test_undecorated_decorator_has_no_args(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        heavy = next(s for s in syms if s.name == "heavy")
        cache = heavy.decorators[0]
        assert cache.name == "cache"
        assert cache.args == ()
        assert cache.kwargs == ()

    def test_retry_kwargs(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        heavy = next(s for s in syms if s.name == "heavy")
        retry = next(d for d in heavy.decorators if d.name == "retry")
        kwargs = dict(retry.kwargs)
        assert kwargs == {"times": "3", "delay": "0.5"}


class TestMethodDecorators:
    def test_staticmethod_attached_to_method(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        m = next(s for s in syms if s.name == "Widget.static_helper")
        assert [d.name for d in m.decorators] == ["staticmethod"]

    def test_property_attached_to_method(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        m = next(s for s in syms if s.name == "Widget.value")
        assert [d.name for d in m.decorators] == ["property"]

    def test_stacked_method_decorators_order_preserved(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        syms = extract_symbols(parse_python(_FIX / "decorated.py"))
        m = next(s for s in syms if s.name == "Widget.classy")
        names = [d.name for d in m.decorators]
        assert names == ["some.factory", "classmethod"]


class TestExistingFixtures:
    def test_app_py_decorators_captured(self):
        """The CP-001 py_fastapi_min fixture has @app.get / @app.post —
        post-CP-005 those decorators must be visible on the symbols."""
        from pathlib import Path as P
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        fix = P(__file__).parent / "fixtures" / "py_fastapi_min" / "app.py"
        syms = extract_symbols(parse_python(fix))
        read_user = next(s for s in syms if s.name == "read_user")
        assert any(d.name == "app.get" for d in read_user.decorators)
        create_user = next(s for s in syms if s.name == "create_user")
        assert any(d.name == "app.post" for d in create_user.decorators)
