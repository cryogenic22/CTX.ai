"""CP-010.3 — catalog row renderer with soft cap."""

from __future__ import annotations

from pathlib import Path


def _make_entity(name: str, sig: str, kind: str = "function", doc: str = ""):
    from ctxpack.core.layers import ContextLayer
    from ctxpack.core.packer.ir import IREntity, IRField, IRSource
    return IREntity(
        name=name,
        fields=[
            IRField(key="kind", value=kind),
            IRField(key="signature", value=sig),
            IRField(key="docstring", value=doc),
        ],
        sources=[IRSource(file="x.py", line_start=1, line_end=1)],
        layer=ContextLayer.RULES,
        confidence=1.0,
    )


class TestApi:
    def test_module_importable(self):
        from ctxpack.core.code import catalog  # noqa: F401

    def test_render_returns_string(self):
        from ctxpack.core.code.catalog import render_catalog_row
        ent = _make_entity("a.py::foo", "def foo(): pass")
        result = render_catalog_row(ent)
        assert isinstance(result, str)


class TestShortSignature:
    def test_short_signature_passes_through(self):
        from ctxpack.core.code.catalog import render_catalog_row
        ent = _make_entity("a.py::foo", "def foo() -> int:", doc="Return one.")
        row = render_catalog_row(ent)
        assert "a.py::foo" in row
        assert "function" in row
        assert "def foo() -> int:" in row
        # No truncation marker
        assert "…" not in row

    def test_includes_docstring_first_line(self):
        from ctxpack.core.code.catalog import render_catalog_row
        ent = _make_entity(
            "a.py::foo", "def foo():",
            doc="One-line.\nSecond line of docstring.",
        )
        row = render_catalog_row(ent)
        assert "One-line." in row
        # Only the first line of the docstring is part of the row
        assert "Second line" not in row


class TestSoftCap:
    def test_long_signature_truncates_with_ellipsis(self):
        from ctxpack.core.code.catalog import render_catalog_row
        from ctxpack.core.code.tokens import count_bpe
        long_sig = (
            "def merge_caches("
            + ", ".join(f"arg_{i}: int = 0" for i in range(30))
            + ") -> dict[str, list[Optional[Foo[Bar, Baz[Qux]]]]]:"
        )
        ent = _make_entity("a.py::long_one", long_sig)
        row = render_catalog_row(ent, cap=120)
        assert "…" in row
        # Cap is soft — allow a small overhead for the ellipsis and
        # surrounding structure.
        assert count_bpe(row) <= 120 + 10

    def test_name_never_truncated(self):
        from ctxpack.core.code.catalog import render_catalog_row
        long_sig = "def x(" + ", ".join(f"a{i}: int" for i in range(50)) + "): pass"
        ent = _make_entity("a.py::stable_name", long_sig)
        row = render_catalog_row(ent, cap=120)
        assert "a.py::stable_name" in row

    def test_tsx_generic_signature_truncates_at_boundary(self):
        from ctxpack.core.code.catalog import render_catalog_row
        sig = "type Foo<T extends Bar<U>, U = Baz<V, W, X, Y, Z, AA, BB>>"
        ent = _make_entity("file.tsx::Foo", sig, kind="type")
        row = render_catalog_row(ent, cap=80)
        # If truncation kicked in, the ellipsis should sit at a
        # generic-boundary character, not inside an identifier.
        if "…" in row:
            idx = row.index("…")
            prev = row[idx - 1]
            assert prev in (",", "]", ")", ">", "[", "(", "<", " ", "\t"), (
                f"truncation broke mid-identifier; prev char = {prev!r}"
            )


class TestMissingFields:
    def test_no_docstring_field(self):
        from ctxpack.core.code.catalog import render_catalog_row
        from ctxpack.core.layers import ContextLayer
        from ctxpack.core.packer.ir import IREntity, IRField, IRSource
        ent = IREntity(
            name="a.py::bare",
            fields=[
                IRField(key="kind", value="function"),
                IRField(key="signature", value="def bare(): pass"),
            ],
            sources=[IRSource(file="a.py", line_start=1, line_end=1)],
            layer=ContextLayer.RULES,
            confidence=1.0,
        )
        row = render_catalog_row(ent)
        # Should not crash. Should include sig.
        assert "def bare()" in row

    def test_no_signature_field(self):
        from ctxpack.core.code.catalog import render_catalog_row
        from ctxpack.core.layers import ContextLayer
        from ctxpack.core.packer.ir import IREntity, IRField, IRSource
        ent = IREntity(
            name="a.py::Foo.attr",
            fields=[IRField(key="kind", value="class_attribute")],
            sources=[IRSource(file="a.py", line_start=1, line_end=1)],
            layer=ContextLayer.RULES,
            confidence=1.0,
        )
        row = render_catalog_row(ent)
        assert "a.py::Foo.attr" in row
        assert "class_attribute" in row


class TestDeterminism:
    def test_two_calls_equal(self):
        from ctxpack.core.code.catalog import render_catalog_row
        ent = _make_entity("a.py::foo", "def foo(): pass", doc="X")
        assert render_catalog_row(ent) == render_catalog_row(ent)
