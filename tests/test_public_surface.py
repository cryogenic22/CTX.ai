"""Snapshot of the intentional CLI and MCP surface."""

from __future__ import annotations

import pytest

from ctxpack import __all__ as ctxpack_all
from ctxpack.cli.main import main

EXPECTED_COMMANDS = {
    "ack",
    "backfill",
    "bench",
    "brief",
    "checkpoint",
    "codebase",
    "diff",
    "dream",
    "elicit",
    "eval",
    "fmt",
    "hook",
    "hydrate",
    "identity",
    "install-hooks",
    "lessons",
    "onboard",
    "pack",
    "parse",
    "retention",
    "scaling",
    "scorecard",
    "session",
    "telemetry",
    "validate",
    "verify",
}

EXPECTED_TOOLS = {
    "ctx/brief",
    "ctx/checkpoint",
    "ctx/code_hydrate_symbol",
    "ctx/code_list_symbols",
    "ctx/code_pack",
    "ctx/code_raw_file",
    "ctx/code_search_symbols",
    "ctx/code_telemetry",
    "ctx/code_version",
    "ctx/format",
    "ctx/graph_query",
    "ctx/hydrate",
    "ctx/pack",
    "ctx/parse",
    "ctx/resume",
    "ctx/session_decisions",
    "ctx/session_literals",
    "ctx/session_recall",
    "ctx/session_timeline",
    "ctx/validate",
    "ctx/why",
}


def test_public_python_api_is_explicit():
    assert "brief" in ctxpack_all
    assert "__version__" in ctxpack_all
    import ctxpack
    assert callable(ctxpack.brief)


def test_cli_help_names_the_intentional_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "MP3" not in text
    assert "session memory" in text
    # argparse prints the subcommand set inside the usage braces.
    start = text.find("{")
    end = text.find("}")
    assert start != -1 and end > start
    listed = {part.strip() for part in text[start + 1:end].split(",")}
    assert listed == EXPECTED_COMMANDS


def test_mcp_tool_names_are_the_intentional_set():
    from ctxpack.integrations.mcp_server import TOOLS
    assert {tool.name for tool in TOOLS} == EXPECTED_TOOLS
