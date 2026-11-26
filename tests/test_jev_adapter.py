"""Jev adapter: off and replay are network-free. Shadow stays advisory."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from ctxpack.agent.jev_adapter import (
    DEFAULT_MODEL,
    QUESTIONS,
    AdvisoryResult,
    JevAdapter,
    JevClient,
    ReplayMiss,
)


class _BoomSocket(socket.socket):
    def connect(self, address):  # type: ignore[override]
        raise AssertionError(f"network connect to {address}")

    def connect_ex(self, address):  # type: ignore[override]
        raise AssertionError(f"network connect to {address}")


@pytest.fixture
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(socket, "socket", _BoomSocket)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr("urllib.request.urlopen", _blocked)


def test_off_mode_is_passthrough_and_pinned(block_network: None, tmp_path: Path) -> None:
    facts = [{"fact_id": "bbbb", "text": "second"}, {"fact_id": "aaaa", "text": "first"}]
    adapter = JevAdapter()
    assert adapter.mode == "off"
    assert adapter.model == DEFAULT_MODEL == "jev-1.13.0"
    selected = adapter.filter_live_facts(facts, "widget")
    assert selected.network is False
    assert selected.selected_fact_ids == ("bbbb", "aaaa")
    assert selected.answers == ()
    assert facts == [
        {"fact_id": "bbbb", "text": "second"},
        {"fact_id": "aaaa", "text": "first"},
    ]
    assessed = adapter.assess_checkpoint("diff", ["keep the floor"], "body")
    assert assessed.answers == ()
    assert assessed.network is False
    assert assessed.error is None
    assert list(tmp_path.iterdir()) == []


def test_rejects_floating_model_unless_overridden(block_network: None) -> None:
    with pytest.raises(ValueError, match="exact pin"):
        JevAdapter(model="latest")
    with pytest.raises(ValueError, match="exact pin"):
        JevAdapter(model="jev-1.13")
    with pytest.raises(ValueError, match="exact pin"):
        JevAdapter(model="jev-1.13.*")
    allowed = JevAdapter(model="latest", allow_unpinned=True)
    assert allowed.model == "latest"
    pinned = JevAdapter(model="jev-1.2.3")
    assert pinned.model == "jev-1.2.3"


def test_url_must_be_https(block_network: None) -> None:
    with pytest.raises(ValueError, match="https://"):
        JevClient(mode="off", url="http://api.typesafe.ai/v1/systemone")
    with pytest.raises(ValueError, match="https://"):
        JevClient(mode="shadow", url="http://127.0.0.1/v1/systemone", api_key="secret-key")
    client = JevClient(mode="off", url="https://api.typesafe.ai/v1/systemone")
    assert client.url.startswith("https://")


def test_replay_filter_and_assess(block_network: None, tmp_path: Path) -> None:
    cassette = tmp_path / "replay.jsonl"
    rows = [
        {
            "op": "filter",
            "query": "widget",
            "selected_fact_ids": ["aaaa"],
        },
        {
            "op": "assess",
            "diff_summary": "diff",
            "pr_body": "body",
            "constraints": ["keep the floor"],
            "answers": {
                "constraint_breach": "no",
                "silent_spec_change": "yes",
                "summary_overclaim": "uncertain",
                "stuck_loop": "no",
            },
        },
    ]
    cassette.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8", newline="\n")
    adapter = JevAdapter(mode="replay", replay_path=cassette)
    facts = [{"fact_id": "aaaa"}, {"fact_id": "bbbb"}]
    selected = adapter.filter_live_facts(facts, "widget")
    assert selected.selected_fact_ids == ("aaaa",)
    assert selected.network is False
    assert facts == [{"fact_id": "aaaa"}, {"fact_id": "bbbb"}]
    assessed = adapter.assess_checkpoint("diff", ["keep the floor"], "body")
    assert assessed.network is False
    assert tuple(row.question for row in assessed.answers) == QUESTIONS
    assert [row.answer for row in assessed.answers] == [
        "no", "yes", "uncertain", "no"]
    with pytest.raises(ReplayMiss):
        adapter.filter_live_facts(facts, "missing-query")
    rendered = json.dumps(assessed.to_dict(), sort_keys=True)
    assert DEFAULT_MODEL in rendered
    assert "\r" not in rendered


def test_shadow_does_not_raise_or_leak_the_key(block_network: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {"calls": 0}

    def transport(url: str, payload: dict) -> dict:
        seen["calls"] = int(seen["calls"]) + 1
        seen["url"] = url
        seen["model"] = payload["model"]
        blob = json.dumps(payload)
        assert "secret-key" not in blob
        raise RuntimeError("boom secret-key")

    adapter = JevAdapter(
        mode="shadow", api_key="secret-key", transport=transport)
    result = adapter.assess_checkpoint("diff", ["constraint"], "pr")
    assert isinstance(result, AdvisoryResult)
    assert result.error == "RuntimeError"
    assert result.network is True
    assert "secret-key" not in json.dumps(result.to_dict())
    assert seen["model"] == "jev-1.13.0"
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    quiet = JevClient(mode="shadow", transport=transport)
    missing = JevAdapter(client=quiet).filter_live_facts(
        [{"fact_id": "aaaa"}], "q")
    assert missing.error == "api key absent"
    assert missing.network is False
    assert seen["calls"] == 1
