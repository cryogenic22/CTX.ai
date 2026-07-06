"""Coordination status reporter — the two parser bugs Codex flagged.

`scripts/` is not a package, so load the module by path.
"""

import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts",
                     "coordination_check.py")
_spec = importlib.util.spec_from_file_location("coordination_check", _PATH)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def test_field_preserves_bold_inside_the_value():
    # bold is stripped only around the LABEL, not inside the value — a glob
    # like benchmarks/**/results/ must keep its `**`
    lines = ["- **Do not touch:** `CLAUDE.md`; ctxpack/benchmarks/**/results/"]
    assert cc._field(lines, "Do not touch") == \
        "`CLAUDE.md`; ctxpack/benchmarks/**/results/"


def test_field_handles_colon_outside_bold():
    assert cc._field(["- **Branch**: feat/x"], "Branch") == "feat/x"


def test_unresolved_note_is_not_matched_by_substring():
    # "unresolved" contains "resolved" — a substring check would wrongly
    # count this note as resolved
    lines = ["### 2026-07-06 — Codex",
             "- Finding: something",
             "- Status: unresolved"]
    assert cc._unresolved_notes(lines) == ["2026-07-06 — Codex"]


def test_resolved_note_is_excluded():
    lines = ["### 2026-07-06 — Codex",
             "- Status: resolved (fixed in abc1234)"]
    assert cc._unresolved_notes(lines) == []


def test_note_without_status_counts_as_unresolved():
    lines = ["### 2026-07-06 — Codex", "- Finding: no status line here"]
    assert cc._unresolved_notes(lines) == ["2026-07-06 — Codex"]
