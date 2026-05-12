"""CP-010 — Symbol → IREntity emission."""

from __future__ import annotations

import json
from pathlib import Path


_FIX_FASTAPI = Path(__file__).parent / "fixtures" / "py_fastapi_min"
_FIX_DECORATORS = Path(__file__).parent / "fixtures" / "py_decorators_min"
_FIX_CLASSES = Path(__file__).parent / "fixtures" / "py_classes_min"


def _ents(fixture_path: Path):
    from ctxpack.core.code.parser import parse_python
    from ctxpack.core.code.emitter import emit_irentities
    rel = fixture_path.relative_to(Path(__file__).parent.parent.parent)
    return emit_irentities(parse_python(fixture_path), rel)


def _fields(ent) -> dict:
    return {f.key: f.value for f in ent.fields}


class TestBasicEmission:
    def test_module_importable(self):
        from ctxpack.core.code import emitter  # noqa: F401

    def test_one_entity_per_symbol_on_app_py(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        ents = _ents(_FIX_FASTAPI / "app.py")
        syms = extract_symbols(parse_python(_FIX_FASTAPI / "app.py"))
        assert len(ents) == len(syms)

    def test_entity_name_is_qualified(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        names = {e.name for e in ents}
        # File path is rendered with forward slashes; suffix is the
        # local symbol name. Read just the local part to confirm.
        assert any(n.endswith("::read_user") for n in names)
        assert any(n.endswith("::create_user") for n in names)


class TestSources:
    def test_sources_contains_file_and_line_range(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        read_user = next(e for e in ents if e.name.endswith("::read_user"))
        assert len(read_user.sources) == 1
        src = read_user.sources[0]
        assert "fixtures/py_fastapi_min/app.py" in src.file.replace("\\", "/")
        assert src.line_start == 19
        assert src.line_end == 21


class TestKindField:
    def test_function_kind(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        e = next(e for e in ents if e.name.endswith("::read_user"))
        assert _fields(e)["kind"] == "function"

    def test_class_kind(self):
        ents = _ents(_FIX_FASTAPI / "models.py")
        e = next(e for e in ents if e.name.endswith("::User"))
        assert _fields(e)["kind"] == "class"

    def test_method_kind(self):
        ents = _ents(_FIX_CLASSES / "widget.py")
        e = next(e for e in ents if e.name.endswith("::Widget.tick"))
        assert _fields(e)["kind"] == "method"

    def test_class_attribute_kind(self):
        ents = _ents(_FIX_CLASSES / "widget.py")
        e = next(e for e in ents if e.name.endswith("::Widget.MAX_TICKS"))
        assert _fields(e)["kind"] == "class_attribute"


class TestSignature:
    def test_function_signature_first_line(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        e = next(e for e in ents if e.name.endswith("::read_user"))
        sig = _fields(e)["signature"]
        assert sig.startswith("def read_user(")
        assert "User" in sig

    def test_class_signature(self):
        ents = _ents(_FIX_FASTAPI / "models.py")
        e = next(e for e in ents if e.name.endswith("::User"))
        sig = _fields(e)["signature"]
        assert sig.startswith("class User(")

    def test_async_method_signature_preserved(self):
        ents = _ents(_FIX_CLASSES / "widget.py")
        e = next(e for e in ents if e.name.endswith("::Widget.refresh"))
        sig = _fields(e)["signature"]
        assert "async def refresh" in sig


class TestDocstring:
    def test_docstring_extracted(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        e = next(e for e in ents if e.name.endswith("::read_user"))
        assert _fields(e)["docstring"] == "Fetch a user by id."

    def test_no_docstring_is_empty_string(self):
        ents = _ents(_FIX_CLASSES / "widget.py")
        e = next(e for e in ents if e.name.endswith("::Widget.tick"))
        # widget.tick has no docstring → empty
        assert _fields(e)["docstring"] == ""


class TestBody:
    def test_body_present_by_default(self):
        ents = _ents(_FIX_FASTAPI / "deps.py")
        e = next(e for e in ents if e.name.endswith("::get_db"))
        body = _fields(e)["body"]
        assert body.startswith("def get_db")
        assert "yield" in body

    def test_body_omitted_when_disabled(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.emitter import emit_irentities
        ents = emit_irentities(
            parse_python(_FIX_FASTAPI / "deps.py"),
            "tests/code/fixtures/py_fastapi_min/deps.py",
            include_body=False,
        )
        e = next(e for e in ents if e.name.endswith("::get_db"))
        assert "body" not in _fields(e)


class TestRouteFields:
    def test_route_fields_present_on_app_get(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        e = next(e for e in ents if e.name.endswith("::read_user"))
        fields = _fields(e)
        assert fields["http_method"] == "GET"
        assert fields["http_path"] == '"/users/{user_id}"'

    def test_route_fields_absent_on_non_route(self):
        ents = _ents(_FIX_FASTAPI / "deps.py")
        e = next(e for e in ents if e.name.endswith("::get_db"))
        fields = _fields(e)
        assert "http_method" not in fields
        assert "http_path" not in fields


class TestDependenciesField:
    def test_dependencies_serialised_as_json(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        e = next(e for e in ents if e.name.endswith("::read_user"))
        deps_raw = _fields(e)["dependencies"]
        deps = json.loads(deps_raw)
        assert deps == [{"parameter": "db", "target": "get_db"}]

    def test_dependencies_absent_when_none(self):
        ents = _ents(_FIX_FASTAPI / "deps.py")
        e = next(e for e in ents if e.name.endswith("::get_db"))
        assert "dependencies" not in _fields(e)


class TestPydanticFieldsEmission:
    def test_pydantic_fields_serialised_for_user(self):
        ents = _ents(_FIX_FASTAPI / "models.py")
        e = next(e for e in ents if e.name.endswith("::User"))
        pyf = json.loads(_fields(e)["pydantic_fields"])
        names = {f["name"] for f in pyf}
        assert names == {"id", "name", "email"}

    def test_pydantic_fields_absent_on_non_pydantic(self):
        ents = _ents(_FIX_CLASSES / "widget.py")
        e = next(e for e in ents if e.name.endswith("::Widget"))
        assert "pydantic_fields" not in _fields(e)


class TestDecoratorsField:
    def test_decorator_field_is_json_list(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        e = next(e for e in ents if e.name.endswith("::read_user"))
        decs = json.loads(_fields(e)["decorators"])
        assert decs == ["app.get"]

    def test_decorators_absent_on_undecorated(self):
        ents = _ents(_FIX_DECORATORS / "decorated.py")
        e = next(e for e in ents if e.name.endswith("::plain"))
        assert "decorators" not in _fields(e)


class TestCentralityPlaceholder:
    def test_centrality_prior_is_zero(self):
        ents = _ents(_FIX_FASTAPI / "app.py")
        for e in ents:
            assert _fields(e)["centrality_prior"] == "0.0"


class TestEntityMetadata:
    def test_layer_is_rules(self):
        from ctxpack.core.layers import ContextLayer
        ents = _ents(_FIX_FASTAPI / "app.py")
        for e in ents:
            assert e.layer == ContextLayer.RULES
            assert e.confidence == 1.0


class TestBodyTruncation:
    def test_huge_body_truncated_with_marker(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.emitter import emit_irentities, _BODY_BPE_CAP
        # Build a function whose body alone blows past the cap.
        f = tmp_path / "huge.py"
        big_line = "    pass  # " + "x" * 200 + "\n"
        f.write_text("def big():\n" + big_line * 600)
        ents = emit_irentities(parse_python(f), "huge.py")
        e = next(e for e in ents if e.name.endswith("::big"))
        body = _fields(e)["body"]
        from ctxpack.core.code.tokens import count_bpe
        # Total BPE must not vastly exceed the cap (marker adds a few).
        assert count_bpe(body) <= _BODY_BPE_CAP + 50
        assert "[truncated" in body
