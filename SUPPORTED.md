# Supported surface (v1.0)

This file is the compatibility contract for ctxpack. Anything not listed
here is internal: it can change or disappear without a deprecation cycle.

The package version today is `0.5.0rc1` (pre-1.0). The lists below are
the surface 1.0 will keep stable. Classification of every module also
lives in `docs/capability-registry.md`, which CI checks.

`ctxpack.benchmarks` is internal research and evidence infrastructure.
It is not part of the stable v1.0 library API. Do not import it from
outside this repository. Eval results under `ctxpack/benchmarks/**/results/`
are immutable artifacts, not a public API.

## CLI

The console script is `ctxpack` (`ctxpack.cli.main:main`).

### Supported

Ledger, checkpoint, brief, hook, verify, and onboard:

| Command | Role |
|---|---|
| `ctxpack checkpoint` | Pack a transcript into the `.claude/ctx/` ledger |
| `ctxpack hook` | Hook entry points: `pre-compact`, `session-start`, `session-end`, `stop` |
| `ctxpack install-hooks` | Wire those hooks into `.claude/settings.json` |
| `ctxpack backfill` | Pack transcripts the hooks missed. Does not touch `latest-gist` |
| `ctxpack session resume` | Supported one-call brief: gist, decisions, constraints, failed approaches, literals |
| `ctxpack session recall` | Section index or hydrated prose |
| `ctxpack session why` | Provenance for a key. Default searches every session |
| `ctxpack session literals` | Every verbatim identifier in the ledger |
| `ctxpack session decisions` | Decisions, constraints, failed approaches |
| `ctxpack session timeline` | Facts in turn order |
| `ctxpack session graph` | Entity graph (`neighbors`, `parents`, `bfs`, `path`) |
| `ctxpack session stats` | Ledger telemetry for one repo |
| `ctxpack session ratify` | Local intent marker only. Not owner approval |
| `ctxpack onboard` | Hooks, MCP server, CLAUDE.md block, ledger directory |
| `ctxpack onboard --check` | Verify the wired runtime. Exit 1 on mismatch |
| `ctxpack identity` | Version and package root the verify probe prints |
| `ctxpack lessons` | Curated cross-repo lessons |
| `ctxpack lessons --check` | Validate the lessons registry |
| `ctxpack scorecard` | Cohort telemetry rollup |
| `ctxpack scorecard --check` | Verify `scorecard-latest.json` against its inputs |
| `ctxpack retention` | Plan or apply deletion of old per-session artifacts |

There is no separate `ctxpack brief` subcommand in this revision. The
supported brief is `ctxpack session resume`.

Domain packer (zero runtime dependencies):

| Command | Role |
|---|---|
| `ctxpack pack` | Pack a corpus directory into `.ctx` |
| `ctxpack parse` | Parse a `.ctx` file |
| `ctxpack validate` | Validate a `.ctx` file |
| `ctxpack fmt` | Format a `.ctx` file |
| `ctxpack hydrate` | Hydrate sections from a `.ctx` file |
| `ctxpack diff` | AST-level comparison of two `.ctx` files |

### Experimental or legacy

These run, and they are not part of the v1.0 contract. The capability
registry marks the modules they drive as experimental, eval, or
legacy-deprecation-candidate.

| Command | Status |
|---|---|
| `ctxpack codebase` | Experimental codebase map and harness |
| `ctxpack dream` | Experimental consolidation prototype |
| `ctxpack elicit` | Experimental expert-elicitation capture |
| `ctxpack eval` | Eval harness |
| `ctxpack bench` | Eval latency benchmark |
| `ctxpack scaling` | Eval scaling experiment |
| `ctxpack telemetry` | Hydration-log summary for the packer, not the session ledger |

`ctxpack.agent.session` (the rolling merge-and-evict prototype) is a
legacy deprecation candidate. It is not the session-memory product.
The product read path is `ctxpack session` / `ctxpack.agent.session_reader`.

## Python API

Supported entry points:

| Import | Role |
|---|---|
| `ctxpack.__version__` | Running package version. Must match `pyproject.toml` |
| `ctxpack.cli.main.main` | CLI entry point |
| `ctxpack.core.parser.parse` | `.ctx` parser |
| `ctxpack.core.serializer.serialize` | `.ctx` serializer |
| `ctxpack.core.validator.validate` | `.ctx` validator |
| `ctxpack.core.packer.pack` | Corpus packer |
| `ctxpack.core.hydration_protocol.build_system_prompt` | L3 directory-index prompt |
| `ctxpack.core.hydration_protocol.build_hydration_tool_schema` | `ctx/hydrate` tool schema |
| `ctxpack.agent.checkpoint.run_checkpoint` | Ledger write |
| `ctxpack.agent.checkpoint.read_startup_context` | Text the session-start hook injects |
| `ctxpack.agent.session_reader.session_resume` | One-call brief |
| `ctxpack.agent.session_reader.session_recall` | Recall |
| `ctxpack.agent.session_reader.session_why` | Single-session why |
| `ctxpack.agent.session_reader.session_why_across` | Cross-session why (the CLI default) |
| `ctxpack.agent.session_reader.session_literals` | Literals |
| `ctxpack.agent.session_reader.session_decisions` | Stakes trio |
| `ctxpack.agent.session_reader.session_timeline` | Timeline |
| `ctxpack.agent.session_reader.session_stats` | Stats |

Names that start with `_` are private, including when a test imports
them. `ctxpack.modules`, `ctxpack.benchmarks`, `ctxpack.agent.state_parser`,
and `ctxpack.agent.session` are not supported API.

The optional `[code]` extra (tree-sitter, tiktoken) is a supported
install extra. Its Python modules under `ctxpack.core.code` are
internal to the code-packer tools; call them through the CLI/MCP
surface or treat them as unstable.

## MCP tools

The server is `python -m ctxpack.integrations.mcp_server`. It needs the
`mcp` extra (`mcp>=1.0,<3`).

The default agent-facing operation set is five tools:

- `ctx/resume`
- `ctx/session_recall`
- `ctx/why`
- `ctx/session_literals`
- `ctx/checkpoint`

Also supported, not part of that default set:

- Session: `ctx/session_timeline`, `ctx/session_decisions`, `ctx/graph_query`
- Document packer: `ctx/pack`, `ctx/parse`, `ctx/validate`, `ctx/format`, `ctx/hydrate`
- Code packer (requires the `[code]` extra): `ctx/code_pack`, `ctx/code_version`, `ctx/code_list_symbols`, `ctx/code_hydrate_symbol`, `ctx/code_search_symbols`, `ctx/code_raw_file`, `ctx/code_telemetry`

The full tool list is whatever `ctxpack.integrations.mcp_server.TOOLS`
registers. Do not copy a tool count into a status doc; the release
manifest gate rejects a hard-coded full-surface count.

## Semver and ledger format

Ledger schema ids are the compatibility boundary. The package version
does not move them.

Schemas this release reads and writes:

| Id | What |
|---|---|
| `ctx-events/v1` | Fact events (`events.jsonl`). `ctxpack.core.factid.EVENTS_SCHEMA` |
| `ctx-injections/v2` | Session-start injection receipts. v1 rows are still read |
| `ctx-ratifications/v1` | Local ratify/reject journal |
| `ctx-retention/v1` | Retention-apply receipts |
| `ctx-states/v1` | State rows |
| `.ctx` header `1.0` | Document format (`§CTX v1.0`) |

These stamps are provenance, not the ledger format. They can move
without a schema bump:

- Extractor `tp/1.4` (`ctxpack.core.factid.EXTRACTOR_VERSION`). Fact
  text may change. Fact identity does not: the same scope, kind, key,
  and normalized value keep the same `fact_id`. The extractor version
  is not part of the id.
- Redaction `redact/v2`.
- Rank policy `rank/v0-static-priors`.

Rules:

- Adding an optional field, or a new schema id that readers of every
  id in the table above still accept, is backward compatible.
- Stopping reading an id in that table, or changing `fact_id` for
  existing content, is a breaking ledger change.
- Before 1.0, a breaking ledger change is a minor version bump and a
  changelog entry that names the schema id. Patch releases do not
  change ledger schemas.
- From 1.0 on, a breaking ledger change is a major version. Minor
  releases only add compatible fields and schema ids. Patch releases
  do not change schemas.
- `ctxpack.benchmarks` and the experimental CLI commands are outside
  this policy.

On a git tag, the tag name must be the package version. `v0.5.0-rc1`
and `0.5.0rc1` are the same version. `scripts/check_version.py` enforces
that in CI, including on `v*` tag pushes.
