"""_annotate_authority returns the journal it stamps onto matches."""
from __future__ import annotations

from ctxpack.agent.session_reader import _annotate_authority


def _matches():
    return [{
        "fields": [
            {"key": "FACT-ID", "value": "abc123"},
            {"key": "SOURCE-ROLE", "value": "assistant"},
        ],
    }]


def test_return_annotation_is_the_journal_dict():
    assert _annotate_authority.__annotations__["return"] == "dict[str, Any]"


def test_returns_journal_and_stamps_axes(tmp_path):
    matches = _matches()
    journal = _annotate_authority(matches, str(tmp_path))
    assert isinstance(journal, dict)
    assert journal["degraded"] is False
    assert journal["malformed_rows"] == 0
    assert journal["state"] == {}
    assert "authority" in matches[0]
    assert matches[0]["owner_approval"] == "unavailable"
    assert "local_ratification" not in matches[0]


def test_missing_ledger_dir_still_returns_a_journal():
    matches = _matches()
    journal = _annotate_authority(matches, None)
    assert journal["degraded"] is False
    assert journal["quarantined"] == 0
    assert matches[0]["owner_approval"] == "unavailable"
