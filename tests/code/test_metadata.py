"""CP-006/007/008 — semantic interpretation of symbols + decorators.

Three pure-helper APIs in `ctxpack.core.code.metadata`:

- `extract_route(symbol)` — FastAPI route decorators → RouteInfo.
- `extract_dependencies(parse_result, symbol)` — `Depends(...)` params.
- `is_pydantic_model(parse_result, symbol)` — class inherits BaseModel.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_FIX_FASTAPI = Path(__file__).parent / "fixtures" / "py_fastapi_min"
_FIX_DECORATORS = Path(__file__).parent / "fixtures" / "py_decorators_min"
_FIX_CLASSES = Path(__file__).parent / "fixtures" / "py_classes_min"


# ── CP-006: FastAPI route detection ─────────────────────────────────────


class TestRouteApi:
    def test_module_importable(self):
        from ctxpack.core.code import metadata  # noqa: F401

    def test_routeinfo_is_frozen(self):
        from ctxpack.core.code.metadata import RouteInfo
        import dataclasses
        r = RouteInfo(http_method="GET", http_path='"/x"')
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.http_method = "POST"  # type: ignore[misc]


class TestRouteDetection:
    def _syms(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        return extract_symbols(parse_python(_FIX_FASTAPI / "app.py"))

    def test_app_get_detected(self):
        from ctxpack.core.code.metadata import extract_route
        ru = next(s for s in self._syms() if s.name == "read_user")
        r = extract_route(ru)
        assert r is not None
        assert r.http_method == "GET"
        assert r.http_path == '"/users/{user_id}"'

    def test_app_post_detected(self):
        from ctxpack.core.code.metadata import extract_route
        cu = next(s for s in self._syms() if s.name == "create_user")
        r = extract_route(cu)
        assert r is not None
        assert r.http_method == "POST"
        assert r.http_path == '"/users"'

    def test_non_route_returns_none(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import extract_route
        syms = extract_symbols(parse_python(_FIX_DECORATORS / "decorated.py"))
        plain = next(s for s in syms if s.name == "plain")
        assert extract_route(plain) is None
        heavy = next(s for s in syms if s.name == "heavy")
        assert extract_route(heavy) is None  # @cache, @retry, @validators.email

    def test_property_is_not_a_route(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import extract_route
        syms = extract_symbols(parse_python(_FIX_DECORATORS / "decorated.py"))
        value = next(s for s in syms if s.name == "Widget.value")
        assert extract_route(value) is None

    def test_all_http_methods_detected(self):
        """Pin every HTTP verb FastAPI supports."""
        from ctxpack.core.code.symbols import Symbol, Kind, Decorator
        from ctxpack.core.code.metadata import extract_route
        for method in ["get", "post", "put", "patch", "delete", "head", "options"]:
            s = Symbol(
                name="x", kind=Kind.FUNCTION,
                line_start=1, line_end=1, byte_start=0, byte_end=1,
                decorators=(Decorator(name=f"router.{method}", args=('"/x"',)),),
            )
            r = extract_route(s)
            assert r is not None
            assert r.http_method == method.upper()

    def test_decorator_without_call_still_route(self):
        """`@app.get` (no parens) is unusual but legal Python; the
        framework would never accept it but we still classify."""
        from ctxpack.core.code.symbols import Symbol, Kind, Decorator
        from ctxpack.core.code.metadata import extract_route
        s = Symbol(
            name="x", kind=Kind.FUNCTION,
            line_start=1, line_end=1, byte_start=0, byte_end=1,
            decorators=(Decorator(name="app.get"),),
        )
        r = extract_route(s)
        assert r is not None
        assert r.http_method == "GET"
        assert r.http_path is None

    def test_symbol_without_decorators_returns_none(self):
        from ctxpack.core.code.symbols import Symbol, Kind
        from ctxpack.core.code.metadata import extract_route
        s = Symbol(
            name="x", kind=Kind.FUNCTION,
            line_start=1, line_end=1, byte_start=0, byte_end=1,
        )
        assert extract_route(s) is None

    def test_multi_decorator_with_route_returns_route(self):
        """`@cached @router.get("/x")` should still produce the route."""
        from ctxpack.core.code.symbols import Symbol, Kind, Decorator
        from ctxpack.core.code.metadata import extract_route
        s = Symbol(
            name="x", kind=Kind.FUNCTION,
            line_start=1, line_end=1, byte_start=0, byte_end=1,
            decorators=(
                Decorator(name="cached"),
                Decorator(name="router.get", args=('"/x"',)),
            ),
        )
        r = extract_route(s)
        assert r is not None
        assert r.http_method == "GET"


# ── CP-007: Depends(...) extraction ─────────────────────────────────────


class TestDependsApi:
    def test_dependency_is_frozen(self):
        from ctxpack.core.code.metadata import Dependency
        import dataclasses
        d = Dependency(parameter="db", target="get_db")
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.parameter = "x"  # type: ignore[misc]


class TestDependsExtraction:
    def _parse_and_find(self, name: str):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        result = parse_python(_FIX_FASTAPI / "app.py")
        sym = next(s for s in extract_symbols(result) if s.name == name)
        return result, sym

    def test_read_user_has_depends_get_db(self):
        from ctxpack.core.code.metadata import extract_dependencies
        result, sym = self._parse_and_find("read_user")
        deps = extract_dependencies(result, sym)
        assert len(deps) == 1
        assert deps[0].parameter == "db"
        assert deps[0].target == "get_db"

    def test_create_user_has_depends_get_db(self):
        from ctxpack.core.code.metadata import extract_dependencies
        result, sym = self._parse_and_find("create_user")
        deps = extract_dependencies(result, sym)
        assert len(deps) == 1
        assert deps[0].target == "get_db"

    def test_function_without_depends_returns_empty(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import extract_dependencies
        result = parse_python(_FIX_DECORATORS / "decorated.py")
        sym = next(s for s in extract_symbols(result) if s.name == "plain")
        assert extract_dependencies(result, sym) == []

    def test_class_symbol_returns_empty(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import extract_dependencies
        result = parse_python(_FIX_CLASSES / "widget.py")
        sym = next(s for s in extract_symbols(result) if s.name == "Widget")
        assert extract_dependencies(result, sym) == []

    def test_typed_default_parameter_shape(self, tmp_path):
        """`db: Session = Depends(get_db)` is a typed_default_parameter
        rather than default_parameter — must be handled."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import extract_dependencies
        f = tmp_path / "typed_depends.py"
        f.write_bytes(
            b"from fastapi import Depends\n"
            b"def get_db(): pass\n"
            b"def handler(db: object = Depends(get_db)):\n"
            b"    return db\n"
        )
        result = parse_python(f)
        sym = next(s for s in extract_symbols(result) if s.name == "handler")
        deps = extract_dependencies(result, sym)
        assert len(deps) == 1
        assert deps[0].parameter == "db"
        assert deps[0].target == "get_db"

    def test_multiple_depends_params(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import extract_dependencies
        f = tmp_path / "multi.py"
        f.write_bytes(
            b"from fastapi import Depends\n"
            b"def get_db(): pass\n"
            b"def get_user(): pass\n"
            b"def handler(db=Depends(get_db), user=Depends(get_user)):\n"
            b"    return db\n"
        )
        result = parse_python(f)
        sym = next(s for s in extract_symbols(result) if s.name == "handler")
        deps = extract_dependencies(result, sym)
        targets = {d.target for d in deps}
        assert targets == {"get_db", "get_user"}


# ── CP-008: Pydantic BaseModel detection ────────────────────────────────


class TestPydanticDetection:
    def test_user_is_pydantic_model(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import is_pydantic_model
        result = parse_python(_FIX_FASTAPI / "models.py")
        user = next(s for s in extract_symbols(result) if s.name == "User")
        assert is_pydantic_model(result, user) is True

    def test_widget_is_not_pydantic_model(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import is_pydantic_model
        result = parse_python(_FIX_CLASSES / "widget.py")
        widget = next(s for s in extract_symbols(result) if s.name == "Widget")
        assert is_pydantic_model(result, widget) is False

    def test_function_returns_false(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import is_pydantic_model
        result = parse_python(_FIX_FASTAPI / "deps.py")
        sym = next(s for s in extract_symbols(result) if s.name == "get_db")
        assert is_pydantic_model(result, sym) is False

    def test_dotted_basemodel_detected(self, tmp_path):
        """`class X(pydantic.BaseModel)` should also be detected."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import is_pydantic_model
        f = tmp_path / "dotted.py"
        f.write_bytes(
            b"import pydantic\n"
            b"class X(pydantic.BaseModel):\n"
            b"    x: int\n"
        )
        result = parse_python(f)
        x = next(s for s in extract_symbols(result) if s.name == "X")
        assert is_pydantic_model(result, x) is True

    def test_pydantic_fields_from_user(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import pydantic_fields
        result = parse_python(_FIX_FASTAPI / "models.py")
        user = next(s for s in extract_symbols(result) if s.name == "User")
        fields = pydantic_fields(result, user)
        by_name = {f.name: f for f in fields}
        assert set(by_name) == {"id", "name", "email"}
        assert by_name["id"].type_source == "int"
        assert by_name["name"].type_source == "str"
        assert by_name["email"].type_source == "str"
        # No defaults on this model.
        assert all(f.default_source is None for f in fields)

    def test_pydantic_fields_with_defaults(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import pydantic_fields
        f = tmp_path / "defaults.py"
        f.write_bytes(
            b"from pydantic import BaseModel\n"
            b"class Pt(BaseModel):\n"
            b"    x: int\n"
            b"    y: int = 0\n"
            b"    label: str = \"\"\n"
        )
        result = parse_python(f)
        pt = next(s for s in extract_symbols(result) if s.name == "Pt")
        fields = pydantic_fields(result, pt)
        by_name = {fld.name: fld for fld in fields}
        assert by_name["x"].default_source is None
        assert by_name["y"].default_source == "0"
        assert by_name["label"].default_source == '""'

    def test_pydantic_fields_non_pydantic_returns_empty(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import pydantic_fields
        result = parse_python(_FIX_CLASSES / "widget.py")
        widget = next(s for s in extract_symbols(result) if s.name == "Widget")
        assert pydantic_fields(result, widget) == []

    def test_pydantic_fields_non_class_returns_empty(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.metadata import pydantic_fields
        result = parse_python(_FIX_FASTAPI / "deps.py")
        sym = next(s for s in extract_symbols(result) if s.name == "get_db")
        assert pydantic_fields(result, sym) == []
