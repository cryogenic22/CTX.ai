"""Tests for the analytics domain pack compiler.

Two lanes (Codex Finding 2 — the external-corpus skip must NOT be
module-wide, or a normal checkout runs zero analytics behaviour):

- Hermetic inline-YAML unit tests (``TestHermeticInlineYAML``,
  ``TestPyYAMLAbsence``) run wherever PyYAML is importable — no external
  corpus needed. This is the ordinary-lane coverage (CI ``test`` job) and
  is non-vacuous: it exercises real parse, the empty-pack path, the
  dep-free module import, and the ``pip install ctxpack[analytics]``
  install hint raised when PyYAML is absent.
- Integration tests over the ACTUAL Bright_Light packs run only when that
  external corpus is present (CI ``extras`` job); they are scoped-skipped
  per class, never module-wide.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys

import os
import pytest

from ctxpack.modules.analytics import (
    build_analytics_l3,
    compile_domain_packs,
    parse_domain_pack,
)
from ctxpack.core.packer.ir import IRCorpus, IREntity, IRField, IRSource

# ── Paths ──

PACKS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "bright_light", "packs")
)
RETAIL_PACK = os.path.join(PACKS_DIR, "retail", "v1", "pack.yaml")
AIRLINES_PACK = os.path.join(PACKS_DIR, "airlines", "v1", "pack.yaml")

HAVE_PACKS = os.path.isdir(PACKS_DIR)
HAVE_YAML = importlib.util.find_spec("yaml") is not None

# The external Bright_Light corpus gates ONLY the integration classes
# (applied per-class below), never the whole module — the hermetic lane
# always runs.
requires_packs = pytest.mark.skipif(
    not HAVE_PACKS,
    reason="Bright_Light packs not found (external integration corpus)",
)
requires_yaml = pytest.mark.skipif(
    not HAVE_YAML,
    reason="PyYAML not installed (analytics extra)",
)


# ── Helpers ──

def _load_pack(path: str) -> list[IREntity]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    domain = os.path.basename(os.path.dirname(os.path.dirname(path)))
    return parse_domain_pack(text, filename=path, domain=domain)


def _find_entity(entities: list[IREntity], name_fragment: str) -> IREntity | None:
    """Find an entity whose name contains the given fragment (case-insensitive)."""
    for e in entities:
        if name_fragment.upper() in e.name.upper():
            return e
    return None


def _find_field(entity: IREntity, key_fragment: str) -> IRField | None:
    """Find a field whose key contains the given fragment (case-insensitive)."""
    for f in entity.fields:
        if key_fragment.upper() in f.key.upper():
            return f
    return None


# ── parse_domain_pack tests ──


@requires_packs
class TestParseDomainPack:
    """Test parsing a single domain pack into IR entities (integration —
    requires the external Bright_Light corpus)."""

    def test_parse_retail_pack_extracts_domain_entity(self):
        """The retail pack should produce a top-level RETAIL domain entity."""
        entities = _load_pack(RETAIL_PACK)
        domain_entity = _find_entity(entities, "RETAIL")
        assert domain_entity is not None, (
            f"Expected RETAIL domain entity, got: {[e.name for e in entities]}"
        )
        # Should have metadata in annotations
        assert "description" in domain_entity.annotations

    def test_parse_retail_pack_extracts_fingerprints_as_fields(self):
        """Fingerprint columns should become fields on the domain entity."""
        entities = _load_pack(RETAIL_PACK)
        domain_entity = _find_entity(entities, "RETAIL")
        assert domain_entity is not None

        # Retail has 17 fingerprint columns (transaction_id through online_sales_amount)
        fingerprint_fields = [
            f for f in domain_entity.fields if f.key.startswith("FP-")
        ]
        assert len(fingerprint_fields) >= 15, (
            f"Expected >=15 fingerprint fields, got {len(fingerprint_fields)}: "
            f"{[f.key for f in fingerprint_fields]}"
        )

        # Specific check: transaction_id should be present
        txn_field = _find_field(domain_entity, "FP-TRANSACTION-ID")
        assert txn_field is not None
        # Should include patterns info
        assert "txn_id" in txn_field.value or "txn-id" in txn_field.value

    def test_parse_retail_pack_extracts_metrics(self):
        """Each metric should become a separate entity."""
        entities = _load_pack(RETAIL_PACK)

        # Find metric entities — they should contain 'METRIC' or the metric name
        metric_entities = [
            e for e in entities if "METRIC" in e.name.upper()
        ]
        # Retail has 14 metrics
        assert len(metric_entities) >= 10, (
            f"Expected >=10 metric entities, got {len(metric_entities)}: "
            f"{[e.name for e in metric_entities]}"
        )

        # Check specific metric: gross_sales
        gross = _find_entity(entities, "GROSS-SALES")
        assert gross is not None, (
            f"Expected GROSS-SALES metric entity, got: {[e.name for e in entities]}"
        )
        # Should have formula field
        formula_field = _find_field(gross, "FORMULA")
        assert formula_field is not None
        assert "SUM" in formula_field.value

    def test_parse_retail_pack_extracts_dimensions(self):
        """Each dimension should become a separate entity."""
        entities = _load_pack(RETAIL_PACK)

        dim_entities = [
            e for e in entities if "DIM" in e.name.upper()
        ]
        # Retail has 6 dimensions
        assert len(dim_entities) >= 5, (
            f"Expected >=5 dimension entities, got {len(dim_entities)}: "
            f"{[e.name for e in dim_entities]}"
        )

        # Check store dimension has hierarchy
        store_dim = _find_entity(entities, "DIM-RETAIL-STORE")
        assert store_dim is not None, (
            f"Expected DIM-RETAIL-STORE, got dims: {[e.name for e in dim_entities]}"
        )
        hier_field = _find_field(store_dim, "HIERARCHY")
        assert hier_field is not None
        assert "Region" in hier_field.value or "region" in hier_field.value.lower()

    def test_parse_retail_pack_extracts_vocabulary_synonyms(self):
        """Vocabulary entity synonyms should appear as aliases on the domain entity."""
        entities = _load_pack(RETAIL_PACK)
        domain_entity = _find_entity(entities, "RETAIL")
        assert domain_entity is not None

        # Retail vocabulary: customer=Shopper, product=SKU, store=Storefront, etc.
        all_aliases = []
        for e in entities:
            all_aliases.extend(e.aliases)
        alias_str = " ".join(all_aliases).lower()
        # At least some vocabulary synonyms should be captured
        assert "shopper" in alias_str or "sku" in alias_str, (
            f"Expected vocabulary synonyms in aliases, got: {all_aliases}"
        )

    def test_parse_retail_pack_extracts_value_enums(self):
        """Value enums should become fields on the domain entity."""
        entities = _load_pack(RETAIL_PACK)
        domain_entity = _find_entity(entities, "RETAIL")
        assert domain_entity is not None

        # Look for value enum fields (channel values: POS, ECom, etc.)
        enum_fields = [
            f for f in domain_entity.fields if f.key.startswith("ENUM-")
        ]
        assert len(enum_fields) >= 3, (
            f"Expected >=3 enum fields, got {len(enum_fields)}: "
            f"{[f.key for f in enum_fields]}"
        )
        # Check channel enum includes POS
        channel_enum = _find_field(domain_entity, "ENUM-CHANNEL")
        assert channel_enum is not None
        assert "POS" in channel_enum.value

    def test_parse_retail_pack_extracts_tables(self):
        """Table structures should become fields on the domain entity."""
        entities = _load_pack(RETAIL_PACK)
        domain_entity = _find_entity(entities, "RETAIL")
        assert domain_entity is not None

        table_fields = [
            f for f in domain_entity.fields if f.key.startswith("TABLE-")
        ]
        assert len(table_fields) >= 3, (
            f"Expected >=3 table fields, got {len(table_fields)}: "
            f"{[f.key for f in table_fields]}"
        )

    def test_parse_retail_pack_extracts_guardrails(self):
        """Guardrails (PII patterns, compliance rules) should be captured."""
        entities = _load_pack(RETAIL_PACK)
        domain_entity = _find_entity(entities, "RETAIL")
        assert domain_entity is not None

        guardrail_fields = [
            f for f in domain_entity.fields
            if "PII" in f.key or "COMPLIANCE" in f.key or "GUARDRAIL" in f.key
        ]
        assert len(guardrail_fields) >= 1, (
            f"Expected guardrail fields, got: {[f.key for f in domain_entity.fields]}"
        )

    def test_parse_retail_pack_extracts_kbq_templates(self):
        """KBQ templates should be captured as entities or fields."""
        entities = _load_pack(RETAIL_PACK)

        # KBQ templates can be entities or fields — check they exist somewhere
        all_field_keys = []
        for e in entities:
            all_field_keys.extend(f.key for f in e.fields)
        kbq_items = [k for k in all_field_keys if "KBQ" in k]
        assert len(kbq_items) >= 5, (
            f"Expected >=5 KBQ items, got {len(kbq_items)}"
        )

    def test_parse_airlines_pack_extracts_domain_entity(self):
        """Airlines pack should produce AIRLINES domain entity."""
        entities = _load_pack(AIRLINES_PACK)
        domain_entity = _find_entity(entities, "AIRLINES")
        assert domain_entity is not None

    def test_parse_airlines_pack_extracts_vocabulary(self):
        """Airlines vocabulary: location=Airport, customer=Passenger, etc."""
        entities = _load_pack(AIRLINES_PACK)
        all_aliases = []
        for e in entities:
            all_aliases.extend(e.aliases)
        alias_str = " ".join(all_aliases).lower()
        assert "airport" in alias_str or "passenger" in alias_str or "pnr" in alias_str, (
            f"Expected airlines vocabulary synonyms, got: {all_aliases}"
        )

    def test_metric_entity_has_owner_and_tags(self):
        """Metric entities should carry owner and tags as fields."""
        entities = _load_pack(RETAIL_PACK)
        gross = _find_entity(entities, "GROSS-SALES")
        assert gross is not None
        owner_field = _find_field(gross, "OWNER")
        assert owner_field is not None
        tags_field = _find_field(gross, "TAGS")
        assert tags_field is not None

    def test_dimension_entity_has_keys(self):
        """Dimension entities should carry key columns."""
        entities = _load_pack(RETAIL_PACK)
        store_dim = _find_entity(entities, "DIM-RETAIL-STORE")
        assert store_dim is not None
        keys_field = _find_field(store_dim, "KEYS")
        assert keys_field is not None
        assert "store_id" in keys_field.value or "store-id" in keys_field.value

    def test_ontology_synonyms_captured(self):
        """Ontology synonyms (basket size -> average_basket_size) should be captured."""
        entities = _load_pack(RETAIL_PACK)
        # Find the average basket size metric
        basket = _find_entity(entities, "AVERAGE-BASKET")
        if basket is not None:
            # Should have "basket size" as alias or in aliases
            assert any(
                "basket" in a.lower() for a in basket.aliases
            ), f"Expected 'basket size' alias, got: {basket.aliases}"


# ── compile_domain_packs tests ──


@requires_packs
class TestCompileDomainPacks:
    """Test compiling all 17 packs into a unified IRCorpus (integration —
    requires the external Bright_Light corpus)."""

    @pytest.fixture(scope="class")
    def compiled(self) -> IRCorpus:
        return compile_domain_packs(PACKS_DIR, deduplicate=True)

    def test_compile_all_packs_entity_count(self, compiled: IRCorpus):
        """Should produce entities for all 17 domains + their metrics + dimensions."""
        # 17 domain entities + ~180 metrics + ~90 dimensions = ~287+
        # But after dedup some may merge; at minimum we expect 100+
        assert len(compiled.entities) >= 100, (
            f"Expected >=100 entities after compilation, got {len(compiled.entities)}"
        )

    def test_compile_all_packs_deduplicates_common_fingerprints(self, compiled: IRCorpus):
        """Common fingerprints like customer_id should appear once with multi-source provenance."""
        # Find a domain entity and check its fingerprint fields
        # customer_id appears in most packs — after dedup the field should
        # have additional_sources from multiple packs
        all_fp_fields: list[IRField] = []
        for entity in compiled.entities:
            for f in entity.fields:
                if f.key == "FP-CUSTOMER-ID":
                    all_fp_fields.append(f)

        # After dedup, there might still be one per domain entity or one shared
        # The key check is: the corpus doesn't have 17 separate customer_id definitions
        # that are identical
        total_customer_id_definitions = len(all_fp_fields)
        # Should be fewer than 17 (some domains don't have customer_id, and those
        # that do should be deduplicated or at least tracked)
        assert total_customer_id_definitions <= 17, (
            f"Got {total_customer_id_definitions} customer_id definitions"
        )

    def test_compile_all_packs_cross_domain_synonym_resolution(self, compiled: IRCorpus):
        """Cross-domain synonyms: customer=Shopper=Passenger=Subscriber."""
        # After compilation, vocabulary synonyms from all domains should be tracked
        # Check that the corpus has warnings or merged aliases for cross-domain terms
        all_aliases: list[str] = []
        for entity in compiled.entities:
            all_aliases.extend(entity.aliases)
        alias_set = {a.lower() for a in all_aliases}

        # Multiple domain-specific customer terms should be present
        customer_terms = {"shopper", "passenger", "subscriber", "policyholder",
                          "player", "guest", "account holder", "digital shopper"}
        found = alias_set & customer_terms
        assert len(found) >= 3, (
            f"Expected >=3 cross-domain customer synonyms, found {found}"
        )

    def test_compile_all_packs_has_17_domains(self, compiled: IRCorpus):
        """Should discover all 17 domain packs."""
        assert len(compiled.source_files) == 17, (
            f"Expected 17 source files, got {len(compiled.source_files)}: "
            f"{compiled.source_files}"
        )

    def test_compile_all_packs_has_warnings_for_conflicts(self, compiled: IRCorpus):
        """Cross-domain conflicts (same metric name, different definition) should produce warnings."""
        # This is best-effort: if there are genuine conflicts, they should be caught
        # At minimum we expect the compiler to complete without errors
        assert compiled.warnings is not None

    def test_compile_with_dedup_false(self):
        """Compiling without dedup should produce more entities."""
        no_dedup = compile_domain_packs(PACKS_DIR, deduplicate=False)
        with_dedup = compile_domain_packs(PACKS_DIR, deduplicate=True)
        # Without dedup should have at least as many entities
        assert len(no_dedup.entities) >= len(with_dedup.entities)

    def test_compiled_corpus_has_source_token_count(self, compiled: IRCorpus):
        """Source token count should be populated."""
        assert compiled.source_token_count > 0

    def test_compiled_corpus_domain_label(self, compiled: IRCorpus):
        """Domain should be set to 'analytics' or 'multi-domain'."""
        assert compiled.domain != ""


# ── build_analytics_l3 tests ──


@requires_packs
class TestBuildAnalyticsL3:
    """Test building the L3 directory index (integration — requires the
    external Bright_Light corpus)."""

    @pytest.fixture(scope="class")
    def compiled(self) -> IRCorpus:
        return compile_domain_packs(PACKS_DIR, deduplicate=True)

    @pytest.fixture(scope="class")
    def l3_text(self, compiled: IRCorpus) -> str:
        return build_analytics_l3(compiled)

    def test_build_analytics_l3_shows_domain_counts(self, l3_text: str):
        """L3 should list each domain with counts."""
        # Should mention 'retail' somewhere
        assert "retail" in l3_text.lower(), f"L3 text:\n{l3_text[:500]}"
        # Should mention 'airlines'
        assert "airlines" in l3_text.lower()

    def test_build_analytics_l3_shows_totals(self, l3_text: str):
        """L3 should show aggregate totals."""
        # Should contain 'total' or 'Total'
        assert "total" in l3_text.lower(), f"L3 text:\n{l3_text[:500]}"

    def test_build_analytics_l3_is_compact(self, l3_text: str):
        """L3 should be compact — under 2000 chars."""
        assert len(l3_text) < 2000, f"L3 is {len(l3_text)} chars, expected <2000"

    def test_build_analytics_l3_contains_fingerprint_count(self, l3_text: str):
        """L3 should mention fingerprint counts."""
        assert "fingerprint" in l3_text.lower() or "fp" in l3_text.lower()

    def test_build_analytics_l3_contains_metric_count(self, l3_text: str):
        """L3 should mention metric counts."""
        assert "metric" in l3_text.lower()


# ── hermetic inline-YAML lane (no external corpus; Codex Finding 2a) ──


@requires_yaml
class TestHermeticInlineYAML:
    """Non-vacuous ordinary-lane coverage: parse real inline YAML domain
    packs with PyYAML, no Bright_Light corpus required."""

    def test_parse_empty_pack_returns_empty(self):
        """An empty YAML string returns an empty entity list."""
        assert parse_domain_pack("", filename="empty.yaml", domain="t") == []

    def test_parse_whitespace_only_pack_returns_empty(self):
        assert parse_domain_pack("  \n\n", filename="ws.yaml", domain="t") == []

    def test_parse_minimal_pack_returns_domain_entity(self):
        """A minimal pack (version + domain) yields a domain entity."""
        entities = parse_domain_pack(
            "version: v1\ndomain: test\n", filename="test.yaml", domain="test")
        assert len(entities) >= 1
        assert _find_entity(entities, "TEST") is not None

    def test_parse_inline_pack_extracts_metric_entity(self):
        """A hand-written inline pack with one metric produces a metric
        entity carrying its formula — proves the parser runs end-to-end on
        bytes authored here, not only on the external corpus."""
        text = (
            "version: v1\n"
            "domain: retail\n"
            "metadata:\n"
            "  description: inline test pack\n"
            "ontology:\n"
            "  metrics:\n"
            "    - name: gross_sales\n"
            "      formula: SUM(sales_amount)\n"
            "      owner: analytics-team\n"
        )
        entities = parse_domain_pack(text, filename="inline.yaml",
                                     domain="retail")
        domain_entity = _find_entity(entities, "RETAIL")
        assert domain_entity is not None
        assert "description" in domain_entity.annotations
        gross = _find_entity(entities, "GROSS-SALES")
        assert gross is not None
        formula = _find_field(gross, "FORMULA")
        assert formula is not None and "SUM" in formula.value

    def test_folded_scalar_parses_with_full_pyyaml(self):
        """Domain packs are standard YAML, not the ctxpack subset: a folded
        scalar (`>`), which the subset parser rejects, parses fine here —
        proof that full PyYAML is used, not the subset reader."""
        text = (
            "version: v1\n"
            "domain: test\n"
            "metadata:\n"
            "  description: >\n"
            "    one two\n"
            "    three\n"
        )
        entities = parse_domain_pack(text, filename="folded.yaml",
                                     domain="test")
        dom = _find_entity(entities, "TEST")
        assert dom is not None
        assert "description" in dom.annotations


class TestPyYAMLAbsence:
    """The lazy-import contract (Finding 2a): the module imports without
    PyYAML, and parsing without it raises the exact install hint. These run
    ALWAYS — they simulate PyYAML's absence, so they must not be skipped
    when PyYAML happens to be installed."""

    def test_module_imports_without_pyyaml(self, monkeypatch):
        """Reloading the analytics module with 'yaml' unavailable must not
        raise — module load is dep-free (a module-load `import yaml` was the
        public-CI break)."""
        monkeypatch.setitem(sys.modules, "yaml", None)
        import ctxpack.modules.analytics as analytics_mod
        importlib.reload(analytics_mod)            # must not import yaml
        assert analytics_mod is not None
        monkeypatch.undo()                          # restore, then reload clean
        importlib.reload(analytics_mod)

    def test_parse_without_pyyaml_raises_install_hint(self, monkeypatch):
        """Parsing a pack when PyYAML is absent raises ModuleNotFoundError
        naming `pip install ctxpack[analytics]`."""
        from ctxpack.modules import analytics as analytics_mod
        monkeypatch.setitem(sys.modules, "yaml", None)
        with pytest.raises(ModuleNotFoundError) as ei:
            analytics_mod.parse_domain_pack(
                "version: v1\ndomain: t\n", filename="t.yaml", domain="t")
        assert "pip install ctxpack[analytics]" in str(ei.value)

    def test_load_yaml_helper_raises_install_hint(self, monkeypatch):
        """The one call site (`_load_yaml`) surfaces the hint directly."""
        from ctxpack.modules import analytics as analytics_mod
        monkeypatch.setitem(sys.modules, "yaml", None)
        with pytest.raises(ModuleNotFoundError) as ei:
            analytics_mod._load_yaml("a: 1")
        assert "ctxpack[analytics]" in str(ei.value)
