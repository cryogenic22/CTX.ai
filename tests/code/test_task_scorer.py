"""CP-021/22/23 — BM25 task scorer + rank normalisation + combined."""

from __future__ import annotations

import pytest


def _make_entity(name: str, sig: str = "", doc: str = ""):
    from ctxpack.core.layers import ContextLayer
    from ctxpack.core.packer.ir import IREntity, IRField, IRSource
    return IREntity(
        name=name,
        fields=[
            IRField(key="kind", value="function"),
            IRField(key="signature", value=sig),
            IRField(key="docstring", value=doc),
        ],
        sources=[IRSource(file="x.py", line_start=1, line_end=1)],
        layer=ContextLayer.RULES,
        confidence=1.0,
    )


class TestTokenisation:
    def test_camelcase_split(self):
        from ctxpack.core.code.task_scorer import _tokenise
        toks = _tokenise("createUser")
        assert "createuser" in toks
        assert "create" in toks
        assert "user" in toks

    def test_snake_case_kept_lowered(self):
        from ctxpack.core.code.task_scorer import _tokenise
        toks = _tokenise("get_db")
        assert "get_db" in toks


class TestBm25:
    def test_query_match_in_name_scores_high(self):
        from ctxpack.core.code.task_scorer import compute_task_scores
        ents = [
            _make_entity("a.py::create_user", "def create_user(): pass"),
            _make_entity("a.py::list_items", "def list_items(): pass"),
            _make_entity("a.py::delete_user", "def delete_user(): pass"),
        ]
        scores = compute_task_scores(ents, "create user")
        assert scores["a.py::create_user"] > scores["a.py::list_items"]
        assert scores["a.py::delete_user"] > scores["a.py::list_items"]

    def test_empty_query_returns_zeros(self):
        from ctxpack.core.code.task_scorer import compute_task_scores
        ents = [_make_entity("a.py::foo")]
        scores = compute_task_scores(ents, "")
        assert scores["a.py::foo"] == 0.0

    def test_no_match_returns_zero(self):
        from ctxpack.core.code.task_scorer import compute_task_scores
        ents = [_make_entity("a.py::foo", "def foo(): pass")]
        scores = compute_task_scores(ents, "completely_unrelated_xyzzy")
        assert scores["a.py::foo"] == 0.0


class TestRankNormalise:
    def test_top_is_one_bottom_is_zero(self):
        from ctxpack.core.code.task_scorer import rank_normalise
        result = rank_normalise({"a": 10.0, "b": 5.0, "c": 1.0})
        assert result["a"] == pytest.approx(1.0)
        assert result["c"] == pytest.approx(0.0)
        # b is in the middle
        assert 0 < result["b"] < 1

    def test_ties_share_rank(self):
        from ctxpack.core.code.task_scorer import rank_normalise
        result = rank_normalise({"a": 1.0, "b": 1.0, "c": 1.0})
        # all same value → all same normalised rank
        assert result["a"] == result["b"] == result["c"]

    def test_empty(self):
        from ctxpack.core.code.task_scorer import rank_normalise
        assert rank_normalise({}) == {}

    def test_singleton(self):
        from ctxpack.core.code.task_scorer import rank_normalise
        assert rank_normalise({"a": 42.0}) == {"a": 1.0}


class TestCombined:
    def test_alpha_zero_is_pure_centrality(self):
        from ctxpack.core.code.task_scorer import combined_scores
        task = {"a": 1.0, "b": 100.0}  # b wins on task
        cent = {"a": 100.0, "b": 1.0}  # a wins on centrality
        result = combined_scores(
            task_scores=task, centrality_scores=cent, alpha=0.0,
        )
        # α=0 → pure centrality → a wins.
        assert result["a"] > result["b"]

    def test_alpha_one_is_pure_task(self):
        from ctxpack.core.code.task_scorer import combined_scores
        task = {"a": 1.0, "b": 100.0}
        cent = {"a": 100.0, "b": 1.0}
        result = combined_scores(
            task_scores=task, centrality_scores=cent, alpha=1.0,
        )
        # α=1 → pure task → b wins.
        assert result["b"] > result["a"]

    def test_default_alpha_combines(self):
        from ctxpack.core.code.task_scorer import combined_scores
        task = {"a": 1.0, "b": 100.0}
        cent = {"a": 100.0, "b": 1.0}
        result = combined_scores(task_scores=task, centrality_scores=cent)
        # Both should be present, neither at 0 or 1 — combination's
        # the point.
        assert 0 < result["a"] < 1
        assert 0 < result["b"] < 1

    def test_no_task_signal_falls_back_to_centrality(self):
        from ctxpack.core.code.task_scorer import combined_scores
        task = {"a": 0.0, "b": 0.0}
        cent = {"a": 100.0, "b": 1.0}
        # α=0.7 nominal, but effective α should become 0 → centrality.
        result = combined_scores(
            task_scores=task, centrality_scores=cent, alpha=0.7,
        )
        assert result["a"] > result["b"]

    def test_invalid_alpha_raises(self):
        from ctxpack.core.code.task_scorer import combined_scores
        with pytest.raises(ValueError):
            combined_scores(task_scores={}, centrality_scores={}, alpha=1.5)


class TestPackIntegration:
    def test_search_symbols_uses_bm25(self, tmp_path):
        """The new BM25 path should rank an exact-name match above a
        random other function."""
        from ctxpack.core.code.pack import pack_codebase, search_symbols
        (tmp_path / "a.py").write_text(
            "def create_user():\n    return 1\n\n"
            "def list_users():\n    return []\n\n"
            "def unrelated():\n    return 2\n"
        )
        pack = pack_codebase(tmp_path)
        result = search_symbols(pack, "create_user")
        # Top hit should be create_user, not unrelated.
        top = result["symbols"][0]
        assert top["name"].endswith("::create_user")

    def test_list_symbols_context_changes_ranking(self, tmp_path):
        """Same module, different context — ranking should differ."""
        from ctxpack.core.code.pack import pack_codebase, list_symbols
        (tmp_path / "x.py").write_text(
            "def create_widget(): pass\n"
            "def delete_widget(): pass\n"
            "def query_widget(): pass\n"
        )
        pack = pack_codebase(tmp_path)
        with_context = list_symbols(pack, "x.py", context="delete")
        names_in_order = [s["name"] for s in with_context["symbols"]]
        assert names_in_order[0].endswith("::delete_widget")
