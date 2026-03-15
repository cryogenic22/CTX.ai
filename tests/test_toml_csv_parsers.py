"""Tests for TOML and CSV source parsers + discovery integration.

TDD: these tests are written before the implementation.
"""

from __future__ import annotations

import os
import tempfile
import textwrap

import pytest

from ctxpack.core.packer.ir import IREntity, IRField, IRSource


# ── TOML Parser Tests ──


class TestTomlExtractsEntitiesFromTables:
    """test_toml_extracts_entities_from_tables"""

    def test_single_table_becomes_entity(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = textwrap.dedent("""\
            [customer]
            golden_source = "CRM"
            retention = "7-years"
        """)
        data = toml_parse(text, filename="entities.toml")
        entities, rules, warnings = extract_entities_from_toml(
            data, filename="entities.toml"
        )
        assert len(entities) >= 1
        names = [e.name for e in entities]
        assert "CUSTOMER" in names

    def test_multiple_tables_become_entities(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = textwrap.dedent("""\
            [customer]
            golden_source = "CRM"

            [order]
            golden_source = "OMS"
        """)
        data = toml_parse(text, filename="entities.toml")
        entities, rules, warnings = extract_entities_from_toml(
            data, filename="entities.toml"
        )
        names = [e.name for e in entities]
        assert "CUSTOMER" in names
        assert "ORDER" in names


class TestTomlExtractsFieldsWithTypes:
    """test_toml_extracts_fields_with_types"""

    def test_string_field_extracted(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = textwrap.dedent("""\
            [product]
            identifier = "sku"
            pii = false
            retention = "5-years"
        """)
        data = toml_parse(text, filename="product.toml")
        entities, _, _ = extract_entities_from_toml(data, filename="product.toml")
        assert len(entities) == 1
        entity = entities[0]
        assert entity.name == "PRODUCT"
        field_keys = [f.key for f in entity.fields]
        assert "IDENTIFIER" in field_keys
        assert "PII" in field_keys
        assert "RETENTION" in field_keys

    def test_integer_and_bool_preserved(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = textwrap.dedent("""\
            [config]
            max_retries = 3
            enabled = true
            fields = ["id", "name"]
        """)
        data = toml_parse(text, filename="config.toml")
        entities, rules, _ = extract_entities_from_toml(data, filename="config.toml")
        # Either extracted as entity or standalone rules — fields must have values
        all_fields = []
        for e in entities:
            all_fields.extend(e.fields)
        all_fields.extend(rules)
        keys = [f.key for f in all_fields]
        assert "MAX-RETRIES" in keys or "MAX_RETRIES" in keys


class TestTomlHandlesNestedTables:
    """test_toml_handles_nested_tables"""

    def test_dotted_table_key_extracts_entity(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = textwrap.dedent("""\
            [entity.customer]
            golden_source = "CRM"
            identifier = "customer_id"

            [entity.order]
            golden_source = "OMS"
        """)
        data = toml_parse(text, filename="entities.toml")
        entities, _, _ = extract_entities_from_toml(data, filename="entities.toml")
        names = [e.name for e in entities]
        assert "CUSTOMER" in names
        assert "ORDER" in names

    def test_nested_subtable_becomes_field(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = textwrap.dedent("""\
            [customer]
            golden_source = "CRM"

            [customer.retention]
            active = "7-years"
            churned = "2-years"
        """)
        data = toml_parse(text, filename="entities.toml")
        entities, _, _ = extract_entities_from_toml(data, filename="entities.toml")
        assert len(entities) >= 1
        customer = [e for e in entities if e.name == "CUSTOMER"][0]
        # The retention subtable should appear as fields
        field_keys = [f.key for f in customer.fields]
        has_retention = any("RETENTION" in k for k in field_keys)
        assert has_retention


class TestTomlSetsSourceProvenance:
    """test_toml_sets_source_provenance"""

    def test_entity_has_source(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = textwrap.dedent("""\
            [customer]
            golden_source = "CRM"
        """)
        data = toml_parse(text, filename="schema/entities.toml")
        entities, _, _ = extract_entities_from_toml(data, filename="schema/entities.toml")
        assert len(entities) >= 1
        assert entities[0].sources[0].file == "schema/entities.toml"

    def test_field_has_source(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = textwrap.dedent("""\
            [customer]
            golden_source = "CRM"
        """)
        data = toml_parse(text, filename="entities.toml")
        entities, _, _ = extract_entities_from_toml(data, filename="entities.toml")
        for f in entities[0].fields:
            assert f.source is not None
            assert f.source.file == "entities.toml"


class TestTomlEmptyFileReturnsEmpty:
    """test_toml_empty_file_returns_empty"""

    def test_empty_string(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        data = toml_parse("", filename="empty.toml")
        entities, rules, warnings = extract_entities_from_toml(
            data, filename="empty.toml"
        )
        assert entities == []
        assert rules == []

    def test_comments_only(self):
        from ctxpack.core.packer.toml_parser import toml_parse, extract_entities_from_toml

        text = "# This is just a comment\n# Another comment\n"
        data = toml_parse(text, filename="comments.toml")
        entities, rules, warnings = extract_entities_from_toml(
            data, filename="comments.toml"
        )
        assert entities == []
        assert rules == []


# ── CSV Parser Tests ──


class TestCsvEntityPerRowLayout:
    """test_csv_entity_per_row_layout"""

    def test_groups_rows_by_entity(self):
        from ctxpack.core.packer.csv_parser import csv_parse, extract_entities_from_csv

        text = textwrap.dedent("""\
            entity,field_name,type,description,nullable,pii
            customer,customer_id,string,Unique customer identifier,false,false
            customer,email,string,Customer email address,false,true
            order,order_id,string,Unique order identifier,false,false
            order,total,decimal,Order total amount,false,false
        """)
        data = csv_parse(text, filename="data_dict.csv")
        entities, _, _ = extract_entities_from_csv(data, filename="data_dict.csv")
        names = [e.name for e in entities]
        assert "CUSTOMER" in names
        assert "ORDER" in names
        customer = [e for e in entities if e.name == "CUSTOMER"][0]
        assert len(customer.fields) >= 2

    def test_field_values_compressed(self):
        from ctxpack.core.packer.csv_parser import csv_parse, extract_entities_from_csv

        text = textwrap.dedent("""\
            entity,field_name,type,description,nullable,pii
            customer,customer_id,string,Unique ID,false,false
        """)
        data = csv_parse(text, filename="dict.csv")
        entities, _, _ = extract_entities_from_csv(data, filename="dict.csv")
        customer = [e for e in entities if e.name == "CUSTOMER"][0]
        assert len(customer.fields) >= 1
        # Field should have a key and value
        f = customer.fields[0]
        assert f.key
        assert f.value


class TestCsvEntityPerFileLayout:
    """test_csv_entity_per_file_layout"""

    def test_filename_becomes_entity(self):
        from ctxpack.core.packer.csv_parser import csv_parse, extract_entities_from_csv

        text = textwrap.dedent("""\
            field_name,type,description,nullable,pii
            customer_id,string,Unique customer identifier,false,false
            email,string,Customer email address,false,true
            name,string,Full customer name,true,true
        """)
        data = csv_parse(text, filename="customer.csv")
        entities, _, _ = extract_entities_from_csv(data, filename="customer.csv")
        assert len(entities) == 1
        assert entities[0].name == "CUSTOMER"
        assert len(entities[0].fields) >= 3


class TestCsvAutoDetectsLayout:
    """test_csv_auto_detects_layout"""

    def test_detects_entity_per_row_from_entity_column(self):
        from ctxpack.core.packer.csv_parser import csv_parse, extract_entities_from_csv

        text_with_entity_col = textwrap.dedent("""\
            entity,field_name,type,description
            customer,id,string,Customer ID
        """)
        data = csv_parse(text_with_entity_col, filename="dict.csv")
        entities, _, _ = extract_entities_from_csv(data, filename="dict.csv")
        assert len(entities) == 1
        assert entities[0].name == "CUSTOMER"

    def test_detects_entity_per_file_from_missing_entity_column(self):
        from ctxpack.core.packer.csv_parser import csv_parse, extract_entities_from_csv

        text_no_entity_col = textwrap.dedent("""\
            field_name,type,description
            id,string,Customer ID
        """)
        data = csv_parse(text_no_entity_col, filename="customer.csv")
        entities, _, _ = extract_entities_from_csv(data, filename="customer.csv")
        assert len(entities) == 1
        assert entities[0].name == "CUSTOMER"


class TestCsvExtractsPiiFields:
    """test_csv_extracts_pii_fields"""

    def test_pii_column_true_marks_field(self):
        from ctxpack.core.packer.csv_parser import csv_parse, extract_entities_from_csv

        text = textwrap.dedent("""\
            entity,field_name,type,description,nullable,pii
            customer,email,string,Email address,false,true
            customer,name,string,Full name,false,true
            customer,status,string,Account status,false,false
        """)
        data = csv_parse(text, filename="dict.csv")
        entities, _, _ = extract_entities_from_csv(data, filename="dict.csv")
        customer = [e for e in entities if e.name == "CUSTOMER"][0]
        # At least one field should contain PII information
        pii_fields = [
            f for f in customer.fields
            if "pii" in f.value.lower() or "PII" in f.key
        ]
        assert len(pii_fields) >= 1


class TestCsvSetsSourceProvenance:
    """test_csv_sets_source_provenance"""

    def test_entity_source_set(self):
        from ctxpack.core.packer.csv_parser import csv_parse, extract_entities_from_csv

        text = textwrap.dedent("""\
            entity,field_name,type,description
            customer,id,string,Customer ID
        """)
        data = csv_parse(text, filename="schema/dict.csv")
        entities, _, _ = extract_entities_from_csv(data, filename="schema/dict.csv")
        assert len(entities) >= 1
        assert entities[0].sources[0].file == "schema/dict.csv"

    def test_field_source_set(self):
        from ctxpack.core.packer.csv_parser import csv_parse, extract_entities_from_csv

        text = textwrap.dedent("""\
            entity,field_name,type,description
            customer,id,string,Customer ID
        """)
        data = csv_parse(text, filename="dict.csv")
        entities, _, _ = extract_entities_from_csv(data, filename="dict.csv")
        for f in entities[0].fields:
            assert f.source is not None
            assert f.source.file == "dict.csv"


# ── Discovery Integration Tests ──


class TestDiscoveryClassifiesTomlFiles:
    """test_discovery_classifies_toml_files"""

    def test_toml_files_classified(self):
        from ctxpack.core.packer.discovery import discover

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a .toml file
            toml_path = os.path.join(tmpdir, "entities.toml")
            with open(toml_path, "w", encoding="utf-8") as f:
                f.write('[customer]\ngolden_source = "CRM"\n')

            result = discover(tmpdir)
            assert hasattr(result, "toml_files")
            assert len(result.toml_files) == 1
            assert result.toml_files[0].endswith("entities.toml")

    def test_toml_excluded_by_pattern(self):
        from ctxpack.core.packer.discovery import discover

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create ctxpack.yaml with exclude pattern
            config_path = os.path.join(tmpdir, "ctxpack.yaml")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("exclude:\n  - '*.toml'\n")

            toml_path = os.path.join(tmpdir, "entities.toml")
            with open(toml_path, "w", encoding="utf-8") as f:
                f.write('[customer]\ngolden_source = "CRM"\n')

            result = discover(tmpdir)
            assert hasattr(result, "toml_files")
            assert len(result.toml_files) == 0


class TestDiscoveryClassifiesCsvFiles:
    """test_discovery_classifies_csv_files"""

    def test_csv_files_classified(self):
        from ctxpack.core.packer.discovery import discover

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "data_dict.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("entity,field_name,type\ncustomer,id,string\n")

            result = discover(tmpdir)
            assert hasattr(result, "csv_files")
            assert len(result.csv_files) == 1
            assert result.csv_files[0].endswith("data_dict.csv")

    def test_csv_excluded_by_pattern(self):
        from ctxpack.core.packer.discovery import discover

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "ctxpack.yaml")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("exclude:\n  - '*.csv'\n")

            csv_path = os.path.join(tmpdir, "data_dict.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("entity,field_name,type\ncustomer,id,string\n")

            result = discover(tmpdir)
            assert hasattr(result, "csv_files")
            assert len(result.csv_files) == 0
