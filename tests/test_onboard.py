"""ctxpack onboard — one-command session-memory setup for any repo."""

import json

from ctxpack.cli.main import _CLAUDE_MD_MARKER, main


def _onboard(project_dir):
    return main(["onboard", "--project-dir", str(project_dir)])


def test_onboard_fresh_repo(tmp_path):
    assert _onboard(tmp_path) == 0

    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert set(settings["hooks"]) >= {"PreCompact", "SessionStart",
                                      "SessionEnd"}

    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["ctxpack"]["args"] == [
        "-m", "ctxpack.integrations.mcp_server"]

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert _CLAUDE_MD_MARKER in claude_md
    assert "Decision:" in claude_md          # the load-bearing convention
    assert "ctxpack session" in claude_md    # the read path
    assert (tmp_path / ".claude" / "ctx").is_dir()


def test_onboard_is_idempotent(tmp_path):
    assert _onboard(tmp_path) == 0
    assert _onboard(tmp_path) == 0

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md.count(_CLAUDE_MD_MARKER) == 1, "block duplicated"

    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for event in ("PreCompact", "SessionStart", "SessionEnd"):
        ctx_entries = [e for e in settings["hooks"][event]
                       if any("ctxpack" in str(h.get("command", ""))
                              for h in e.get("hooks", []))]
        assert len(ctx_entries) == 1, f"{event} hook duplicated"


def test_onboard_preserves_existing_config(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# My project\n\nExisting instructions.\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"other": {"command": "node", "args": ["s.js"]}}
    }), encoding="utf-8")

    assert _onboard(tmp_path) == 0

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Existing instructions." in claude_md
    assert _CLAUDE_MD_MARKER in claude_md

    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "other" in mcp["mcpServers"]      # untouched
    assert "ctxpack" in mcp["mcpServers"]    # added


def test_onboard_refuses_unparseable_mcp_json(tmp_path):
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")
    assert _onboard(tmp_path) == 1
    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == "{not json"
