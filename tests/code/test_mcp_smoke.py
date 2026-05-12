"""CP-031 — end-to-end smoke test for the code-packer MCP tools.

Exercises the handlers as the MCP server would invoke them (string-in,
JSON-string-out). Validates each tool's contract without spinning up
the full MCP stack — that's a separate integration test we'd add
in v0.1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "py_fastapi_min"


@pytest.fixture
def loaded_pack():
    """Pack the FastAPI fixture and yield. Resets the module-global
    cache so each test gets a clean pack."""
    from ctxpack.integrations import mcp_server
    mcp_server._CODE_PACK = None
    out = json.loads(
        mcp_server.handle_code_pack({"root": str(_FIXTURE_ROOT)})
    )
    assert "error" not in out, out
    yield out
    mcp_server._CODE_PACK = None


class TestPackHandler:
    def test_pack_returns_version_and_counts(self, loaded_pack):
        assert len(loaded_pack["pack_version"]) == 64  # sha256 hex
        assert loaded_pack["files"] >= 3
        assert loaded_pack["entities"] >= 4

    def test_pack_missing_root_is_invalid_input(self):
        from ctxpack.integrations import mcp_server
        mcp_server._CODE_PACK = None
        out = json.loads(mcp_server.handle_code_pack({}))
        assert out["error"]["code"] == "invalid_input"

    def test_pack_nonexistent_root_errors(self):
        from ctxpack.integrations import mcp_server
        mcp_server._CODE_PACK = None
        out = json.loads(
            mcp_server.handle_code_pack({"root": "/does/not/exist"})
        )
        assert out["error"]["code"] == "path_outside_root"


class TestVersionHandler:
    def test_version_after_pack(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        out = json.loads(mcp_server.handle_code_version({}))
        assert out["pack_version"] == loaded_pack["pack_version"]
        assert out["entities"] == loaded_pack["entities"]

    def test_version_without_pack(self):
        from ctxpack.integrations import mcp_server
        mcp_server._CODE_PACK = None
        out = json.loads(mcp_server.handle_code_version({}))
        assert out["error"]["code"] == "pack_not_loaded"


class TestListSymbolsHandler:
    def test_lists_app_py(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        out = json.loads(
            mcp_server.handle_code_list_symbols(
                {"module": "app.py", "k": 10}
            )
        )
        names = {s["name"] for s in out["symbols"]}
        assert any(n.endswith("::read_user") for n in names)

    def test_unknown_module(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        out = json.loads(
            mcp_server.handle_code_list_symbols({"module": "nope.py"})
        )
        assert out["error"]["code"] == "unknown_module"


class TestHydrateSymbolHandler:
    def test_returns_fields(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        # Get a known symbol via list_symbols
        listed = json.loads(
            mcp_server.handle_code_list_symbols({"module": "app.py", "k": 5})
        )
        name = next(s["name"] for s in listed["symbols"]
                    if s["name"].endswith("::read_user"))
        out = json.loads(
            mcp_server.handle_code_hydrate_symbol(
                {"name": name, "depth": 0}
            )
        )
        assert "error" not in out
        assert out["fields"]["http_method"] == "GET"
        assert "signature" in out["fields"]
        assert "body" in out["fields"]

    def test_depth_one_includes_neighbours(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        listed = json.loads(
            mcp_server.handle_code_list_symbols({"module": "app.py", "k": 5})
        )
        name = next(s["name"] for s in listed["symbols"]
                    if s["name"].endswith("::read_user"))
        out = json.loads(
            mcp_server.handle_code_hydrate_symbol(
                {"name": name, "depth": 1}
            )
        )
        assert "neighbours" in out

    def test_unknown_symbol(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        out = json.loads(
            mcp_server.handle_code_hydrate_symbol({"name": "no::such"})
        )
        assert out["error"]["code"] == "unknown_symbol"


class TestSearchHandler:
    def test_finds_user(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        out = json.loads(
            mcp_server.handle_code_search_symbols({"query": "user"})
        )
        assert any("user" in s["name"].lower() for s in out["symbols"])

    def test_empty_query_errors(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        out = json.loads(
            mcp_server.handle_code_search_symbols({"query": "   "})
        )
        assert out["error"]["code"] == "invalid_input"


class TestRawFileHandler:
    def test_returns_content(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        out = json.loads(
            mcp_server.handle_code_raw_file({"path": "deps.py"})
        )
        assert "def get_db" in out["content"]

    def test_path_traversal_blocked(self, loaded_pack):
        from ctxpack.integrations import mcp_server
        out = json.loads(
            mcp_server.handle_code_raw_file(
                {"path": "../../../etc/passwd"}
            )
        )
        assert out["error"]["code"] == "path_outside_root"


class TestHandlersAdvertised:
    def test_all_code_tools_listed_in_TOOLS(self):
        from ctxpack.integrations.mcp_server import TOOLS, _HANDLERS
        names = {t.name for t in TOOLS}
        for code_tool in (
            "ctx/code_pack",
            "ctx/code_version",
            "ctx/code_list_symbols",
            "ctx/code_hydrate_symbol",
            "ctx/code_search_symbols",
            "ctx/code_raw_file",
        ):
            assert code_tool in names, f"{code_tool} missing from TOOLS"
            assert code_tool in _HANDLERS, f"{code_tool} missing from _HANDLERS"
