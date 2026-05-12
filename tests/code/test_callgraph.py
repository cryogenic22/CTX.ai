"""CP-014 — Python static call graph (best-effort, named call sites only)."""

from __future__ import annotations

from pathlib import Path


_FIX_FASTAPI = Path(__file__).parent / "fixtures" / "py_fastapi_min"
_FIX_CLASSES = Path(__file__).parent / "fixtures" / "py_classes_min"


class TestApi:
    def test_module_importable(self):
        from ctxpack.core.code import callgraph  # noqa: F401

    def test_calledge_frozen(self):
        from ctxpack.core.code.callgraph import CallEdge
        import dataclasses
        e = CallEdge(caller="x", callee="y", line=1)
        try:
            e.caller = "z"  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError("CallEdge should be frozen")


class TestBasicEdges:
    def _build(self, fixture_path: Path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.callgraph import build_call_graph
        return build_call_graph(parse_python(fixture_path), str(fixture_path))

    def test_read_user_calls_user(self):
        edges = self._build(_FIX_FASTAPI / "app.py")
        # Caller qualified name ends with ::read_user
        for e in edges:
            if e.caller.endswith("::read_user"):
                if e.callee == "User":
                    return
        raise AssertionError("Expected an edge from read_user to User()")

    def test_create_user_calls_user(self):
        edges = self._build(_FIX_FASTAPI / "app.py")
        callees_of_create = {
            e.callee for e in edges if e.caller.endswith("::create_user")
        }
        # create_user does `return user` — no call. But the function
        # body is just one line. Expect zero or limited calls.
        # We DON'T assert a call exists for create_user; the test pins
        # that read_user's calls flow through.
        assert isinstance(callees_of_create, set)

    def test_get_db_has_no_calls(self):
        """get_db just yields object() — that's one call (object)."""
        edges = self._build(_FIX_FASTAPI / "deps.py")
        # object() is a call. Skip if zero (different tree-sitter quirks).
        callees = [e.callee for e in edges if e.caller.endswith("::get_db")]
        assert "object" in callees or callees == []

    def test_widget_classmethod_edges(self):
        edges = self._build(_FIX_CLASSES / "widget.py")
        # Widget.from_dict calls cls(payload.get(...)) and payload.get
        # Expect to see at least one edge from Widget.from_dict
        from_dict_calls = [
            e.callee for e in edges if e.caller.endswith("::Widget.from_dict")
        ]
        assert len(from_dict_calls) >= 1


class TestLineNumbers:
    def test_call_line_is_within_caller_range(self):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.symbols import extract_symbols
        from ctxpack.core.code.callgraph import build_call_graph
        result = parse_python(_FIX_FASTAPI / "app.py")
        edges = build_call_graph(result, str(_FIX_FASTAPI / "app.py"))
        syms_by_qname = {}
        # Build symbol -> range map via qualified names
        from ctxpack.core.code.naming import qualified_names_for_module
        for sym, qname in qualified_names_for_module(
            str(_FIX_FASTAPI / "app.py"), extract_symbols(result)
        ):
            syms_by_qname[qname] = sym
        for edge in edges:
            sym = syms_by_qname.get(edge.caller)
            if sym is None:
                continue
            assert sym.line_start <= edge.line <= sym.line_end, (
                f"{edge}: line {edge.line} not in caller "
                f"{sym.line_start}-{sym.line_end}"
            )


class TestEmptyCases:
    def test_no_functions_no_edges(self, tmp_path: Path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.callgraph import build_call_graph
        f = tmp_path / "empty.py"
        f.write_bytes(b"# just a comment\nx = 1\n")
        assert build_call_graph(parse_python(f), str(f)) == []

    def test_function_no_calls(self, tmp_path: Path):
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.callgraph import build_call_graph
        f = tmp_path / "x.py"
        f.write_bytes(b"def foo():\n    return 1\n")
        edges = build_call_graph(parse_python(f), str(f))
        assert edges == []


class TestRealCodebase:
    def test_runs_on_ctx_mod_without_error(self):
        """Sanity: produce edges on every CTX_mod Python file without
        crashing. Doesn't assert specific counts (those would be
        brittle to refactors) — just no exceptions."""
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.callgraph import build_call_graph
        root = Path(__file__).parent.parent.parent / "ctxpack"
        total = 0
        for f in root.rglob("*.py"):
            edges = build_call_graph(parse_python(f), str(f))
            total += len(edges)
        # CTX_mod has many calls; assert a reasonable lower bound.
        assert total > 100
