"""Tests for Phase B: WS7 (Diff engine + test coverage gaps).

Covers diff_documents, format_diff, DiffResult counts, and CLI integration.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from ctxpack.core.model import (
    CTXDocument,
    Header,
    KeyValue,
    Layer,
    PlainLine,
    Provenance,
    Section,
)
from ctxpack.core.errors import Span
from ctxpack.core.diff import diff_documents, format_diff, DiffResult
from ctxpack.core.serializer import serialize
from ctxpack.core.parser import parse
from ctxpack.cli.main import main


# ── Helpers ──────────────────────────────────────────


def _make_l2_doc(sections, domain="test"):
    """Build a synthetic L2 CTXDocument with the given body sections."""
    return CTXDocument(
        header=Header(
            magic="§CTX",
            version="1.0",
            layer=Layer.L2,
            status_fields=(KeyValue(key="DOMAIN", value=domain),),
            metadata=(
                KeyValue(key="SOURCE_TOKENS", value="~1000"),
                KeyValue(key="CTX_TOKENS", value="~200"),
            ),
        ),
        body=tuple(sections),
    )


def _base_doc():
    """A baseline document with two entity sections."""
    return _make_l2_doc([
        Section(
            name="ENTITY-CUSTOMER",
            children=(
                KeyValue(key="IDENTIFIER", value="cust_id(UUID)"),
                KeyValue(key="PII", value="name+email"),
            ),
        ),
        Section(
            name="ENTITY-ORDER",
            children=(
                KeyValue(key="IDENTIFIER", value="order_id(int)"),
                KeyValue(key="BELONGS-TO", value="@ENTITY-CUSTOMER"),
            ),
        ),
    ])


# ═══════════════════════════════════════════════════════
# WS7: Diff Engine
# ═══════════════════════════════════════════════════════


class TestDiffIdentical:
    """Test 1: identical documents produce no changes."""

    def test_identical_documents_no_changes(self):
        """D1: Diffing a document against itself yields zero entries."""
        doc = _base_doc()
        result = diff_documents(doc, doc)
        assert not result.has_changes
        assert len(result.entries) == 0


class TestDiffAddedSection:
    """Test 2: added section detected."""

    def test_added_section_detected(self):
        """D2: A new section in the second document is reported as added."""
        old = _base_doc()
        new_sections = list(old.body) + [
            Section(
                name="ENTITY-PRODUCT",
                children=(
                    KeyValue(key="IDENTIFIER", value="sku(string)"),
                ),
            ),
        ]
        new = _make_l2_doc(new_sections)
        result = diff_documents(old, new)

        assert result.has_changes
        added = [e for e in result.entries if e.kind == "added"]
        added_paths = [e.path for e in added]
        assert any("ENTITY-PRODUCT" in p for p in added_paths), (
            f"Expected ENTITY-PRODUCT in added paths: {added_paths}"
        )


class TestDiffRemovedSection:
    """Test 3: removed section detected."""

    def test_removed_section_detected(self):
        """D3: A section present only in the first document is reported as removed."""
        old = _base_doc()
        # New doc has only the first section
        new = _make_l2_doc([old.body[0]])
        result = diff_documents(old, new)

        assert result.has_changes
        removed = [e for e in result.entries if e.kind == "removed"]
        removed_paths = [e.path for e in removed]
        assert any("ENTITY-ORDER" in p for p in removed_paths), (
            f"Expected ENTITY-ORDER in removed paths: {removed_paths}"
        )


class TestDiffChangedKV:
    """Test 4: changed KV value detected."""

    def test_changed_kv_value_detected(self):
        """D4: A changed KV value in a section is reported as changed."""
        old = _base_doc()
        new = _make_l2_doc([
            Section(
                name="ENTITY-CUSTOMER",
                children=(
                    KeyValue(key="IDENTIFIER", value="cust_id(int)"),  # changed from UUID
                    KeyValue(key="PII", value="name+email"),
                ),
            ),
            Section(
                name="ENTITY-ORDER",
                children=(
                    KeyValue(key="IDENTIFIER", value="order_id(int)"),
                    KeyValue(key="BELONGS-TO", value="@ENTITY-CUSTOMER"),
                ),
            ),
        ])
        result = diff_documents(old, new)

        assert result.has_changes
        changed = [e for e in result.entries if e.kind == "changed"]
        assert len(changed) >= 1
        id_change = next(
            (e for e in changed if "IDENTIFIER" in e.path), None
        )
        assert id_change is not None, f"Expected IDENTIFIER change, got: {changed}"
        assert "UUID" in id_change.old_value
        assert "int" in id_change.new_value


class TestDiffAddedHeaderField:
    """Test 5: added header field detected."""

    def test_added_header_field_detected(self):
        """D5: A new header metadata field is reported as added."""
        old = _base_doc()
        new = CTXDocument(
            header=Header(
                magic="§CTX",
                version="1.0",
                layer=Layer.L2,
                status_fields=(KeyValue(key="DOMAIN", value="test"),),
                metadata=(
                    KeyValue(key="SOURCE_TOKENS", value="~1000"),
                    KeyValue(key="CTX_TOKENS", value="~200"),
                    KeyValue(key="COMPRESSED", value="2026-02-23"),  # new field
                ),
            ),
            body=old.body,
        )
        result = diff_documents(old, new)

        assert result.has_changes
        added = [e for e in result.entries if e.kind == "added"]
        added_paths = [e.path for e in added]
        assert any("COMPRESSED" in p for p in added_paths), (
            f"Expected COMPRESSED in added paths: {added_paths}"
        )


class TestDiffChangedHeaderField:
    """Test 6: changed header field detected."""

    def test_changed_header_field_detected(self):
        """D6: A changed header field is reported as changed."""
        old = _base_doc()
        new = CTXDocument(
            header=Header(
                magic="§CTX",
                version="1.0",
                layer=Layer.L2,
                status_fields=(KeyValue(key="DOMAIN", value="test"),),
                metadata=(
                    KeyValue(key="SOURCE_TOKENS", value="~2000"),  # changed
                    KeyValue(key="CTX_TOKENS", value="~200"),
                ),
            ),
            body=old.body,
        )
        result = diff_documents(old, new)

        assert result.has_changes
        changed = [e for e in result.entries if e.kind == "changed"]
        src_change = next(
            (e for e in changed if "SOURCE_TOKENS" in e.path), None
        )
        assert src_change is not None
        assert src_change.old_value == "~1000"
        assert src_change.new_value == "~2000"


class TestFormatDiffAdded:
    """Test 7: format_diff uses '+' prefix for added entries."""

    def test_added_entry_plus_prefix(self):
        """D7: Added entries formatted with '+' prefix."""
        result = DiffResult(entries=[
            DiffResult.__class__.__mro__[0]  # dummy to avoid import
        ])
        # Build manually
        from ctxpack.core.diff import DiffEntry
        result = DiffResult(entries=[
            DiffEntry(kind="added", path="±ENTITY-NEW", new_value=""),
        ])
        text = format_diff(result)
        assert text.startswith("+ ")
        assert "ENTITY-NEW" in text


class TestFormatDiffRemoved:
    """Test 8: format_diff uses '-' prefix for removed entries."""

    def test_removed_entry_minus_prefix(self):
        """D8: Removed entries formatted with '-' prefix."""
        from ctxpack.core.diff import DiffEntry
        result = DiffResult(entries=[
            DiffEntry(kind="removed", path="±ENTITY-OLD", old_value=""),
        ])
        text = format_diff(result)
        assert text.startswith("- ")
        assert "ENTITY-OLD" in text


class TestFormatDiffChanged:
    """Test 9: format_diff uses '~' prefix with arrow for changed entries."""

    def test_changed_entry_tilde_prefix_with_arrow(self):
        """D9: Changed entries formatted with '~' prefix and arrow separator."""
        from ctxpack.core.diff import DiffEntry
        result = DiffResult(entries=[
            DiffEntry(
                kind="changed",
                path="HEADER/SOURCE_TOKENS",
                old_value="~1000",
                new_value="~2000",
            ),
        ])
        text = format_diff(result)
        assert text.startswith("~ ")
        assert "\u2192" in text or "->" in text or " → " in text  # arrow char
        assert "~1000" in text
        assert "~2000" in text


class TestFormatDiffNoChanges:
    """Test 10: format_diff with empty result shows '(no changes)'."""

    def test_no_changes_message(self):
        """D10: Empty DiffResult formats as '(no changes)'."""
        result = DiffResult()
        text = format_diff(result)
        assert text == "(no changes)"


class TestDiffResultCounts:
    """Test 11: DiffResult count properties."""

    def test_counts(self):
        """D11: added_count, removed_count, changed_count are correct."""
        from ctxpack.core.diff import DiffEntry
        result = DiffResult(entries=[
            DiffEntry(kind="added", path="a"),
            DiffEntry(kind="added", path="b"),
            DiffEntry(kind="removed", path="c"),
            DiffEntry(kind="changed", path="d", old_value="x", new_value="y"),
            DiffEntry(kind="changed", path="e", old_value="x", new_value="y"),
            DiffEntry(kind="changed", path="f", old_value="x", new_value="y"),
        ])
        assert result.added_count == 2
        assert result.removed_count == 1
        assert result.changed_count == 3
        assert result.has_changes


class TestDiffCLIIntegration:
    """Test 12: CLI diff command via main() with temp files."""

    def test_cli_diff_identical_files(self):
        """D12a: CLI diff of identical files returns exit code 0."""
        doc = _base_doc()
        text = serialize(doc)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ctx", delete=False, encoding="utf-8"
        ) as f1:
            f1.write(text)
            path1 = f1.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ctx", delete=False, encoding="utf-8"
        ) as f2:
            f2.write(text)
            path2 = f2.name

        try:
            exit_code = main(["diff", path1, path2])
            assert exit_code == 0
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_cli_diff_different_files(self):
        """D12b: CLI diff of different files returns exit code 1."""
        old = _base_doc()
        new = _make_l2_doc([
            Section(
                name="ENTITY-CUSTOMER",
                children=(
                    KeyValue(key="IDENTIFIER", value="cust_id(int)"),  # changed
                ),
            ),
        ])

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ctx", delete=False, encoding="utf-8"
        ) as f1:
            f1.write(serialize(old))
            path1 = f1.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ctx", delete=False, encoding="utf-8"
        ) as f2:
            f2.write(serialize(new))
            path2 = f2.name

        try:
            exit_code = main(["diff", path1, path2])
            assert exit_code == 1
        finally:
            os.unlink(path1)
            os.unlink(path2)
