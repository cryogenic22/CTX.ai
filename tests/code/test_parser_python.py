"""CP-002 — tree-sitter Python parser wrapper.

Pins the parser API every downstream extractor (CP-003+) builds on:

- `parse_python(path) → ParseResult`.
- ParseResult contains the raw tree-sitter Tree, the source bytes,
  and a warnings list for partial-parse cases.
- Syntax errors don't raise; they surface as warnings on the result.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_PY_FASTAPI = Path(__file__).parent / "fixtures" / "py_fastapi_min"
_PY_BROKEN = Path(__file__).parent / "fixtures" / "py_broken"


# ── Happy path ──────────────────────────────────────────────────────────


class TestHappyPath:
    def test_module_importable(self):
        from ctxpack.core.code import parser  # noqa: F401

    def test_returns_parse_result_with_tree(self):
        from ctxpack.core.code.parser import parse_python, ParseResult
        result = parse_python(_PY_FASTAPI / "app.py")
        assert isinstance(result, ParseResult)
        assert result.tree is not None
        assert result.tree.root_node.type == "module"

    def test_app_py_parses_without_warnings(self):
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_FASTAPI / "app.py")
        assert not result.tree.root_node.has_error
        assert result.warnings == []

    def test_deps_py_parses_without_warnings(self):
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_FASTAPI / "deps.py")
        assert not result.tree.root_node.has_error
        assert result.warnings == []

    def test_models_py_parses_without_warnings(self):
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_FASTAPI / "models.py")
        assert not result.tree.root_node.has_error
        assert result.warnings == []

    def test_path_is_preserved(self):
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_FASTAPI / "app.py")
        assert result.path == _PY_FASTAPI / "app.py"

    def test_source_bytes_preserved(self):
        """Downstream extractors slice node.start_byte:node.end_byte
        out of result.source; the bytes must match what was on disk."""
        from ctxpack.core.code.parser import parse_python
        path = _PY_FASTAPI / "app.py"
        result = parse_python(path)
        assert result.source == path.read_bytes()

    def test_root_property_returns_root_node(self):
        """tree-sitter's Python binding creates fresh Node wrappers on
        each `root_node` access, so identity comparison (`is`) fails
        even when both refer to the same tree position. Compare by
        node type and byte range instead.
        """
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_FASTAPI / "app.py")
        root = result.root
        rn = result.tree.root_node
        assert root.type == rn.type
        assert root.start_byte == rn.start_byte
        assert root.end_byte == rn.end_byte

    def test_accepts_str_path(self):
        from ctxpack.core.code.parser import parse_python
        result = parse_python(str(_PY_FASTAPI / "app.py"))
        assert result.tree.root_node.type == "module"


# ── Syntax errors → warnings, not exceptions ────────────────────────────


class TestSyntaxErrorHandling:
    def test_broken_file_does_not_raise(self):
        from ctxpack.core.code.parser import parse_python
        # Must not raise. The whole point.
        result = parse_python(_PY_BROKEN / "syntax_error.py")
        assert result is not None

    def test_broken_file_yields_warnings(self):
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_BROKEN / "syntax_error.py")
        assert len(result.warnings) >= 1

    def test_broken_file_tree_root_has_error(self):
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_BROKEN / "syntax_error.py")
        assert result.tree.root_node.has_error

    def test_broken_file_partial_parse_still_useful(self):
        """tree-sitter recovers after errors; later valid definitions
        in the file should still appear in the tree. This is what
        'partial tree' means in the acceptance criterion."""
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_BROKEN / "syntax_error.py")
        # `survivor` is defined after the syntax error.
        # It should show up as a function_definition node somewhere.
        found_survivor = _find_function_named(result.tree.root_node, "survivor")
        assert found_survivor is not None, (
            "Expected tree-sitter's partial parse to recover and surface "
            "`survivor` after the broken function."
        )

    def test_warning_has_line_and_column(self):
        from ctxpack.core.code.parser import parse_python, ParseWarning
        result = parse_python(_PY_BROKEN / "syntax_error.py")
        w = result.warnings[0]
        assert isinstance(w, ParseWarning)
        # 1-indexed line numbers, 0-indexed columns
        assert w.line_start >= 1
        assert w.line_end >= w.line_start
        assert w.column_start >= 0
        assert w.column_end >= w.column_start


# ── Encoding ────────────────────────────────────────────────────────────


class TestEncoding:
    def test_non_ascii_identifiers_parse(self):
        from ctxpack.core.code.parser import parse_python
        result = parse_python(_PY_BROKEN / "unicode_identifiers.py")
        assert not result.tree.root_node.has_error
        assert result.warnings == []

    def test_non_ascii_source_bytes_preserved(self):
        from ctxpack.core.code.parser import parse_python
        path = _PY_BROKEN / "unicode_identifiers.py"
        result = parse_python(path)
        assert result.source == path.read_bytes()
        assert "café".encode("utf-8") in result.source


# ── Filesystem errors ───────────────────────────────────────────────────


class TestFilesystemErrors:
    def test_missing_file_raises_filenotfounderror(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        with pytest.raises(FileNotFoundError):
            parse_python(tmp_path / "nonexistent.py")

    def test_directory_raises_isadirectoryerror(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        with pytest.raises(IsADirectoryError):
            parse_python(tmp_path)


# ── Edge cases (red-team material from spec) ────────────────────────────


class TestEdgeCases:
    def test_empty_file_returns_module_with_no_children(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        empty = tmp_path / "empty.py"
        empty.write_bytes(b"")
        result = parse_python(empty)
        assert result.tree.root_node.type == "module"
        assert len(result.tree.root_node.children) == 0
        assert result.warnings == []

    def test_comment_only_file_no_warnings(self, tmp_path):
        from ctxpack.core.code.parser import parse_python
        f = tmp_path / "comments.py"
        f.write_bytes(b"# just a comment\n# and another\n")
        result = parse_python(f)
        assert not result.tree.root_node.has_error
        assert result.warnings == []

    def test_two_parses_are_equivalent(self):
        """Determinism invariant — required by §8.6 down the line."""
        from ctxpack.core.code.parser import parse_python
        r1 = parse_python(_PY_FASTAPI / "app.py")
        r2 = parse_python(_PY_FASTAPI / "app.py")
        assert r1.source == r2.source
        assert r1.tree.root_node.type == r2.tree.root_node.type
        assert (
            r1.tree.root_node.child_count
            == r2.tree.root_node.child_count
        )
        # Compare child types pairwise as a structural-equivalence
        # proxy (tree-sitter Tree objects don't implement __eq__).
        t1 = [c.type for c in r1.tree.root_node.children]
        t2 = [c.type for c in r2.tree.root_node.children]
        assert t1 == t2


# ── Red-team additions ─────────────────────────────────────────────────


class TestRedTeam:
    def test_nested_syntax_error_is_surfaced(self, tmp_path):
        """The walker optimises by descending only into subtrees where
        ``has_error`` is True. If we ever flip the polarity or skip the
        wrong branch, deeply nested errors will silently disappear from
        the warnings list. Pin the contract with a nested-error case."""
        from ctxpack.core.code.parser import parse_python
        f = tmp_path / "nested.py"
        f.write_bytes(
            b"class Outer:\n"
            b"    class Inner:\n"
            b"        def broken_method(\n"  # missing paren
            b"            pass\n"
        )
        result = parse_python(f)
        assert result.tree.root_node.has_error
        assert len(result.warnings) >= 1, (
            "Nested errors must be surfaced, not lost in the optimised "
            "tree walk."
        )

    def test_parser_handles_interleaved_calls(self):
        """Singleton parser is used by every call. Test that
        interleaving parses of different files doesn't cross-pollute
        state (e.g. a parser holding onto a previous file's bytes)."""
        from ctxpack.core.code.parser import parse_python
        r1 = parse_python(_PY_FASTAPI / "app.py")
        r2 = parse_python(_PY_FASTAPI / "models.py")
        r1_again = parse_python(_PY_FASTAPI / "app.py")
        assert r1.source == r1_again.source
        # Source bytes must reflect the file just parsed, not the
        # most-recent-overall one.
        assert r1.source != r2.source
        assert r1.tree.root_node.start_byte == r1_again.tree.root_node.start_byte

    def test_warnings_are_frozen_dataclass(self):
        """ParseWarning is frozen so downstream code can put it into
        sets / use as dict keys without surprising mutation. Pin it.
        """
        from ctxpack.core.code.parser import ParseWarning
        import dataclasses
        w = ParseWarning(
            message="x", line_start=1, line_end=1,
            column_start=0, column_end=1,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            w.message = "mutated"  # type: ignore[misc]

    def test_parse_result_warnings_default_is_independent_per_instance(self):
        """Mutable default args / shared list defaults are a recurring
        dataclass footgun. A fresh ParseResult must get its own list,
        not share one with siblings."""
        from ctxpack.core.code.parser import ParseResult
        import tree_sitter, tree_sitter_python
        lang = tree_sitter.Language(tree_sitter_python.language())
        parser = tree_sitter.Parser(lang)
        tree = parser.parse(b"x = 1\n")
        from pathlib import Path
        r1 = ParseResult(path=Path("a.py"), tree=tree, source=b"a")
        r2 = ParseResult(path=Path("b.py"), tree=tree, source=b"b")
        assert r1.warnings is not r2.warnings
        r1.warnings.append(None)  # type: ignore[arg-type]
        assert r2.warnings == []


# ── Helpers ─────────────────────────────────────────────────────────────


def _find_function_named(node, name: str):
    """Walk the tree-sitter tree iteratively, return the
    function_definition node whose 'name' field child equals `name`,
    or None.
    """
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "function_definition":
            name_node = n.child_by_field_name("name")
            if name_node is not None and name_node.text == name.encode("utf-8"):
                return n
        stack.extend(n.children)
    return None
