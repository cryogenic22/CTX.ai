"""CP-040.5 + CP-041 — code-packer telemetry."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


# ── Schema sanity ──────────────────────────────────────────────────────


class TestSchema:
    def test_schema_loads(self):
        from ctxpack.core.code.telemetry import load_schema
        s = load_schema()
        assert s["$schema"].startswith("https://json-schema.org/")
        assert s["title"] == "Code-packer telemetry events"
        assert s["version"] == 1

    def test_event_types_enumerated(self):
        from ctxpack.core.code.telemetry import load_schema
        s = load_schema()
        types = set(s["properties"]["event_type"]["enum"])
        assert "pack_built" in types
        assert "list_symbols_call" in types
        assert "hydrate_symbol_call" in types
        assert "search_symbols_call" in types
        assert "raw_file_call" in types
        assert "symbol_not_in_pack" in types
        assert "pattern_raw_file_after_hydrate" in types
        assert "pattern_reformulated_search" in types


class TestValidation:
    def test_minimal_pack_built_validates(self):
        from ctxpack.core.code.telemetry import validate_event
        ev = {
            "v": 1,
            "ts": "2026-05-13T10:00:00Z",
            "session_id": "abcdef0123456789",
            "event_type": "pack_built",
            "pack_version": "abc" * 16,
            "root_hash": "deadbeef" * 4,
            "entities": 10,
            "files": 3,
            "latency_ms": 12.3,
        }
        validate_event(ev)  # must not raise

    def test_missing_required_field_fails(self):
        from ctxpack.core.code.telemetry import validate_event
        import jsonschema
        ev = {
            "v": 1,
            "ts": "2026-05-13T10:00:00Z",
            "session_id": "abcdef0123456789",
            "event_type": "pack_built",
            # missing root_hash, entities, files, pack_version, latency_ms
        }
        with pytest.raises(jsonschema.ValidationError):
            validate_event(ev)

    def test_wrong_event_type_fails(self):
        from ctxpack.core.code.telemetry import validate_event
        import jsonschema
        ev = {
            "v": 1,
            "ts": "2026-05-13T10:00:00Z",
            "session_id": "abc123",
            "event_type": "definitely_not_a_valid_type",
        }
        with pytest.raises(jsonschema.ValidationError):
            validate_event(ev)


# ── Telemetry writes are schema-valid ──────────────────────────────────


class TestEventsValidateAgainstSchema:
    """For every emitter on CodeTelemetry, the event it writes must
    validate against the schema. This is the CP-040.5 ship gate."""

    def _read_all(self, path: Path) -> list[dict]:
        out: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def test_every_emitter(self, tmp_path: Path):
        from ctxpack.core.code.telemetry import CodeTelemetry, validate_event
        tel = CodeTelemetry(
            path=tmp_path / "t.jsonl",
            session_id="cafebabe",
            pack_version="v1pack",
        )
        tel.log_pack_built(
            root="/repo", entities=10, files=3,
            pack_version="v1pack", latency_ms=15.0,
        )
        tel.log_list_symbols(
            module="x.py", k=10, n_returned=3,
            context="search a thing", alpha=0.7, latency_ms=1.2,
        )
        tel.log_hydrate_symbol(
            name="x.py::foo", depth=0, success=True, latency_ms=0.3,
        )
        tel.log_search_symbols(
            query="search a thing", k=10, n_returned=5,
            alpha=0.7, latency_ms=2.1,
        )
        tel.log_raw_file(path="x.py", success=True, latency_ms=0.5)
        tel.log_symbol_not_in_pack(name="x.py::missing")
        events = self._read_all(tmp_path / "t.jsonl")
        assert events, "no events written"
        for ev in events:
            validate_event(ev)


# ── Pattern: raw_file after hydrate_symbol ────────────────────────────


class TestRawFileAfterHydratePattern:
    def test_pattern_emitted(self, tmp_path: Path):
        from ctxpack.core.code.telemetry import CodeTelemetry
        tel = CodeTelemetry(path=tmp_path / "t.jsonl", session_id="aaaa",
                            pack_version="v1")
        tel.log_hydrate_symbol(
            name="src/foo.py::bar", depth=0, success=True, latency_ms=0.5,
        )
        tel.log_raw_file(path="src/foo.py", success=True, latency_ms=0.5)
        events = [json.loads(l) for l in
                  (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines() if l]
        types = [e["event_type"] for e in events]
        assert "pattern_raw_file_after_hydrate" in types

    def test_pattern_not_emitted_for_unrelated_file(self, tmp_path: Path):
        from ctxpack.core.code.telemetry import CodeTelemetry
        tel = CodeTelemetry(path=tmp_path / "t.jsonl", session_id="bbbb",
                            pack_version="v1")
        tel.log_hydrate_symbol(
            name="src/foo.py::bar", depth=0, success=True, latency_ms=0.5,
        )
        tel.log_raw_file(path="src/totally_other.py", success=True, latency_ms=0.5)
        events = [json.loads(l) for l in
                  (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines() if l]
        types = [e["event_type"] for e in events]
        assert "pattern_raw_file_after_hydrate" not in types


# ── Pattern: reformulated search ──────────────────────────────────────


class TestReformulatedSearchPattern:
    def test_pattern_emitted_on_similar_queries(self, tmp_path: Path):
        from ctxpack.core.code.telemetry import CodeTelemetry
        tel = CodeTelemetry(path=tmp_path / "t.jsonl", session_id="cccc",
                            pack_version="v1")
        tel.log_search_symbols(
            query="create user", k=10, n_returned=5, alpha=0.7, latency_ms=1.0,
        )
        tel.log_search_symbols(
            query="user create",  # same normalised key
            k=10, n_returned=5, alpha=0.7, latency_ms=1.0,
        )
        events = [json.loads(l) for l in
                  (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines() if l]
        types = [e["event_type"] for e in events]
        assert "pattern_reformulated_search" in types

    def test_pattern_not_emitted_for_distinct_queries(self, tmp_path: Path):
        from ctxpack.core.code.telemetry import CodeTelemetry
        tel = CodeTelemetry(path=tmp_path / "t.jsonl", session_id="dddd",
                            pack_version="v1")
        tel.log_search_symbols(
            query="create user", k=10, n_returned=5, alpha=0.7, latency_ms=1.0,
        )
        tel.log_search_symbols(
            query="delete order", k=10, n_returned=5, alpha=0.7, latency_ms=1.0,
        )
        events = [json.loads(l) for l in
                  (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines() if l]
        types = [e["event_type"] for e in events]
        assert "pattern_reformulated_search" not in types


# ── Summary aggregation ───────────────────────────────────────────────


class TestSummary:
    def test_counts_and_rates(self, tmp_path: Path):
        from ctxpack.core.code.telemetry import CodeTelemetry
        tel = CodeTelemetry(path=tmp_path / "t.jsonl", session_id="eeee",
                            pack_version="v1")
        tel.log_hydrate_symbol(
            name="x.py::a", depth=0, success=True, latency_ms=0.5,
        )
        tel.log_hydrate_symbol(
            name="x.py::missing", depth=0, success=False, latency_ms=0.5,
        )
        tel.log_symbol_not_in_pack(name="x.py::missing")
        s = tel.summary()
        assert s["by_type"]["hydrate_symbol_call"] == 2
        assert s["by_type"]["symbol_not_in_pack"] == 1
        assert s["rates"]["unknown_symbol_rate"] == 0.5


# ── Pack-version reset clears state ───────────────────────────────────


class TestPackVersionReset:
    def test_state_reset_on_new_pack(self, tmp_path: Path):
        from ctxpack.core.code.telemetry import CodeTelemetry
        tel = CodeTelemetry(path=tmp_path / "t.jsonl", session_id="ffff",
                            pack_version="v1")
        tel.log_hydrate_symbol(
            name="src/x.py::foo", depth=0, success=True, latency_ms=0.5,
        )
        tel.set_pack_version("v2")
        # raw_file in same path should NOT trigger the pattern — state
        # was cleared because the pack changed.
        tel.log_raw_file(path="src/x.py", success=True, latency_ms=0.5)
        events = [json.loads(l) for l in
                  (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines() if l]
        types = [e["event_type"] for e in events]
        assert "pattern_raw_file_after_hydrate" not in types


# ── Disabled telemetry ────────────────────────────────────────────────


class TestDisabled:
    def test_disabled_writes_nothing(self, tmp_path: Path):
        from ctxpack.core.code.telemetry import CodeTelemetry
        path = tmp_path / "t.jsonl"
        tel = CodeTelemetry(path=path, session_id="gggg", enabled=False)
        tel.log_hydrate_symbol(
            name="x.py::y", depth=0, success=True, latency_ms=0.1,
        )
        assert not path.exists()


# ── pack.py integration ───────────────────────────────────────────────


class TestPackIntegration:
    def test_pack_helpers_emit_when_telemetry_passed(self, tmp_path: Path):
        from ctxpack.core.code.pack import (
            pack_codebase, hydrate_symbol, list_symbols, raw_file, search_symbols,
        )
        from ctxpack.core.code.telemetry import CodeTelemetry
        (tmp_path / "x.py").write_text("def foo():\n    return 1\n")
        pack = pack_codebase(tmp_path)
        log_path = tmp_path / "code-telemetry.jsonl"
        tel = CodeTelemetry(path=log_path, session_id="aaaa")
        tel.set_pack_version(pack.version)
        list_symbols(pack, "x.py", k=5, context="foo", telemetry=tel)
        ent = next(e for e in pack.entities if e.name.endswith("::foo"))
        hydrate_symbol(pack, ent.name, depth=0, telemetry=tel)
        search_symbols(pack, "foo", k=5, telemetry=tel)
        raw_file(pack, "x.py", telemetry=tel)
        events = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines() if l]
        types = [e["event_type"] for e in events]
        assert "list_symbols_call" in types
        assert "hydrate_symbol_call" in types
        assert "search_symbols_call" in types
        assert "raw_file_call" in types
        # raw_file after hydrate on the same file should emit pattern
        assert "pattern_raw_file_after_hydrate" in types

    def test_pack_helpers_silent_without_telemetry(self, tmp_path: Path):
        """No telemetry kwarg → no file writes, no exceptions."""
        from ctxpack.core.code.pack import pack_codebase, hydrate_symbol
        (tmp_path / "x.py").write_text("def foo(): pass\n")
        pack = pack_codebase(tmp_path)
        ent = next(e for e in pack.entities if e.name.endswith("::foo"))
        result = hydrate_symbol(pack, ent.name)
        assert "error" not in result
        # No file written anywhere unexpected
        assert not (Path(pack.root) / ".ctx-cache" / "code-telemetry.jsonl").exists()
