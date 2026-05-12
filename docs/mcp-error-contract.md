---
title: Code-packer MCP error contract
status: CP-025.5 — pinned for v0
---

# MCP Error Contract — code-packer tools

Every code-packer MCP tool returns a structured JSON object. Errors
are returned as ``{"error": {"code": ..., "message": ..., "hint": ...}}``
rather than as exceptions, so the agent can see *why* a call failed
and act without retrying blindly.

Error codes are stable strings; the message and hint may evolve.

## Common error codes

| code | When | Agent recovery hint |
|---|---|---|
| `unknown_symbol` | Hydrate / list called on a name that's not in the pack. | Call `ctx/code_list_symbols(module)` for the module, or `ctx/code_search_symbols` to discover the right name. |
| `unknown_module` | Module path not found in the pack root. | List the pack's known modules via the manifest, or check the path with `ctx/code_raw_file`. |
| `ignored_path` | `raw_file` called on a path that's excluded by `.gitignore` / `.ctxpackignore` / heuristics. | The file is intentionally outside the pack. If genuinely needed, edit the ignore file. |
| `path_outside_root` | Path argument escapes the pack root (e.g. `..`). | Use a path relative to the pack root. |
| `pack_not_loaded` | A tool was called before `ctx/code_pack` ran. | Call `ctx/code_pack(root)` first. |
| `budget_exceeded` | `hydrate_symbol(depth=1)` could not fit any neighbours within the 4K BPE budget. | Drop to `depth=0`. |
| `invalid_input` | Bad type / missing required arg / shape mismatch. | Re-read the tool's input schema. |
| `internal_parse_error` | A file in the pack root caused the parser to crash unexpectedly. | The pack continues without that file; check `pack.warnings`. |

## Per-tool failure surface

### `ctx/code_pack(root)`
- `path_outside_root` if `root` is not a directory or contains `..` segments after normalisation.
- `invalid_input` if `root` is missing.
- On partial parse failures: returns success with per-file warnings collected in `pack.warnings`.

### `ctx/code_list_symbols(module, k=50, context=None)`
- `unknown_module` if `module` doesn't match any file in the pack.
- `pack_not_loaded` if no pack is active.
- `invalid_input` if `k` is non-positive.

### `ctx/code_hydrate_symbol(name, depth=0)`
- `unknown_symbol` if the qualified name isn't in the pack.
- `budget_exceeded` if `depth=1` and the symbol's neighbours can't fit.
  Returns the depth-0 body + the warning code so the agent knows.
- `invalid_input` if `depth` not in {0, 1}.

### `ctx/code_search_symbols(query, k=10)`
- Returns an empty list (NOT an error) if no symbols match — empty
  result is a valid answer.
- `invalid_input` if `query` is empty after trim.

### `ctx/code_raw_file(path)`
- `path_outside_root`, `ignored_path` as above.
- `unknown_module` (re-used) if the path simply doesn't exist.
- Returns file bytes as `{"content": "<text>", "bytes": <int>}`.

### `ctx/code_version()`
- Cheap probe; cannot fail except `pack_not_loaded`.

## Stale-pack protocol

Every response includes a `pack_version` field (content-hash of the
pack). The agent compares against its cached value; if mismatched,
it should reset its symbol cache and refetch.
