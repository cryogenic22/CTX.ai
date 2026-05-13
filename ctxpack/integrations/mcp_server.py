"""CtxPack MCP Server — expose ctx/pack, ctx/parse, ctx/validate, ctx/format as MCP tools.

Usage:
    python -m ctxpack.integrations.mcp_server          # stdio transport (default)
    python -m ctxpack.integrations.mcp_server --port 8080  # HTTP transport

Requires: mcp (pip install mcp)

This server exposes five tools:
  ctx/pack      — Pack a corpus directory into .ctx format
  ctx/parse     — Parse a .ctx file/string into structured output
  ctx/validate  — Validate a .ctx file and return diagnostics
  ctx/format    — Reformat a .ctx file (canonical, ASCII, natural language)
  ctx/hydrate   — Query-adaptive section retrieval from a .ctx file
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any, Optional  # noqa: F401

# ── MCP SDK import ──
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    HAS_MCP = True
except ImportError:
    HAS_MCP = False

# ── CtxPack imports ──
from ..core.errors import DiagnosticLevel, ParseError
from ..core.json_export import to_json
from ..core.parser import parse
from ..core.serializer import serialize, serialize_iter, serialize_section
from ..core.telemetry import TelemetryLog
from ..core.validator import validate

# Packer import (may fail if corpus tools not needed)
try:
    from ..core.packer import PackResult, pack
    HAS_PACKER = True
except ImportError:
    HAS_PACKER = False

# Code packer (optional — tree-sitter + tiktoken via [code] extra)
try:
    from ..core.code.pack import (
        Pack as CodePack,
        hydrate_symbol as code_hydrate_symbol,
        list_symbols as code_list_symbols,
        pack_codebase,
        pack_version as code_pack_version,
        raw_file as code_raw_file,
        render_manifest as code_render_manifest,
        search_symbols as code_search_symbols,
    )
    HAS_CODE_PACKER = True
except ImportError:
    HAS_CODE_PACKER = False
    CodePack = None  # type: ignore[assignment]

# Shared cache: the most recently built code pack. Re-set every time
# ctx/code_pack runs so subsequent tool calls operate on a consistent
# snapshot. Single-pack-at-a-time model is the v0 simplification;
# multi-pack support is a v0.1 item.
_CODE_PACK: "Optional[CodePack]" = None


# ── Tool definitions ──

TOOLS = [
    Tool(
        name="ctx/pack",
        description=(
            "Pack a corpus directory (YAML, Markdown, JSON files) into compressed .ctx format. "
            "Returns the .ctx text and compression metrics."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "corpus_dir": {
                    "type": "string",
                    "description": "Path to the corpus directory containing source files",
                },
                "domain": {
                    "type": "string",
                    "description": "Domain label (e.g. 'pharma', 'finserv')",
                },
                "scope": {
                    "type": "string",
                    "description": "Scope label (e.g. 'data-governance')",
                },
                "author": {
                    "type": "string",
                    "description": "Author identifier",
                },
                "strict": {
                    "type": "boolean",
                    "description": "If true, only emit EXPLICIT certainty fields (no inferences)",
                    "default": False,
                },
                "layers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["L2", "L3"]},
                    "description": "Which layers to generate (default: ['L2'])",
                },
                "ascii_mode": {
                    "type": "boolean",
                    "description": "Use ASCII-only operators instead of Unicode",
                    "default": False,
                },
            },
            "required": ["corpus_dir"],
        },
    ),
    Tool(
        name="ctx/parse",
        description=(
            "Parse a .ctx file or string into a structured JSON AST. "
            "Returns the document structure with header, sections, and elements."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to a .ctx file to parse",
                },
                "text": {
                    "type": "string",
                    "description": "Raw .ctx text to parse (alternative to file_path)",
                },
                "level": {
                    "type": "integer",
                    "description": "Conformance level: 1 (header only), 2 (full structure), 3 (operators + cross-refs)",
                    "default": 2,
                    "enum": [1, 2, 3],
                },
            },
        },
    ),
    Tool(
        name="ctx/validate",
        description=(
            "Validate a .ctx file against the CTXPACK-SPEC. "
            "Returns a list of errors and warnings with line numbers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to a .ctx file to validate",
                },
                "text": {
                    "type": "string",
                    "description": "Raw .ctx text to validate (alternative to file_path)",
                },
                "level": {
                    "type": "integer",
                    "description": "Conformance level (1, 2, or 3)",
                    "default": 2,
                    "enum": [1, 2, 3],
                },
            },
        },
    ),
    Tool(
        name="ctx/format",
        description=(
            "Reformat a .ctx file. Modes: canonical (sorted fields), "
            "ASCII (Unicode→ASCII fallbacks), natural-language (readable prose)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to a .ctx file to format",
                },
                "text": {
                    "type": "string",
                    "description": "Raw .ctx text to format (alternative to file_path)",
                },
                "canonical": {
                    "type": "boolean",
                    "description": "Sort header fields by spec order",
                    "default": False,
                },
                "ascii_mode": {
                    "type": "boolean",
                    "description": "Replace Unicode operators with ASCII",
                    "default": False,
                },
                "natural_language": {
                    "type": "boolean",
                    "description": "Emit readable L1 prose instead of .ctx notation",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="ctx/hydrate",
        description=(
            "Section-level retrieval from a .ctx document. Returns readable Markdown prose "
            "by default (NOT .ctx notation — LLMs cannot reliably consume .ctx format). "
            "Primary path: provide 'section' name(s) for direct lookup. "
            "Fallback: provide 'query' for keyword matching."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to a .ctx file",
                },
                "text": {
                    "type": "string",
                    "description": "Raw .ctx text (alternative to file_path)",
                },
                "section": {
                    "type": "string",
                    "description": "Section name to hydrate (e.g. 'ENTITY-CUSTOMER'). Comma-separated for multiple.",
                },
                "query": {
                    "type": "string",
                    "description": "Keyword query for section matching (fallback if section not provided)",
                },
                "max_sections": {
                    "type": "integer",
                    "description": "Maximum number of sections to return (default: 5)",
                    "default": 5,
                },
                "include_header": {
                    "type": "boolean",
                    "description": "Include the document header in output (default: true)",
                    "default": True,
                },
                "raw": {
                    "type": "boolean",
                    "description": "Return raw .ctx notation instead of prose. Only use for machine-to-machine (diff, validate). Default: false (prose).",
                    "default": False,
                },
            },
        },
    ),
]


_CODE_TOOLS = [
    Tool(
        name="ctx/code_pack",
        description=(
            "Pack a code repository (Python only at v0) into a queryable "
            "index of symbols, decorators, FastAPI routes, dependencies, "
            "and Pydantic models. Caches the pack server-side; "
            "follow-up tools (ctx/code_list_symbols, ctx/code_hydrate_symbol, "
            "etc.) operate on the most recently packed root."
        ),
        inputSchema={
            "type": "object",
            "required": ["root"],
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Absolute path to the codebase root.",
                },
                "include_body": {
                    "type": "boolean",
                    "description": "Include full source bodies on each entity. Default true.",
                    "default": True,
                },
            },
        },
    ),
    Tool(
        name="ctx/code_version",
        description="Return the content-hash pack_version. Cheap stale-pack probe.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="ctx/code_list_symbols",
        description=(
            "Return top-k symbols in a module, ranked by centrality. "
            "Returns catalog rows: '<qualified-name> | <kind> | <signature> | <docstring 1st line>'."
        ),
        inputSchema={
            "type": "object",
            "required": ["module"],
            "properties": {
                "module": {
                    "type": "string",
                    "description": "Module path relative to the pack root (e.g. 'src/api/routes.py').",
                },
                "k": {"type": "integer", "default": 50, "description": "Max symbols to return."},
                "context": {
                    "type": "string",
                    "description": "Optional working-set hint for per-turn ranking (currently logged, not used in ranking).",
                },
            },
        },
    ),
    Tool(
        name="ctx/code_hydrate_symbol",
        description=(
            "Return a symbol's full IRField content (signature, docstring, body, "
            "decorators, http_method/path, dependencies, pydantic_fields). "
            "depth=1 also returns 1-hop neighbour bodies budgeted to 4K BPE."
        ),
        inputSchema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Qualified symbol name (e.g. 'src/api/routes.py::create_user').",
                },
                "depth": {
                    "type": "integer",
                    "default": 0,
                    "description": "0 = just this symbol. 1 = also neighbour bodies (caller/callee), capped at 4K BPE.",
                },
            },
        },
    ),
    Tool(
        name="ctx/code_search_symbols",
        description=(
            "Fuzzy search across symbol names, signatures, and docstrings. "
            "Returns top-k matches ranked by hit location and centrality."
        ),
        inputSchema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Search text."},
                "k": {"type": "integer", "default": 10},
            },
        },
    ),
    Tool(
        name="ctx/code_raw_file",
        description=(
            "Escape hatch: return raw file bytes when the curated pack is insufficient. "
            "Subject only to .gitignore / .ctxpackignore exclusions. Path-traversal blocked."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "Path relative to the pack root."},
            },
        },
    ),
]

# Append code tools to the list MCP advertises.
TOOLS = TOOLS + _CODE_TOOLS


# ── Tool implementations ──


def _read_ctx_input(arguments: dict[str, Any]) -> str:
    """Read .ctx text from file_path or text argument."""
    if "text" in arguments and arguments["text"]:
        return arguments["text"]
    if "file_path" in arguments and arguments["file_path"]:
        path = arguments["file_path"]
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")
        with open(path, encoding="utf-8") as f:
            return f.read()
    raise ValueError("Provide either 'file_path' or 'text'")


def handle_pack(arguments: dict[str, Any]) -> str:
    """Handle ctx/pack tool call."""
    if not HAS_PACKER:
        return json.dumps({"error": "Packer module not available"})

    corpus_dir = arguments["corpus_dir"]
    if not os.path.isdir(corpus_dir):
        return json.dumps({"error": f"Directory not found: {corpus_dir}"})

    result = pack(
        corpus_dir,
        domain=arguments.get("domain"),
        scope=arguments.get("scope"),
        author=arguments.get("author"),
        strict=arguments.get("strict", False),
        layers=arguments.get("layers"),
    )

    ascii_mode = arguments.get("ascii_mode", False)
    ctx_text = serialize(result.document, ascii_mode=ascii_mode)

    output: dict[str, Any] = {
        "ctx_text": ctx_text,
        "metrics": {
            "source_tokens": result.source_token_count,
            "source_files": result.source_file_count,
            "entities": result.entity_count,
            "warnings": result.warning_count,
            "ctx_tokens": len(ctx_text.split()),
            "compression_ratio": round(
                result.source_token_count / max(len(ctx_text.split()), 1), 1
            ),
        },
    }

    if result.l3_document:
        output["l3_text"] = serialize(result.l3_document, ascii_mode=ascii_mode)
    if result.manifest_document:
        output["manifest_text"] = serialize(result.manifest_document, ascii_mode=ascii_mode)
    if result.provenance_text:
        output["provenance_text"] = result.provenance_text

    return json.dumps(output, indent=2)


def handle_parse(arguments: dict[str, Any]) -> str:
    """Handle ctx/parse tool call."""
    text = _read_ctx_input(arguments)
    level = arguments.get("level", 2)

    try:
        doc = parse(text, level=level)
    except ParseError as e:
        return json.dumps({"error": str(e)})

    return to_json(doc, indent=2)


def handle_validate(arguments: dict[str, Any]) -> str:
    """Handle ctx/validate tool call."""
    text = _read_ctx_input(arguments)
    level = arguments.get("level", 2)

    try:
        doc = parse(text, level=level)
    except ParseError as e:
        return json.dumps({
            "valid": False,
            "diagnostics": [{"level": "error", "message": str(e)}],
        })

    diagnostics = validate(doc, level=level)

    diag_list = []
    for d in diagnostics:
        entry: dict[str, Any] = {
            "level": d.level.value,
            "code": d.code,
            "message": d.message,
        }
        if d.span:
            entry["line"] = d.span.line
        diag_list.append(entry)

    errors = [d for d in diagnostics if d.level == DiagnosticLevel.ERROR]
    return json.dumps({
        "valid": len(errors) == 0,
        "errors": len(errors),
        "warnings": len(diagnostics) - len(errors),
        "diagnostics": diag_list,
    }, indent=2)


def handle_format(arguments: dict[str, Any]) -> str:
    """Handle ctx/format tool call."""
    text = _read_ctx_input(arguments)

    try:
        doc = parse(text, level=2)
    except ParseError as e:
        return json.dumps({"error": str(e)})

    formatted = serialize(
        doc,
        canonical=arguments.get("canonical", False),
        ascii_mode=arguments.get("ascii_mode", False),
        natural_language=arguments.get("natural_language", False),
    )
    return formatted


def handle_hydrate(arguments: dict[str, Any], telemetry: TelemetryLog | None = None) -> str:
    """Handle ctx/hydrate — section-level retrieval.

    Two paths:
    1. section param → direct name lookup (LLM-as-router, primary)
    2. query param → keyword matching (programmatic fallback)

    IMPORTANT: Output defaults to natural language prose (Markdown), NOT .ctx
    notation. LLMs cannot reliably consume .ctx L2 notation — they ignore it
    and fall back to training knowledge, causing hallucination. Set raw=true
    only for machine-to-machine use (diff, validate, version control).
    """
    from ..core.hydrator import hydrate_by_name, hydrate_by_query, list_sections

    text = _read_ctx_input(arguments)
    section_param = arguments.get("section", "")
    query = arguments.get("query", "")
    max_sections = arguments.get("max_sections", 5)
    include_header = arguments.get("include_header", True)
    raw_format = arguments.get("raw", False)  # Default: prose (not .ctx notation)

    try:
        doc = parse(text, level=2)
    except ParseError as e:
        return json.dumps({"error": str(e)})

    # Path 1: direct section lookup
    if section_param:
        names = [n.strip() for n in section_param.split(",") if n.strip()]
        result = hydrate_by_name(
            doc, names,
            include_header=include_header,
            telemetry=telemetry,
            question=query or section_param,
        )
    elif query:
        # Path 2: keyword-based matching
        result = hydrate_by_query(doc, query, max_sections=max_sections,
                                   include_header=include_header)
    else:
        # No section or query — return section listing
        sections_list = list_sections(doc)
        return json.dumps({
            "sections_matched": 0,
            "sections_available": len(sections_list),
            "available_sections": sections_list,
            "ctx_text": "",
        }, indent=2)

    # Serialize matched sections — prose by default, raw .ctx notation only if requested
    use_nl = not raw_format
    lines: list[str] = []
    if result.header_text:
        lines.append(result.header_text)
        lines.append("")

    for section in result.sections:
        for line in serialize_section(section, natural_language=use_nl):
            lines.append(line)
        lines.append("")

    return json.dumps({
        "sections_matched": len(result.sections),
        "sections_available": result.sections_available,
        "tokens_injected": result.tokens_injected,
        "format": "prose" if use_nl else "ctx",
        "ctx_text": "\n".join(lines),
    }, indent=2)


# ── Telemetry instance ──

_telemetry = TelemetryLog()


# ── Tool dispatch ──

# ── Code-packer tool handlers (CP-026/027/028/029/030/030.5) ──


def _no_code_packer() -> str:
    return json.dumps({
        "error": {
            "code": "internal_parse_error",
            "message": (
                "Code packer not available. Install the optional "
                "extra: pip install ctxpack[code]"
            ),
        }
    })


def handle_code_pack(arguments: dict[str, Any]) -> str:
    """Build a code pack from ``root`` and cache it for follow-up tools."""
    if not HAS_CODE_PACKER:
        return _no_code_packer()
    global _CODE_PACK
    root = arguments.get("root")
    if not root:
        return json.dumps({"error": {"code": "invalid_input",
                                     "message": "root is required"}})
    if not os.path.isdir(root):
        return json.dumps({"error": {"code": "path_outside_root",
                                     "message": f"Not a directory: {root}"}})
    include_body = bool(arguments.get("include_body", True))
    _CODE_PACK = pack_codebase(root, include_body=include_body)
    return json.dumps({
        "pack_version": _CODE_PACK.version,
        "files": len(_CODE_PACK.files),
        "entities": len(_CODE_PACK.entities),
        "warnings": len(_CODE_PACK.warnings),
        "root": _CODE_PACK.root,
        "manifest": code_render_manifest(_CODE_PACK),
    })


def _require_pack() -> "Optional[str]":
    """Return a JSON error string if no pack is loaded, else None."""
    if _CODE_PACK is None:
        return json.dumps({"error": {
            "code": "pack_not_loaded",
            "message": "Call ctx/code_pack(root) first.",
        }})
    return None


def handle_code_version(_arguments: dict[str, Any]) -> str:
    if not HAS_CODE_PACKER:
        return _no_code_packer()
    err = _require_pack()
    if err is not None:
        return err
    return json.dumps(code_pack_version(_CODE_PACK))


def handle_code_list_symbols(arguments: dict[str, Any]) -> str:
    if not HAS_CODE_PACKER:
        return _no_code_packer()
    err = _require_pack()
    if err is not None:
        return err
    module = arguments.get("module", "")
    k = int(arguments.get("k", 50))
    context = arguments.get("context")
    alpha = float(arguments.get("alpha", 0.7))
    return json.dumps(code_list_symbols(
        _CODE_PACK, module, k=k, context=context, alpha=alpha,
    ))


def handle_code_hydrate_symbol(arguments: dict[str, Any]) -> str:
    if not HAS_CODE_PACKER:
        return _no_code_packer()
    err = _require_pack()
    if err is not None:
        return err
    name = arguments.get("name", "")
    depth = int(arguments.get("depth", 0))
    return json.dumps(code_hydrate_symbol(_CODE_PACK, name, depth=depth))


def handle_code_search_symbols(arguments: dict[str, Any]) -> str:
    if not HAS_CODE_PACKER:
        return _no_code_packer()
    err = _require_pack()
    if err is not None:
        return err
    query = arguments.get("query", "")
    k = int(arguments.get("k", 10))
    alpha = float(arguments.get("alpha", 0.7))
    return json.dumps(code_search_symbols(_CODE_PACK, query, k=k, alpha=alpha))


def handle_code_raw_file(arguments: dict[str, Any]) -> str:
    if not HAS_CODE_PACKER:
        return _no_code_packer()
    err = _require_pack()
    if err is not None:
        return err
    path = arguments.get("path", "")
    return json.dumps(code_raw_file(_CODE_PACK, path))


_HANDLERS = {
    "ctx/pack": handle_pack,
    "ctx/parse": handle_parse,
    "ctx/validate": handle_validate,
    "ctx/format": handle_format,
    "ctx/hydrate": lambda args: handle_hydrate(args, telemetry=_telemetry),
    # Code-packer tools (CP-026/027/028/029/030.5)
    "ctx/code_pack": handle_code_pack,
    "ctx/code_version": handle_code_version,
    "ctx/code_list_symbols": handle_code_list_symbols,
    "ctx/code_hydrate_symbol": handle_code_hydrate_symbol,
    "ctx/code_search_symbols": handle_code_search_symbols,
    "ctx/code_raw_file": handle_code_raw_file,
}


# ── MCP Server setup ──

def create_server() -> "Server":
    """Create and configure the MCP server."""
    if not HAS_MCP:
        raise ImportError(
            "MCP SDK not installed. Install with: pip install mcp"
        )

    server = Server("ctxpack")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        handler = _HANDLERS.get(name)
        if not handler:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        try:
            result = handler(arguments)
        except Exception as e:
            result = json.dumps({"error": f"{type(e).__name__}: {str(e)}"})

        return [TextContent(type="text", text=result)]

    return server


async def run_stdio() -> None:
    """Run the MCP server on stdio transport."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Entry point for the MCP server."""
    import asyncio

    if not HAS_MCP:
        print("Error: MCP SDK not installed. Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
