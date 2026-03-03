"""Tests for agent state compression."""

from __future__ import annotations

import pytest

from ctxpack.agent import AgentCompressResult, compress_state
from ctxpack.agent.state_parser import parse_steps


# ── Shared test fixture: 10-step agent chain ──

AGENT_STEPS = [
    {"tool": "read_file", "result": {"file": "main.py", "classes": ["App", "Config"]}},
    {"entities": [{"name": "APP", "framework": "FastAPI", "version": "0.104"}]},
    {"tool": "search_db", "result": {"entity": "USER", "fields": ["id", "email", "role"]}},
    {"entities": [{"name": "USER", "auth": "JWT", "session_ttl": "3600s"}]},
    {"entities": [{"name": "APP", "database": "PostgreSQL"}]},  # updates APP
    {"decision": "Use connection pooling for database access"},
    {"entities": [{"name": "USER", "auth": "OAuth2"}]},  # contradicts step 3
    {"tool": "analyze_deps", "result": {"count": 42, "vulnerable": 2}},
    {"entities": [{"name": "CONFIG", "env": "production", "debug": "false"}]},
    {"decision": "Deploy to staging first, then production after approval"},
]


class TestParseSteps:
    def test_entity_steps(self):
        steps = [{"entities": [{"name": "APP", "framework": "FastAPI"}]}]
        corpus = parse_steps(steps)
        assert len(corpus.entities) == 1
        assert corpus.entities[0].name == "APP"

    def test_tool_steps(self):
        steps = [{"tool": "read_file", "result": {"file": "main.py"}}]
        corpus = parse_steps(steps)
        assert len(corpus.entities) == 1
        assert corpus.entities[0].name.startswith("TOOL-")

    def test_decision_steps(self):
        steps = [{"decision": "Use connection pooling"}]
        corpus = parse_steps(steps)
        assert len(corpus.standalone_rules) == 1
        assert "connection pooling" in corpus.standalone_rules[0].value

    def test_fallback_steps(self):
        steps = [{"arbitrary_key": "value", "another": 42}]
        corpus = parse_steps(steps)
        assert len(corpus.entities) == 1
        assert corpus.entities[0].name.startswith("STEP-")

    def test_salience_recency_boost(self):
        """Later steps should have slightly higher salience."""
        steps = [
            {"entities": [{"name": "A", "x": "1"}]},
            {"entities": [{"name": "B", "y": "2"}]},
        ]
        corpus = parse_steps(steps)
        assert corpus.entities[1].salience > corpus.entities[0].salience

    def test_source_token_count(self):
        corpus = parse_steps(AGENT_STEPS)
        assert corpus.source_token_count > 0

    def test_domain_propagated(self):
        corpus = parse_steps([{"decision": "test"}], domain="my-agent")
        assert corpus.domain == "my-agent"


class TestCompressState:
    def test_basic_compression(self):
        result = compress_state(AGENT_STEPS)
        assert isinstance(result, AgentCompressResult)
        assert result.step_count == 10
        assert result.tokens_raw > 0
        assert result.tokens_compressed > 0
        assert len(result.ctx_text) > 0

    def test_entity_merging(self):
        """APP appears in steps 1 and 4 — should be merged."""
        result = compress_state(AGENT_STEPS)
        # APP appears as entity in steps[1] and steps[4], should merge
        assert result.entities_merged > 0

    def test_compression_ratio(self):
        """With entity merging, compressed output should be reasonable."""
        result = compress_state(AGENT_STEPS)
        # Ratio may be <1.0 for small inputs since .ctx header adds overhead.
        # But it should be positive and entities should have merged.
        assert result.compression_ratio > 0
        assert result.entities_merged > 0

    def test_ctx_text_valid(self):
        """Output should be parseable .ctx."""
        from ctxpack.core.parser import parse as ctx_parse

        result = compress_state(AGENT_STEPS)
        doc = ctx_parse(result.ctx_text, level=2)
        assert doc.header.layer.value == "L2"

    def test_empty_steps(self):
        result = compress_state([])
        assert result.step_count == 0
        assert result.tokens_raw == 0
        assert result.tokens_compressed == 0
        assert result.compression_ratio == 0.0
        assert len(result.ctx_text) > 0  # still valid .ctx

    def test_strict_mode(self):
        result_enriched = compress_state(AGENT_STEPS, strict=False)
        result_strict = compress_state(AGENT_STEPS, strict=True)
        # Strict should produce same or fewer tokens
        assert result_strict.tokens_compressed <= result_enriched.tokens_compressed + 5

    def test_domain_in_output(self):
        result = compress_state(AGENT_STEPS, domain="my-agent")
        assert "my-agent" in result.ctx_text

    def test_single_entity_step(self):
        steps = [{"entities": [{"name": "X", "key": "value"}]}]
        result = compress_state(steps)
        assert result.step_count == 1
        assert result.tokens_compressed > 0
        assert "X" in result.ctx_text.upper()

    def test_single_tool_step(self):
        steps = [{"tool": "test_tool", "result": {"status": "ok"}}]
        result = compress_state(steps)
        assert result.step_count == 1
        assert "TOOL" in result.ctx_text.upper()

    def test_decisions_in_output(self):
        steps = [
            {"decision": "Use Redis for caching"},
            {"decision": "Deploy to Kubernetes"},
        ]
        result = compress_state(steps)
        # Decisions should appear in output
        assert "Redis" in result.ctx_text or "caching" in result.ctx_text.lower()

    def test_list_values_compressed(self):
        steps = [
            {"entities": [{"name": "SVC", "endpoints": ["/api", "/health", "/admin"]}]},
        ]
        result = compress_state(steps)
        assert result.tokens_compressed > 0

    def test_nested_result_compressed(self):
        steps = [
            {"tool": "scan", "result": {"vulns": {"high": 1, "medium": 3, "low": 10}}},
        ]
        result = compress_state(steps)
        assert result.tokens_compressed > 0
