"""Tests for WS2 (CLI preset/hydrate) and WS5 (LLM-as-Router protocol)."""

from __future__ import annotations

import os
import tempfile

import pytest

from ctxpack.cli.main import main
from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    Section,
)


# ── Fixtures ──


def _golden_set_dir() -> str:
    d = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "ctxpack", "benchmarks", "ctxpack_eval", "corpus"
    ))
    if not os.path.isdir(d):
        pytest.skip("Golden set corpus not found")
    return d


def _make_l3_doc() -> CTXDocument:
    """Minimal L3 document for testing."""
    return CTXDocument(
        header=Header(
            magic="§CTX", version="1.0", layer=Layer.L3,
            status_fields=(KeyValue(key="DOMAIN", value="test"),),
            metadata=(
                KeyValue(key="COMPRESSED", value="2026-03-13"),
                KeyValue(key="SOURCE_TOKENS", value="~5000"),
            ),
        ),
        body=(
            Section(name="ENTITIES", children=(
                KeyValue(key="CUSTOMER", value="hub|4-fields|GOLDEN-SOURCE:CRM"),
                KeyValue(key="ORDER", value="leaf|3-fields|BELONGS-TO:CUSTOMER"),
            )),
            Section(name="PATTERNS", children=(
                KeyValue(key="LIFECYCLE", value="pending→confirmed→shipped→delivered"),
            )),
        ),
    )


def _make_l2_doc() -> CTXDocument:
    """Minimal L2 document for testing."""
    return CTXDocument(
        header=Header(
            magic="§CTX", version="1.0", layer=Layer.L2,
            status_fields=(KeyValue(key="DOMAIN", value="test"),),
        ),
        body=(
            Section(name="ENTITY-CUSTOMER", children=(
                KeyValue(key="IDENTIFIER", value="customer_id(UUID)"),
                KeyValue(key="PII", value="name+email+phone"),
            )),
            Section(name="ENTITY-ORDER", children=(
                KeyValue(key="IDENTIFIER", value="order_id(UUID)"),
                KeyValue(key="STATUS", value="pending→confirmed→shipped"),
            )),
        ),
    )


# ── WS5: System Prompt ──


class TestSystemPrompt:
    def test_build_system_prompt_lists_entities(self):
        from ctxpack.core.hydration_protocol import build_system_prompt

        prompt = build_system_prompt(_make_l2_doc())
        assert "ENTITY-CUSTOMER" in prompt
        assert "ENTITY-ORDER" in prompt

    def test_build_system_prompt_includes_identifiers(self):
        from ctxpack.core.hydration_protocol import build_system_prompt

        prompt = build_system_prompt(_make_l2_doc())
        # Should extract IDENTIFIER values
        assert "customer_id" in prompt
        assert "order_id" in prompt

    def test_build_system_prompt_includes_hydration_instructions(self):
        from ctxpack.core.hydration_protocol import build_system_prompt

        prompt = build_system_prompt(_make_l2_doc())
        assert "ctx/hydrate" in prompt
        assert "section" in prompt.lower()

    def test_build_system_prompt_without_instructions(self):
        from ctxpack.core.hydration_protocol import build_system_prompt

        prompt = build_system_prompt(_make_l2_doc(), hydration_instructions=False)
        # Detailed hydration instructions should be absent
        assert "Only hydrate" not in prompt
        # Entity names should still be there
        assert "ENTITY-CUSTOMER" in prompt

    def test_system_prompt_under_200_words(self):
        """Ultra-lean system prompt should be compact."""
        from ctxpack.core.hydration_protocol import build_system_prompt

        prompt = build_system_prompt(_make_l2_doc())
        word_count = len(prompt.split())
        assert word_count < 200, f"System prompt is {word_count} words, expected <200"

    def test_system_prompt_is_directory_index(self):
        """System prompt should be a directory, not a full document dump."""
        from ctxpack.core.hydration_protocol import build_system_prompt

        prompt = build_system_prompt(_make_l2_doc())
        # Should NOT contain full field values (that's L2's job)
        assert "PII" not in prompt or "id:" in prompt  # identifiers OK, but not field dumps
        assert "pending→confirmed" not in prompt  # status flow is detail, not index


class TestHydrationToolSchema:
    def test_schema_has_section_parameter(self):
        from ctxpack.core.hydration_protocol import build_hydration_tool_schema

        schema = build_hydration_tool_schema()
        props = schema["parameters"]["properties"]
        assert "section" in props

    def test_schema_has_required_section(self):
        from ctxpack.core.hydration_protocol import build_hydration_tool_schema

        schema = build_hydration_tool_schema()
        assert "section" in schema["parameters"]["required"]

    def test_schema_is_valid_structure(self):
        from ctxpack.core.hydration_protocol import build_hydration_tool_schema

        schema = build_hydration_tool_schema()
        assert "name" in schema
        assert "description" in schema
        assert "parameters" in schema
        assert schema["parameters"]["type"] == "object"


# ── WS2: CLI ──


class TestCLIPreset:
    def test_cli_pack_preset_conservative(self, capsys):
        corpus = _golden_set_dir()
        ret = main(["pack", corpus, "--preset", "conservative"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "§CTX" in out or "$CTX" in out

    def test_cli_pack_preset_aggressive(self, capsys):
        corpus = _golden_set_dir()
        ret = main(["pack", corpus, "--preset", "aggressive"])
        assert ret == 0

    def test_cli_pack_preset_invalid_errors(self, capsys):
        corpus = _golden_set_dir()
        with pytest.raises(SystemExit) as exc_info:
            main(["pack", corpus, "--preset", "invalid"])
        assert exc_info.value.code != 0


class TestCLIHydrate:
    def _pack_to_file(self) -> str:
        """Pack golden set to a temp file, return path."""
        corpus = _golden_set_dir()
        fd, out = tempfile.mkstemp(suffix=".ctx")
        os.close(fd)
        main(["pack", corpus, "-o", out])
        return out

    def test_cli_hydrate_list(self, capsys):
        ctx_file = self._pack_to_file()
        try:
            ret = main(["hydrate", ctx_file, "--list"])
            assert ret == 0
            out = capsys.readouterr().out
            assert "ENTITY" in out or "sections" in out.lower()
        finally:
            os.unlink(ctx_file)

    def test_cli_hydrate_section(self, capsys):
        ctx_file = self._pack_to_file()
        try:
            ret = main(["hydrate", ctx_file, "--section", "ENTITY-PARSER"])
            assert ret == 0
        finally:
            os.unlink(ctx_file)

    def test_cli_hydrate_query(self, capsys):
        ctx_file = self._pack_to_file()
        try:
            ret = main(["hydrate", ctx_file, "--query", "parser serializer"])
            assert ret == 0
        finally:
            os.unlink(ctx_file)
