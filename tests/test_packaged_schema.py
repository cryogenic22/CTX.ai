"""The code-packer telemetry schema is part of the installed package."""
from __future__ import annotations

from ctxpack.core.code.telemetry import _SCHEMA_PATH, load_schema


def test_telemetry_schema_file_is_next_to_the_package():
    assert _SCHEMA_PATH.is_file(), _SCHEMA_PATH
    assert _SCHEMA_PATH.name == "telemetry-events.schema.json"


def test_telemetry_schema_loads():
    schema = load_schema()
    assert schema["properties"]["event_type"]["enum"]
    assert "ts" in schema["required"]
