"""CP-019/020 — PageRank ranker + centrality_prior population."""

from __future__ import annotations

import pytest


class TestPageRank:
    def test_module_importable(self):
        from ctxpack.core.code import ranker  # noqa: F401

    def test_scores_sum_to_one(self):
        from ctxpack.core.code.ranker import compute_pagerank
        from ctxpack.core.code.callgraph import CallEdge
        nodes = {"a", "b", "c"}
        edges = [
            CallEdge(caller="a", callee="b", line=1),
            CallEdge(caller="b", callee="c", line=1),
            CallEdge(caller="c", callee="a", line=1),
        ]
        scores = compute_pagerank(nodes, edges)
        assert pytest.approx(sum(scores.values()), rel=1e-3) == 1.0

    def test_more_in_edges_higher_score(self):
        """Node with two incoming edges should outrank a node with one
        (modulo damping)."""
        from ctxpack.core.code.ranker import compute_pagerank
        from ctxpack.core.code.callgraph import CallEdge
        nodes = {"a", "b", "c", "d"}
        edges = [
            CallEdge(caller="a", callee="d", line=1),
            CallEdge(caller="b", callee="d", line=1),
            CallEdge(caller="c", callee="d", line=1),
        ]
        scores = compute_pagerank(nodes, edges)
        # d has 3 incoming; a/b/c have 0
        assert scores["d"] > scores["a"]
        assert scores["d"] > scores["b"]
        assert scores["d"] > scores["c"]

    def test_test_edges_weighted_three_times(self):
        """A test caller's edge to a callee should carry 3× the weight
        of a non-test caller's edge to a different callee."""
        from ctxpack.core.code.ranker import compute_pagerank
        from ctxpack.core.code.callgraph import CallEdge

        # Two parallel structures: regular_caller -> normal_target,
        # test_caller -> tested_target. The tested_target should
        # end up ranked higher.
        nodes = {
            "a.py::regular_caller", "a.py::normal_target",
            "tests/t_x.py::test_func", "a.py::tested_target",
        }
        edges = [
            CallEdge(
                caller="a.py::regular_caller",
                callee="a.py::normal_target", line=1,
            ),
            CallEdge(
                caller="tests/t_x.py::test_func",
                callee="a.py::tested_target", line=1,
            ),
        ]
        scores = compute_pagerank(
            nodes, edges,
            test_node_predicate=lambda n: n.startswith("tests/"),
        )
        assert scores["a.py::tested_target"] > scores["a.py::normal_target"]

    def test_determinism_two_runs(self):
        from ctxpack.core.code.ranker import compute_pagerank
        from ctxpack.core.code.callgraph import CallEdge
        nodes = {"a", "b", "c"}
        edges = [
            CallEdge(caller="a", callee="b", line=1),
            CallEdge(caller="c", callee="b", line=1),
        ]
        s1 = compute_pagerank(nodes, edges)
        s2 = compute_pagerank(nodes, edges)
        assert s1 == s2

    def test_isolated_node_gets_baseline(self):
        from ctxpack.core.code.ranker import compute_pagerank
        nodes = {"isolated"}
        scores = compute_pagerank(nodes, [])
        # Single isolated node owns the full probability mass.
        assert pytest.approx(scores["isolated"], rel=1e-3) == 1.0

    def test_dangling_callee_resolves(self):
        """An edge to an unknown node shouldn't crash."""
        from ctxpack.core.code.ranker import compute_pagerank
        from ctxpack.core.code.callgraph import CallEdge
        nodes = {"a"}
        edges = [CallEdge(caller="a", callee="ghost", line=1)]
        scores = compute_pagerank(nodes, edges)
        assert "a" in scores


class TestPopulateCentrality:
    def test_updates_centrality_prior_field(self):
        from ctxpack.core.layers import ContextLayer
        from ctxpack.core.packer.ir import IREntity, IRField, IRSource
        from ctxpack.core.code.ranker import populate_centrality_prior
        ent = IREntity(
            name="a.py::foo",
            fields=[
                IRField(key="kind", value="function"),
                IRField(key="centrality_prior", value="0.0"),
            ],
            sources=[IRSource(file="a.py", line_start=1, line_end=1)],
            layer=ContextLayer.RULES,
            confidence=1.0,
        )
        populate_centrality_prior([ent], {"a.py::foo": 0.42})
        cp = next(f.value for f in ent.fields if f.key == "centrality_prior")
        assert float(cp) == pytest.approx(0.42)

    def test_missing_score_leaves_zero(self):
        from ctxpack.core.layers import ContextLayer
        from ctxpack.core.packer.ir import IREntity, IRField, IRSource
        from ctxpack.core.code.ranker import populate_centrality_prior
        ent = IREntity(
            name="a.py::foo",
            fields=[IRField(key="centrality_prior", value="0.0")],
            sources=[IRSource(file="a.py", line_start=1, line_end=1)],
            layer=ContextLayer.RULES,
            confidence=1.0,
        )
        populate_centrality_prior([ent], {})  # no score for foo
        cp = next(f.value for f in ent.fields if f.key == "centrality_prior")
        assert float(cp) == 0.0


class TestEndToEnd:
    def test_pack_and_rank_fixture(self):
        """Wire the full pipeline: parse → emit → call graph → rank →
        populate. Pin that the result has a top-ranked entity."""
        from pathlib import Path
        from ctxpack.core.code.parser import parse_python
        from ctxpack.core.code.emitter import emit_irentities
        from ctxpack.core.code.callgraph import build_call_graph
        from ctxpack.core.code.ranker import (
            compute_pagerank, populate_centrality_prior,
        )
        f = Path(__file__).parent / "fixtures" / "py_fastapi_min" / "app.py"
        result = parse_python(f)
        ents = emit_irentities(result, str(f))
        edges = build_call_graph(result, str(f))
        scores = compute_pagerank({e.name for e in ents}, edges)
        populate_centrality_prior(ents, scores)
        # At least one entity has nonzero centrality_prior post-population.
        cps = []
        for e in ents:
            for fld in e.fields:
                if fld.key == "centrality_prior":
                    cps.append(float(fld.value))
        assert any(c > 0 for c in cps)
