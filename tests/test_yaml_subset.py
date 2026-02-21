"""Tests for the YAML subset parser."""

import pytest
from ctxpack.core.packer.yaml_parser import yaml_parse, YAMLParseError


class TestScalars:
    def test_string(self):
        result = yaml_parse("key: hello")
        assert result == {"key": "hello"}

    def test_quoted_string(self):
        result = yaml_parse('key: "hello world"')
        assert result == {"key": "hello world"}

    def test_single_quoted_string(self):
        result = yaml_parse("key: 'hello world'")
        assert result == {"key": "hello world"}

    def test_integer(self):
        result = yaml_parse("key: 42")
        assert result == {"key": 42}

    def test_float(self):
        result = yaml_parse("key: 3.14")
        assert result == {"key": 3.14}

    def test_boolean_true(self):
        result = yaml_parse("key: true")
        assert result == {"key": True}

    def test_boolean_false(self):
        result = yaml_parse("key: false")
        assert result == {"key": False}

    def test_null(self):
        result = yaml_parse("key: null")
        assert result == {"key": None}

    def test_tilde_null(self):
        result = yaml_parse("key: ~")
        assert result == {"key": None}


class TestMappings:
    def test_simple_mapping(self):
        result = yaml_parse("name: Alice\nage: 30")
        assert result == {"name": "Alice", "age": 30}

    def test_nested_mapping(self):
        text = "outer:\n  inner: value"
        result = yaml_parse(text)
        assert result == {"outer": {"inner": "value"}}

    def test_deeply_nested(self):
        text = "a:\n  b:\n    c: deep"
        result = yaml_parse(text)
        assert result == {"a": {"b": {"c": "deep"}}}

    def test_flow_mapping(self):
        result = yaml_parse("key: {a: 1, b: 2}")
        assert result == {"key": {"a": 1, "b": 2}}

    def test_multiple_keys(self):
        text = "x: 1\ny: 2\nz: 3"
        result = yaml_parse(text)
        assert result == {"x": 1, "y": 2, "z": 3}


class TestSequences:
    def test_block_sequence(self):
        text = "items:\n  - a\n  - b\n  - c"
        result = yaml_parse(text)
        assert result == {"items": ["a", "b", "c"]}

    def test_flow_sequence(self):
        result = yaml_parse("items: [a, b, c]")
        assert result == {"items": ["a", "b", "c"]}

    def test_sequence_of_mappings(self):
        text = "rules:\n  - field: email\n    method: exact\n  - field: phone\n    method: normalise"
        result = yaml_parse(text)
        assert result == {
            "rules": [
                {"field": "email", "method": "exact"},
                {"field": "phone", "method": "normalise"},
            ]
        }

    def test_flow_sequence_of_strings(self):
        result = yaml_parse("tags: [red, green, blue]")
        assert result == {"tags": ["red", "green", "blue"]}

    def test_nested_flow_in_block(self):
        text = "match:\n  - field: email\n    options: {case: insensitive}"
        result = yaml_parse(text)
        assert result["match"][0]["options"] == {"case": "insensitive"}


class TestComments:
    def test_inline_comment(self):
        result = yaml_parse("key: value # this is a comment")
        assert result == {"key": "value"}

    def test_full_line_comment(self):
        result = yaml_parse("# comment\nkey: value")
        assert result == {"key": "value"}

    def test_blank_lines(self):
        result = yaml_parse("\n\nkey: value\n\n")
        assert result == {"key": "value"}


class TestUnsupported:
    def test_anchor_rejected(self):
        with pytest.raises(YAMLParseError, match="anchors"):
            yaml_parse("key: &anchor value")

    def test_alias_rejected(self):
        with pytest.raises(YAMLParseError, match="anchors"):
            yaml_parse("key: *alias")

    def test_tag_rejected(self):
        with pytest.raises(YAMLParseError, match="tags"):
            yaml_parse("key: !!int 42")

    def test_multiline_scalar_rejected(self):
        with pytest.raises(YAMLParseError, match="Multi-line scalar"):
            yaml_parse("key: |\n  line1\n  line2")

    def test_fold_scalar_rejected(self):
        with pytest.raises(YAMLParseError, match="Multi-line scalar"):
            yaml_parse("key: >\n  line1\n  line2")


class TestEdgeCases:
    def test_empty_string(self):
        result = yaml_parse("")
        assert result == {}

    def test_colon_in_value(self):
        result = yaml_parse("url: https://example.com:8080")
        assert result == {"url": "https://example.com:8080"}

    def test_key_with_hyphens(self):
        result = yaml_parse("my-key: value")
        assert result == {"my-key": "value"}

    def test_value_with_special_chars(self):
        result = yaml_parse('desc: "value with #hash and :colon"')
        assert result == {"desc": "value with #hash and :colon"}

    def test_filename_in_error(self):
        with pytest.raises(YAMLParseError, match="test.yaml"):
            yaml_parse("key: !!int 42", filename="test.yaml")
