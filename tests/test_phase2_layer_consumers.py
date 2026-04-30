"""Phase 2 — layer-aware consumers.

Verifies that:
- The compressor forwards layer/confidence from IREntity into the inserted
  Provenance child, so the layer survives IR → AST.
- hydrate_by_name accepts `layers` / `min_confidence` / `include_layer_metadata`
  and filters sections accordingly.
- grounding.build_grounded_prompt accepts `layer_legend` and renders a
  short trust legend after the catalog.

No producer of INFERRED/AMBIENT/ELICITED layers exists yet — those arrive
in Phase 3. Phase 2 only validates that the plumbing carries the metadata
through and that filtering works when layers are present.
"""

from __future__ import annotations

import time

from ctxpack.core.layers import ContextLayer
from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer as DocLayer,
    Provenance,
    Section,
)
from ctxpack.core.packer.compressor import _entity_to_section
from ctxpack.core.packer.ir import IRCorpus, IREntity, IRField
from ctxpack.core.hydrator import hydrate_by_name, list_sections
from ctxpack.modules.grounding import build_grounded_prompt


# ── Test fixtures ───────────────────────────────────────────────────────


def _make_section(
    name: str,
    *,
    layer: ContextLayer = ContextLayer.RULES,
    confidence: float = 1.0,
) -> Section:
    """Build a small Section with a layered Provenance child."""
    return Section(
        name=name,
        children=(
            KeyValue(key="status", value="active"),
            Provenance(
                source=f"{name.lower()}.md",
                path=f"/repo/{name.lower()}.md",
                layer=layer,
                confidence=confidence,
            ),
        ),
    )


def _make_doc(*sections: Section) -> CTXDocument:
    header = Header(magic="§CTX", version="1.0", layer=DocLayer.L2)
    return CTXDocument(header=header, body=tuple(sections))


# ── Compressor preserves layer ──────────────────────────────────────────


class TestCompressorLayerThreading:
    def test_rules_entity_produces_rules_provenance(self):
        from ctxpack.core.packer.ir import IRSource

        entity = IREntity(
            name="CUSTOMER",
            fields=[IRField(key="status", value="active")],
            sources=[IRSource(file="customers.md", line_start=1)],
        )
        section = _entity_to_section(entity)
        provs = [c for c in section.children if isinstance(c, Provenance)]
        assert len(provs) == 1
        assert provs[0].layer is ContextLayer.RULES
        assert provs[0].confidence == 1.0

    def test_inferred_entity_produces_inferred_provenance(self):
        from ctxpack.core.packer.ir import IRSource

        entity = IREntity(
            name="DRIFT_QUERY_LATENCY",
            fields=[IRField(key="p99", value="220ms")],
            sources=[IRSource(file="dream-2026-04-29", line_start=0)],
            layer=ContextLayer.INFERRED,
            confidence=0.74,
            observation_count=18,
        )
        section = _entity_to_section(entity)
        provs = [c for c in section.children if isinstance(c, Provenance)]
        assert len(provs) == 1
        assert provs[0].layer is ContextLayer.INFERRED
        assert provs[0].confidence == 0.74
        assert provs[0].observation_count == 18

    def test_ambient_entity_carries_expiry(self):
        from ctxpack.core.packer.ir import IRSource

        future = time.time() + 60
        entity = IREntity(
            name="LIVE_FLAGS",
            fields=[IRField(key="enabled_count", value="42")],
            sources=[IRSource(file="prod.api", line_start=0)],
            layer=ContextLayer.AMBIENT,
            expires_at=future,
        )
        section = _entity_to_section(entity)
        provs = [c for c in section.children if isinstance(c, Provenance)]
        assert provs[0].layer is ContextLayer.AMBIENT
        assert provs[0].expires_at is not None


# ── Hydrator: layer filtering ───────────────────────────────────────────


class TestHydrateByNameLayerFilter:
    def test_default_returns_all_layers(self):
        doc = _make_doc(
            _make_section("ENTITY-A", layer=ContextLayer.RULES),
            _make_section("ENTITY-B", layer=ContextLayer.INFERRED, confidence=0.6),
        )
        result = hydrate_by_name(doc, ["ENTITY-A", "ENTITY-B"])
        assert len(result.sections) == 2

    def test_layers_filter_keeps_only_listed(self):
        doc = _make_doc(
            _make_section("ENTITY-A", layer=ContextLayer.RULES),
            _make_section("ENTITY-B", layer=ContextLayer.INFERRED, confidence=0.6),
        )
        result = hydrate_by_name(
            doc,
            ["ENTITY-A", "ENTITY-B"],
            layers={ContextLayer.RULES},
        )
        assert len(result.sections) == 1
        assert result.sections[0].name == "ENTITY-A"

    def test_layers_filter_accepts_multiple(self):
        doc = _make_doc(
            _make_section("ENTITY-A", layer=ContextLayer.RULES),
            _make_section("ENTITY-B", layer=ContextLayer.INFERRED, confidence=0.8),
            _make_section("ENTITY-C", layer=ContextLayer.AMBIENT),
        )
        result = hydrate_by_name(
            doc,
            ["ENTITY-A", "ENTITY-B", "ENTITY-C"],
            layers={ContextLayer.RULES, ContextLayer.INFERRED},
        )
        names = {s.name for s in result.sections}
        assert names == {"ENTITY-A", "ENTITY-B"}

    def test_section_without_provenance_treated_as_rules(self):
        # Legacy sections (no Provenance child) must still be returned when
        # layers={RULES} so existing pipelines don't break.
        doc = _make_doc(
            Section(name="LEGACY", children=(KeyValue(key="x", value="1"),)),
        )
        result = hydrate_by_name(doc, ["LEGACY"], layers={ContextLayer.RULES})
        assert len(result.sections) == 1


class TestHydrateByNameConfidenceFilter:
    def test_default_min_confidence_is_zero(self):
        doc = _make_doc(
            _make_section("E", layer=ContextLayer.INFERRED, confidence=0.1),
        )
        result = hydrate_by_name(doc, ["E"])
        assert len(result.sections) == 1

    def test_min_confidence_drops_low_confidence_sections(self):
        doc = _make_doc(
            _make_section("HIGH", layer=ContextLayer.INFERRED, confidence=0.9),
            _make_section("LOW", layer=ContextLayer.INFERRED, confidence=0.3),
        )
        result = hydrate_by_name(doc, ["HIGH", "LOW"], min_confidence=0.5)
        names = {s.name for s in result.sections}
        assert names == {"HIGH"}

    def test_rules_always_pass_confidence_filter(self):
        # RULES default to confidence 1.0; even with min_confidence=0.99 they pass.
        doc = _make_doc(
            _make_section("R", layer=ContextLayer.RULES),
        )
        result = hydrate_by_name(doc, ["R"], min_confidence=0.99)
        assert len(result.sections) == 1


class TestHydrateByNameLayerMetadata:
    def test_metadata_off_by_default(self):
        doc = _make_doc(
            _make_section("E", layer=ContextLayer.INFERRED, confidence=0.7),
        )
        result = hydrate_by_name(doc, ["E"])
        # New attribute exists but is empty when metadata is disabled.
        assert getattr(result, "layer_breakdown", {}) == {}

    def test_metadata_records_per_layer_counts(self):
        doc = _make_doc(
            _make_section("A", layer=ContextLayer.RULES),
            _make_section("B", layer=ContextLayer.INFERRED, confidence=0.8),
            _make_section("C", layer=ContextLayer.INFERRED, confidence=0.7),
        )
        result = hydrate_by_name(
            doc,
            ["A", "B", "C"],
            include_layer_metadata=True,
        )
        assert result.layer_breakdown == {"rules": 1, "inferred": 2}


# ── Grounding: layer legend ─────────────────────────────────────────────


class TestGroundingLayerLegend:
    def test_legend_off_by_default(self):
        prompt = build_grounded_prompt(catalog="## ENTITY-A\n", few_shot=False)
        assert "Trust Legend" not in prompt
        assert "rules" not in prompt.lower() or "GROUNDING" in prompt

    def test_legend_on_inserts_legend_block(self):
        prompt = build_grounded_prompt(
            catalog="## ENTITY-A\n",
            few_shot=False,
            layer_legend=True,
        )
        assert "Trust Legend" in prompt
        # All four layer names appear, lowercased
        for layer in ("rules", "inferred", "elicited", "ambient"):
            assert layer in prompt.lower()

    def test_legend_appears_after_catalog(self):
        prompt = build_grounded_prompt(
            catalog="## ENTITY-A\n",
            few_shot=False,
            layer_legend=True,
        )
        catalog_idx = prompt.index("--- END CATALOG ---")
        legend_idx = prompt.index("Trust Legend")
        assert legend_idx > catalog_idx

    def test_legend_warns_about_inferred_being_observed_not_policy(self):
        prompt = build_grounded_prompt(
            catalog="## ENTITY-A\n",
            few_shot=False,
            layer_legend=True,
        )
        # The legend must call out the difference between observed patterns
        # and policy facts so the LLM weights them differently.
        lower = prompt.lower()
        assert "policy" in lower or "rule" in lower
        assert "observed" in lower or "observation" in lower


# ── list_sections still works (sanity) ──────────────────────────────────


class TestListSectionsBackwardCompat:
    def test_list_sections_unchanged(self):
        doc = _make_doc(
            _make_section("E", layer=ContextLayer.INFERRED, confidence=0.6),
        )
        listing = list_sections(doc)
        assert len(listing) == 1
        assert listing[0]["name"] == "E"
        assert "tokens" in listing[0]
