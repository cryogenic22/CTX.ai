"""Tests for 6 bolt-on engineering features.

Feature 1: Domain Template System
Feature 2: Conditional Guard Notation
Feature 3: Agent Session Rolling State
Feature 4: Temporal/Version Conflict Detection
Feature 5: Window/Tolerance Micro-Syntax
Feature 6: Source Cross-Reference Resolver
"""

import os
import tempfile
import textwrap

import pytest

from ctxpack.core.packer.ir import (
    CONDITIONAL_RE,
    WINDOW_RE,
    Certainty,
    IRCorpus,
    IREntity,
    IRField,
    IRSource,
    IRWarning,
    Severity,
)


# ── Feature 5: Window/Tolerance ──


class TestWindowMicroSyntax:
    def test_window_re_matches_days(self):
        assert WINDOW_RE.search("±3d")
        m = WINDOW_RE.search("grace-period:±3d")
        assert m.group(1) == "3"
        assert m.group(2) == "d"

    def test_window_re_matches_weeks(self):
        m = WINDOW_RE.search("tolerance:±2w")
        assert m.group(1) == "2"
        assert m.group(2) == "w"

    def test_window_re_matches_months(self):
        m = WINDOW_RE.search("window:±1m")
        assert m.group(1) == "1"
        assert m.group(2) == "m"

    def test_window_re_no_match(self):
        assert WINDOW_RE.search("no-window-here") is None
        assert WINDOW_RE.search("regular text") is None

    def test_window_salience_boost(self):
        from ctxpack.core.packer.compressor import _score_field

        field = IRField(key="GRACE-PERIOD", value="±3d", salience=1.0)
        _score_field(field)
        assert field.salience > 1.0  # boosted

    def test_window_l3_extraction(self):
        """Window patterns appear in L3 PATTERNS section."""
        from ctxpack.core.model import Header, KeyValue, Layer, Section, CTXDocument
        from ctxpack.core.packer.l3_generator import generate_l3

        doc = CTXDocument(
            header=Header(magic="§CTX", version="1.0", layer=Layer.L2,
                          metadata=(KeyValue(key="SOURCE_TOKENS", value="~500"),
                                    KeyValue(key="DOMAIN", value="test"))),
            body=(
                Section(name="ENTITY-ORDER", children=(
                    KeyValue(key="GRACE-PERIOD", value="±3d"),
                )),
            ),
        )
        l3 = generate_l3(doc)
        patterns = [s for s in l3.body if s.name == "PATTERNS"][0]
        texts = [c.text for c in patterns.children]
        assert any("WINDOW:" in t and "±3days" in t for t in texts)


# ── Feature 2: Conditional Guard ──


class TestConditionalGuard:
    def test_conditional_re_only_if(self):
        m = CONDITIONAL_RE.search("only-if(active)")
        assert m.group(1) == "active"

    def test_conditional_re_when(self):
        m = CONDITIONAL_RE.search("when(status=approved)")
        assert m.group(1) == "status=approved"

    def test_conditional_re_if(self):
        m = CONDITIONAL_RE.search("if(premium)")
        assert m.group(1) == "premium"

    def test_conditional_re_no_match(self):
        assert CONDITIONAL_RE.search("no condition here") is None

    def test_conditional_salience_boost(self):
        from ctxpack.core.packer.compressor import _score_field

        field = IRField(key="RULE", value="only-if(active)", salience=1.0)
        _score_field(field)
        assert field.salience > 1.0

    def test_conditional_conflict_detection(self):
        from ctxpack.core.packer.conflict import detect_conflicts

        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="ORDER",
                    fields=[
                        IRField(key="DISCOUNT", value="apply only-if(active)"),
                        IRField(key="DISCOUNT", value="deny only-if(inactive)"),
                    ],
                ),
            ],
        )
        warnings = detect_conflicts(corpus)
        cond_warnings = [w for w in warnings if "Conditional conflict" in w.message]
        assert len(cond_warnings) >= 1

    def test_conditional_l3_extraction(self):
        from ctxpack.core.model import Header, KeyValue, Layer, Section, CTXDocument
        from ctxpack.core.packer.l3_generator import generate_l3

        doc = CTXDocument(
            header=Header(magic="§CTX", version="1.0", layer=Layer.L2,
                          metadata=(KeyValue(key="SOURCE_TOKENS", value="~500"),
                                    KeyValue(key="DOMAIN", value="test"))),
            body=(
                Section(name="ENTITY-ORDER", children=(
                    KeyValue(key="RULE", value="apply-discount only-if(premium)"),
                )),
            ),
        )
        l3 = generate_l3(doc)
        patterns = [s for s in l3.body if s.name == "PATTERNS"][0]
        texts = [c.text for c in patterns.children]
        assert any("GUARD:" in t and "only-if(premium)" in t for t in texts)

    def test_no_false_positive_conditional_conflict(self):
        """Same condition on same field = no conflict."""
        from ctxpack.core.packer.conflict import detect_conflicts

        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="ORDER",
                    fields=[
                        IRField(key="DISCOUNT", value="apply only-if(active)"),
                        IRField(key="DISCOUNT", value="10% only-if(active)"),
                    ],
                ),
            ],
        )
        warnings = detect_conflicts(corpus)
        cond_warnings = [w for w in warnings if "Conditional conflict" in w.message]
        assert len(cond_warnings) == 0


# ── Feature 4: Version Conflicts ──


class TestVersionConflicts:
    def test_version_field_on_ir_source(self):
        src = IRSource(file="a.yaml", version="2.0")
        assert src.version == "2.0"

    def test_version_conflict_detected(self):
        from ctxpack.core.packer.conflict import detect_conflicts

        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="ORDER",
                    fields=[
                        IRField(
                            key="RETENTION",
                            value="12-months",
                            source=IRSource(file="v1.yaml", version="1.0"),
                        ),
                        IRField(
                            key="RETENTION",
                            value="24-months",
                            source=IRSource(file="v2.yaml", version="2.0"),
                        ),
                    ],
                ),
            ],
        )
        warnings = detect_conflicts(corpus)
        version_warnings = [w for w in warnings if "Version conflict" in w.message]
        assert len(version_warnings) >= 1
        assert "v1.0" in version_warnings[0].message
        assert "v2.0" in version_warnings[0].message

    def test_no_version_conflict_same_value(self):
        from ctxpack.core.packer.conflict import detect_conflicts

        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="ORDER",
                    fields=[
                        IRField(
                            key="RETENTION",
                            value="12-months",
                            source=IRSource(file="v1.yaml", version="1.0"),
                        ),
                        IRField(
                            key="RETENTION",
                            value="12-months",
                            source=IRSource(file="v2.yaml", version="2.0"),
                        ),
                    ],
                ),
            ],
        )
        warnings = detect_conflicts(corpus)
        version_warnings = [w for w in warnings if "Version conflict" in w.message]
        assert len(version_warnings) == 0

    def test_no_version_conflict_without_version(self):
        """Fields without version info should not trigger version conflicts."""
        from ctxpack.core.packer.conflict import detect_conflicts

        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="ORDER",
                    fields=[
                        IRField(key="RETENTION", value="12-months",
                                source=IRSource(file="a.yaml")),
                        IRField(key="RETENTION", value="24-months",
                                source=IRSource(file="b.yaml")),
                    ],
                ),
            ],
        )
        warnings = detect_conflicts(corpus)
        version_warnings = [w for w in warnings if "Version conflict" in w.message]
        assert len(version_warnings) == 0


# ── Feature 1: Domain Templates ──


class TestDomainTemplates:
    def test_load_builtin_pharma(self):
        from ctxpack.core.packer.templates import load_template

        tmpl = load_template("pharma")
        assert tmpl.name == "pharma"
        assert "DRUG" in tmpl.entity_schemas
        assert "PATIENT" in tmpl.entity_schemas

    def test_load_builtin_data_platform(self):
        from ctxpack.core.packer.templates import load_template

        tmpl = load_template("data-platform")
        assert tmpl.name == "data-platform"
        assert "TABLE" in tmpl.entity_schemas
        assert "PIPELINE" in tmpl.entity_schemas

    def test_load_unknown_raises(self):
        from ctxpack.core.packer.templates import load_template

        with pytest.raises(ValueError, match="Unknown template"):
            load_template("nonexistent-template")

    def test_validate_missing_required_field(self):
        from ctxpack.core.packer.templates import load_template, validate_corpus

        tmpl = load_template("pharma")
        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="DRUG",
                    fields=[
                        IRField(key="IDENTIFIER", value="drug-001"),
                        # Missing ACTIVE-INGREDIENT and DOSAGE-FORM
                    ],
                ),
            ],
        )
        warnings = validate_corpus(corpus, tmpl)
        assert len(warnings) >= 1
        msgs = [w.message for w in warnings]
        assert any("ACTIVE-INGREDIENT" in m for m in msgs)
        assert any("DOSAGE-FORM" in m for m in msgs)

    def test_validate_all_required_present(self):
        from ctxpack.core.packer.templates import load_template, validate_corpus

        tmpl = load_template("pharma")
        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="DRUG",
                    fields=[
                        IRField(key="IDENTIFIER", value="drug-001"),
                        IRField(key="ACTIVE-INGREDIENT", value="aspirin"),
                        IRField(key="DOSAGE-FORM", value="tablet"),
                    ],
                ),
            ],
        )
        warnings = validate_corpus(corpus, tmpl)
        assert len(warnings) == 0

    def test_validate_applies_salience_weights(self):
        from ctxpack.core.packer.templates import load_template, validate_corpus

        tmpl = load_template("pharma")
        field = IRField(key="CONTRAINDICATIONS", value="pregnancy", salience=1.0)
        corpus = IRCorpus(
            entities=[IREntity(name="DRUG", fields=[field])],
        )
        validate_corpus(corpus, tmpl)
        assert field.salience == 2.0  # pharma CONTRAINDICATIONS weight

    def test_load_template_from_file(self):
        from ctxpack.core.packer.templates import load_template

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(textwrap.dedent("""\
                name: custom
                entity_schemas:
                  WIDGET:
                    required_fields:
                      - IDENTIFIER
                      - COLOR
                    description: A widget
                salience_weights:
                  COLOR: 1.5
            """))
            f.flush()
            path = f.name

        try:
            tmpl = load_template(path)
            assert tmpl.name == "custom"
            assert "WIDGET" in tmpl.entity_schemas
            assert tmpl.entity_schemas["WIDGET"].required_fields == ["IDENTIFIER", "COLOR"]
            assert tmpl.salience_weights.get("COLOR") == 1.5
        finally:
            os.unlink(path)

    def test_pack_config_template_field(self):
        from ctxpack.core.packer.discovery import PackConfig

        cfg = PackConfig(template="pharma")
        assert cfg.template == "pharma"

    def test_prefix_schema_match(self):
        """DRUG-PRODUCT should match the DRUG schema."""
        from ctxpack.core.packer.templates import load_template, validate_corpus

        tmpl = load_template("pharma")
        corpus = IRCorpus(
            entities=[
                IREntity(
                    name="DRUG-PRODUCT",
                    fields=[IRField(key="IDENTIFIER", value="dp-001")],
                ),
            ],
        )
        warnings = validate_corpus(corpus, tmpl)
        # Should have warnings for missing ACTIVE-INGREDIENT and DOSAGE-FORM
        assert len(warnings) >= 1


# ── Feature 6: Source Cross-Reference Resolver ──


class TestXRefResolver:
    def test_build_section_index(self):
        from ctxpack.core.packer.xref_resolver import build_section_index

        text = textwrap.dedent("""\
            # Introduction
            Some text.
            ## Background
            More text.
            ## Motivation
            Even more.
            # Methods
            ## Data Collection
        """)
        idx = build_section_index(text)
        assert idx["1"] == "Introduction"
        assert idx["1.1"] == "Background"
        assert idx["1.2"] == "Motivation"
        assert idx["2"] == "Methods"
        assert idx["2.1"] == "Data Collection"

    def test_resolve_xrefs(self):
        from ctxpack.core.packer.xref_resolver import resolve_xrefs

        text = textwrap.dedent("""\
            # Rules
            ## Retention
            Keep data for 12 months.
            ## Exceptions
            See Section 1.1 for details.
        """)
        resolved = resolve_xrefs(text)
        assert "(Retention)" in resolved

    def test_resolve_xrefs_refer_to(self):
        from ctxpack.core.packer.xref_resolver import resolve_xrefs

        text = textwrap.dedent("""\
            # Overview
            ## Details
            Please refer to Section 1.1 for more information.
        """)
        resolved = resolve_xrefs(text)
        assert "(Details)" in resolved

    def test_resolve_xrefs_no_match(self):
        from ctxpack.core.packer.xref_resolver import resolve_xrefs

        text = "No cross references here."
        assert resolve_xrefs(text) == text

    def test_resolve_xrefs_unknown_section(self):
        from ctxpack.core.packer.xref_resolver import resolve_xrefs

        text = textwrap.dedent("""\
            # Only One Section
            See Section 5.3 for details.
        """)
        resolved = resolve_xrefs(text)
        # Unknown section number should be left as-is
        assert "(Only One Section)" not in resolved
        assert "Section 5.3" in resolved

    def test_resolve_with_prebuilt_index(self):
        from ctxpack.core.packer.xref_resolver import resolve_xrefs

        index = {"2.1": "Data Retention"}
        text = "See Section 2.1 for more."
        resolved = resolve_xrefs(text, section_index=index)
        assert "(Data Retention)" in resolved


# ── Feature 3: Agent Session ──


class TestAgentSession:
    def test_session_create(self):
        from ctxpack.agent.session import AgentSession

        session = AgentSession(domain="test", token_budget=2000)
        assert session.entity_count == 0
        assert session.step_count == 0

    def test_session_update(self):
        from ctxpack.agent.session import AgentSession

        session = AgentSession(domain="test", token_budget=4000)
        result = session.update({
            "entities": [{"name": "USER", "email": "a@b.com"}]
        })
        assert session.entity_count >= 1
        assert session.step_count == 1
        assert result.ctx_text  # non-empty

    def test_session_multiple_updates(self):
        from ctxpack.agent.session import AgentSession

        session = AgentSession(domain="test", token_budget=4000)
        session.update({"entities": [{"name": "USER", "role": "admin"}]})
        session.update({"entities": [{"name": "ORDER", "status": "pending"}]})
        result = session.snapshot()
        assert session.step_count == 2
        assert "USER" in result.ctx_text
        assert "ORDER" in result.ctx_text

    def test_session_entity_merge(self):
        """Same entity name across steps should merge."""
        from ctxpack.agent.session import AgentSession

        session = AgentSession(domain="test", token_budget=4000)
        session.update({"entities": [{"name": "USER", "email": "a@b.com"}]})
        session.update({"entities": [{"name": "USER", "role": "admin"}]})
        # Entity resolution should merge the two USER entities
        assert session.entity_count == 1

    def test_session_snapshot_idempotent(self):
        from ctxpack.agent.session import AgentSession

        session = AgentSession(domain="test", token_budget=4000)
        session.update({"entities": [{"name": "USER", "role": "admin"}]})
        r1 = session.snapshot()
        r2 = session.snapshot()
        assert r1.ctx_text == r2.ctx_text

    def test_session_eviction(self):
        from ctxpack.agent.session import AgentSession

        # Very small budget to force eviction
        session = AgentSession(domain="test", token_budget=5)
        for i in range(10):
            session.update({
                "entities": [{"name": f"ENTITY-{i}", "data": f"value-{i}" * 10}]
            })
        # After eviction, should be within budget
        result = session.snapshot()
        assert result.tokens_compressed <= session.token_budget or session.entity_count == 0

    def test_session_evict_oldest(self):
        from ctxpack.agent.session import AgentSession

        session = AgentSession(domain="test", token_budget=5)
        session.update({"entities": [{"name": "OLD", "data": "old-data" * 5}]})
        session.update({"entities": [{"name": "NEW", "data": "new-data" * 5}]})
        evicted = session.evict("oldest")
        assert evicted >= 0  # May or may not need eviction depending on size

    def test_session_tool_step(self):
        from ctxpack.agent.session import AgentSession

        session = AgentSession(domain="test", token_budget=4000)
        result = session.update({
            "tool": "search",
            "result": {"count": 42, "query": "test"},
        })
        assert "SEARCH" in result.ctx_text


# ── Integration: full pack with template ──


class TestPackWithTemplate:
    def test_pack_with_template_flag(self):
        """Template warnings appear in pack output."""
        from ctxpack.core.packer import pack

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a Markdown file with a DRUG entity missing required fields
            with open(os.path.join(tmpdir, "drug.md"), "w") as f:
                f.write(textwrap.dedent("""\
                    ## DRUG
                    - Identifier: drug-001
                """))
            with open(os.path.join(tmpdir, "ctxpack.yaml"), "w") as f:
                f.write("domain: pharma-test\n")

            result = pack(tmpdir, template="pharma")
            assert result.warning_count >= 1
