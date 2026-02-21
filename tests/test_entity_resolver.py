"""Tests for entity resolution and dedup."""

import pytest
from ctxpack.core.packer.ir import IRCorpus, IREntity, IRField, IRSource
from ctxpack.core.packer.entity_resolver import resolve_entities


class TestNameNormalization:
    def test_case_insensitive_merge(self):
        corpus = IRCorpus(entities=[
            IREntity(name="CUSTOMER", fields=[IRField(key="A", value="1")]),
            IREntity(name="customer", fields=[IRField(key="B", value="2")]),
        ])
        resolve_entities(corpus)
        assert len(corpus.entities) == 1
        assert corpus.entities[0].name == "CUSTOMER"
        assert len(corpus.entities[0].fields) == 2

    def test_underscore_to_hyphen(self):
        corpus = IRCorpus(entities=[
            IREntity(name="ENTITY_CUSTOMER", fields=[IRField(key="A", value="1")]),
            IREntity(name="CUSTOMER", fields=[IRField(key="B", value="2")]),
        ])
        resolve_entities(corpus)
        assert len(corpus.entities) == 1

    def test_entity_prefix_stripped(self):
        corpus = IRCorpus(entities=[
            IREntity(name="ENTITY-CUSTOMER", fields=[]),
            IREntity(name="CUSTOMER", fields=[]),
        ])
        resolve_entities(corpus)
        assert len(corpus.entities) == 1
        assert corpus.entities[0].name == "CUSTOMER"


class TestAliasMerge:
    def test_alias_map_merge(self):
        corpus = IRCorpus(entities=[
            IREntity(name="CUSTOMER", fields=[IRField(key="A", value="1")]),
            IREntity(name="CLIENT", fields=[IRField(key="B", value="2")]),
        ])
        alias_map = {"CUSTOMER": ["client", "buyer"]}
        resolve_entities(corpus, alias_map=alias_map)
        assert len(corpus.entities) == 1
        assert corpus.entities[0].name == "CUSTOMER"
        assert len(corpus.entities[0].fields) == 2

    def test_no_merge_without_alias(self):
        corpus = IRCorpus(entities=[
            IREntity(name="CUSTOMER", fields=[]),
            IREntity(name="ORDER", fields=[]),
        ])
        resolve_entities(corpus)
        assert len(corpus.entities) == 2


class TestFieldDedup:
    def test_duplicate_fields_deduped(self):
        field_a = IRField(key="STATUS", value="active", raw_value="active")
        field_b = IRField(key="STATUS", value="active", raw_value="active")
        corpus = IRCorpus(entities=[
            IREntity(name="CUSTOMER", fields=[field_a]),
            IREntity(name="customer", fields=[field_b]),
        ])
        resolve_entities(corpus)
        assert len(corpus.entities) == 1
        # Duplicate field should be deduped
        status_fields = [f for f in corpus.entities[0].fields if f.key == "STATUS"]
        assert len(status_fields) == 1

    def test_different_values_not_deduped(self):
        field_a = IRField(key="STATUS", value="active", raw_value="active")
        field_b = IRField(key="STATUS", value="inactive", raw_value="inactive")
        corpus = IRCorpus(entities=[
            IREntity(name="CUSTOMER", fields=[field_a, field_b]),
        ])
        resolve_entities(corpus)
        status_fields = [f for f in corpus.entities[0].fields if f.key == "STATUS"]
        assert len(status_fields) == 2


class TestSourceMerge:
    def test_sources_combined(self):
        src_a = IRSource(file="a.yaml")
        src_b = IRSource(file="b.md")
        corpus = IRCorpus(entities=[
            IREntity(name="CUSTOMER", sources=[src_a], fields=[]),
            IREntity(name="customer", sources=[src_b], fields=[]),
        ])
        resolve_entities(corpus)
        assert len(corpus.entities[0].sources) == 2

    def test_aliases_combined(self):
        corpus = IRCorpus(entities=[
            IREntity(name="CUSTOMER", aliases=["client"], fields=[]),
            IREntity(name="customer", aliases=["buyer"], fields=[]),
        ])
        resolve_entities(corpus)
        assert "buyer" in corpus.entities[0].aliases
        assert "client" in corpus.entities[0].aliases
