"""Tests for YAML entity extraction to IR."""

import os
import pytest
from ctxpack.core.packer.yaml_parser import yaml_parse, extract_entities_from_yaml


FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample-corpus"
)


class TestSingleEntityExtraction:
    def test_customer_entity_name(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "customer.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="customer.yaml")
        assert len(entities) == 1
        assert entities[0].name == "CUSTOMER"

    def test_customer_has_aliases(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "customer.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="customer.yaml")
        assert "client" in entities[0].aliases
        assert "buyer" in entities[0].aliases

    def test_customer_golden_source(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "customer.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="customer.yaml")
        fields = {f.key: f.value for f in entities[0].fields}
        assert "★GOLDEN-SOURCE" in fields
        assert "Salesforce" in fields["★GOLDEN-SOURCE"]

    def test_customer_identifier(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "customer.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="customer.yaml")
        fields = {f.key: f.value for f in entities[0].fields}
        assert "IDENTIFIER" in fields
        assert "customer_id" in fields["IDENTIFIER"]
        assert "UUID" in fields["IDENTIFIER"]

    def test_customer_match_rules(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "customer.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="customer.yaml")
        fields = {f.key: f.value for f in entities[0].fields}
        assert "MATCH-RULES" in fields
        assert "email" in fields["MATCH-RULES"]

    def test_customer_pii(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "customer.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="customer.yaml")
        fields = {f.key: f.value for f in entities[0].fields}
        assert "PII-CLASSIFICATION" in fields
        assert "RESTRICTED" in fields["PII-CLASSIFICATION"]

    def test_customer_retention(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "customer.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="customer.yaml")
        fields = {f.key: f.value for f in entities[0].fields}
        assert "RETENTION" in fields
        assert "anonymise" in fields["RETENTION"]


class TestOrderEntityExtraction:
    def test_order_belongs_to(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "order.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="order.yaml")
        fields = {f.key: f.value for f in entities[0].fields}
        assert "BELONGS-TO" in fields
        assert "CUSTOMER" in fields["BELONGS-TO"]

    def test_order_status_machine(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "order.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="order.yaml")
        fields = {f.key: f.value for f in entities[0].fields}
        assert "STATUS-MACHINE" in fields
        assert "→" in fields["STATUS-MACHINE"]

    def test_order_financial_fields(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "entities", "order.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="order.yaml")
        fields = {f.key: f.value for f in entities[0].fields}
        assert "FINANCIAL-FIELDS" in fields
        assert "DECIMAL" in fields["FINANCIAL-FIELDS"]


class TestRulesExtraction:
    def test_rules_file_produces_standalone_rules(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "rules", "data-quality.yaml"), encoding="utf-8").read())
        _, rules, _ = extract_entities_from_yaml(data, filename="data-quality.yaml")
        assert len(rules) > 0
        keys = [r.key for r in rules]
        assert "NULL-POLICY" in keys
        assert "FRESHNESS" in keys

    def test_rules_file_no_entities(self):
        data = yaml_parse(open(os.path.join(FIXTURES_DIR, "rules", "data-quality.yaml"), encoding="utf-8").read())
        entities, _, _ = extract_entities_from_yaml(data, filename="data-quality.yaml")
        assert len(entities) == 0


class TestGenericCompression:
    def test_list_compression(self):
        data = {"entity": "TEST", "tags": ["a", "b", "c"]}
        entities, _, _ = extract_entities_from_yaml(data)
        fields = {f.key: f.value for f in entities[0].fields}
        assert "TAGS" in fields
        assert "a+b+c" == fields["TAGS"]

    def test_dict_compression(self):
        data = {"entity": "TEST", "config": {"mode": "fast", "retry": 3}}
        entities, _, _ = extract_entities_from_yaml(data)
        fields = {f.key: f.value for f in entities[0].fields}
        assert "CONFIG" in fields
        assert "mode(fast)" in fields["CONFIG"]
