# Pack + MCP surface (CP-024/025/025.5/026/027/029/030/030.5)

**Status**: in-progress
**Effort**: ~3d compressed (bundling for MCP-ready milestone).

## Acceptance (combined)
- `Pack` object holds entities, edges, scores, and a content-hash version (CP-030.5).
- `pack_codebase(root)` builds a Pack end-to-end deterministically (CP-025).
- `list_symbols(pack, module, k, context)` returns top-k entities for a module by combined score.
- `hydrate_symbol(pack, name, depth)` returns a symbol's full IRField content at depth 0; depth 1 includes neighbour bodies (4K BPE budget).
- `raw_file(pack, path)` returns file bytes (CP-029 escape hatch).
- `render_manifest(pack, served, excluded_reasons)` produces the audit footer (CP-030).
- `pack_version(pack)` returns the content hash for stale-pack detection (CP-030.5).
- MCP error contract documented at `docs/mcp-error-contract.md` (CP-025.5).
- CP-024 invalidation is deferred to v0.1 — incremental packing is not required for the static-snapshot MCP usage.

## Files
- `ctxpack/core/code/pack.py` — Pack class + `pack_codebase` + helpers.
- `docs/mcp-error-contract.md` — error contract.
- Tests in `tests/code/test_pack.py`.

**Ship**: filled at step 9.
