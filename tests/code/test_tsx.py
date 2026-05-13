"""CP-010.5/011/012/013/015 — TSX front end."""

from __future__ import annotations

from pathlib import Path


_FIX = Path(__file__).parent / "fixtures" / "tsx_react_min"


# ── CP-011: parser wrapper ──────────────────────────────────────────────


class TestParserWrapper:
    def test_module_importable(self):
        from ctxpack.core.code import parser_tsx  # noqa: F401

    def test_parses_tsx(self):
        from ctxpack.core.code.parser_tsx import parse_tsx
        result = parse_tsx(_FIX / "App.tsx")
        assert result.tree.root_node.type == "program"
        assert not result.tree.root_node.has_error

    def test_parses_ts(self):
        from ctxpack.core.code.parser_tsx import parse_tsx
        result = parse_tsx(_FIX / "useFoo.ts")
        assert not result.tree.root_node.has_error

    def test_missing_file_raises(self, tmp_path):
        from ctxpack.core.code.parser_tsx import parse_tsx
        import pytest
        with pytest.raises(FileNotFoundError):
            parse_tsx(tmp_path / "no.tsx")


# ── CP-012: symbol extraction ───────────────────────────────────────────


class TestExtractSymbols:
    def _syms(self, fname: str):
        from ctxpack.core.code.parser_tsx import parse_tsx
        from ctxpack.core.code.tsx import extract_symbols_tsx
        return extract_symbols_tsx(parse_tsx(_FIX / fname))

    def test_app_yields_component_and_type(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._syms("App.tsx")
        by_name = {s.name: s for s in syms}
        assert "App" in by_name
        assert by_name["App"].kind == Kind.COMPONENT
        assert "Item" in by_name
        assert by_name["Item"].kind == Kind.TYPE

    def test_card_forwardref_is_component(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._syms("Card.tsx")
        card = next(s for s in syms if s.name == "Card")
        assert card.kind == Kind.COMPONENT
        cardprops = next(s for s in syms if s.name == "CardProps")
        assert cardprops.kind == Kind.TYPE

    def test_usefoo_is_hook_not_a_hook_is_function(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._syms("useFoo.ts")
        by_name = {s.name: s for s in syms}
        assert by_name["useFoo"].kind == Kind.HOOK
        assert by_name["notAHook"].kind == Kind.FUNCTION

    def test_format_extracts_function_type_const(self):
        from ctxpack.core.code.symbols import Kind
        syms = self._syms("format.ts")
        by_name = {s.name: s for s in syms}
        assert by_name["formatLabel"].kind == Kind.FUNCTION
        assert by_name["LabelStyle"].kind == Kind.TYPE
        assert by_name["SEPARATOR"].kind == Kind.CONST

    def test_private_helper_not_exported(self):
        syms = self._syms("format.ts")
        helper = next(s for s in syms if s.name == "privateHelper")
        assert helper.exported is False

    def test_exported_function_is_exported(self):
        syms = self._syms("format.ts")
        formatlbl = next(s for s in syms if s.name == "formatLabel")
        assert formatlbl.exported is True


# ── CP-013: hooks detection ─────────────────────────────────────────────


class TestHooks:
    def _syms(self, fname: str):
        from ctxpack.core.code.parser_tsx import parse_tsx
        from ctxpack.core.code.tsx import extract_symbols_tsx
        return extract_symbols_tsx(parse_tsx(_FIX / fname))

    def test_app_component_uses_useState(self):
        app = next(s for s in self._syms("App.tsx") if s.name == "App")
        assert "useState" in app.hooks

    def test_app_component_uses_custom_hook(self):
        app = next(s for s in self._syms("App.tsx") if s.name == "App")
        assert "useFoo" in app.hooks

    def test_card_uses_multiple_react_hooks(self):
        card = next(s for s in self._syms("Card.tsx") if s.name == "Card")
        # The body uses useState + useEffect + useMemo.
        hookset = set(card.hooks)
        assert {"useState", "useEffect", "useMemo"}.issubset(hookset)

    def test_usefoo_hook_lists_its_own_calls(self):
        useFoo = next(s for s in self._syms("useFoo.ts") if s.name == "useFoo")
        # useFoo body calls useState + useEffect.
        assert "useState" in useFoo.hooks
        assert "useEffect" in useFoo.hooks

    def test_plain_function_has_no_hooks(self):
        nfn = next(s for s in self._syms("useFoo.ts") if s.name == "notAHook")
        assert nfn.hooks == ()


# ── CP-015: JSX call graph ──────────────────────────────────────────────


class TestCallGraph:
    def test_app_uses_card(self):
        from ctxpack.core.code.parser_tsx import parse_tsx
        from ctxpack.core.code.tsx import build_call_graph_tsx
        result = parse_tsx(_FIX / "App.tsx")
        edges = build_call_graph_tsx(result, "App.tsx")
        # App component renders <Card .../> — that should produce
        # an edge from App to Card.
        targets_of_app = {
            e.callee for e in edges if e.caller.endswith("::App")
        }
        assert "Card" in targets_of_app

    def test_lowercase_html_elements_not_edges(self):
        """<div> / <span> shouldn't appear as callees."""
        from ctxpack.core.code.parser_tsx import parse_tsx
        from ctxpack.core.code.tsx import build_call_graph_tsx
        result = parse_tsx(_FIX / "App.tsx")
        edges = build_call_graph_tsx(result, "App.tsx")
        callees = {e.callee for e in edges}
        assert "div" not in callees
        assert "pre" not in callees


# ── End-to-end: full pack picks up TSX too ──────────────────────────────


class TestPackTsx:
    def test_pack_includes_tsx_entities(self):
        from ctxpack.core.code.pack import pack_codebase
        pack = pack_codebase(_FIX)
        names = {e.name for e in pack.entities}
        assert any(n.endswith("::App") for n in names)
        assert any(n.endswith("::Card") for n in names)
        assert any(n.endswith("::useFoo") for n in names)
        assert any(n.endswith("::formatLabel") for n in names)

    def test_pack_files_includes_tsx_and_ts(self):
        from ctxpack.core.code.pack import pack_codebase
        pack = pack_codebase(_FIX)
        suffixes = {Path(f).suffix for f in pack.files}
        assert ".tsx" in suffixes
        assert ".ts" in suffixes

    def test_component_entity_carries_hooks_field(self):
        from ctxpack.core.code.pack import pack_codebase
        pack = pack_codebase(_FIX)
        app = next(e for e in pack.entities if e.name.endswith("::App"))
        fields = {f.key for f in app.fields}
        assert "hooks" in fields

    def test_unexported_entity_marked(self):
        from ctxpack.core.code.pack import pack_codebase
        pack = pack_codebase(_FIX)
        helper = next(
            e for e in pack.entities if e.name.endswith("::privateHelper")
        )
        # `exported=false` field present
        exported_field = next(
            (f.value for f in helper.fields if f.key == "exported"),
            None,
        )
        assert exported_field == "false"
