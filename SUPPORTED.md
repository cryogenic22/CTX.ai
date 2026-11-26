# Supported surface (v1.0)

This file is the compatibility contract for CtxPack 1.0. Anything not
listed here is internal: it can change or disappear in a minor release
without a deprecation cycle. The machine-checked classification of every
module is [`docs/capability-registry.md`](docs/capability-registry.md).
This document says which of those modules callers may depend on.

The package version is [`ctxpack.__version__`](ctxpack/__init__.py), and
it is the same string as `[project].version` in `pyproject.toml`
(`scripts/check_version.py` fails the build when they diverge, and when
a git tag does not name that version).

## Semver and the ledger format

Package versions follow semver. Before 1.0, a minor bump may add
supported surface. It does not stop an existing ledger from loading.

Two version stamps travel with the data, and they are not the package
version:

| Stamp | Current value | What a bump means |
|---|---|---|
| Ledger event schema `EVENTS_SCHEMA` | `ctx-events/v1` | The on-disk event row (`events.jsonl` and the checkpoint journal). Readers of `ctx-events/v1` keep working across package releases that still declare that schema. A move to `ctx-events/v2` is a ledger break: it ships as a package major, with an explicit migration, and this file changes in the same release. |
| Extractor `EXTRACTOR_VERSION` | `tp/1.5` | Provenance stamped on each fact. A bump means newly stored fact text may differ. Fact ids stay content-addressed. Unbulleted sentences keep their ids across a tp bump; bulleted sentences hash the stripped sentence (see `ctxpack/core/factid.py`). A tp bump is named in `CHANGELOG.md`. It is not, by itself, a package major. |
| `.ctx` header | `§CTX v1.0` | The packer grammar (`spec/CTXPACK-SPEC.md`). A breaking grammar change bumps this header version. |
| Rank policy | `rank/v0-static-priors` | Recorded on checkpoint journal rows so later folds can be compared. A new policy is additive; old rows stay readable. |

`ctxpack.benchmarks` is research and eval infrastructure. It is not part
of the stable library API, not covered by this semver promise, and not
imported by `ctxpack.core`. Result files under
`ctxpack/benchmarks/**/results/` are immutable evidence, not a supported
programming interface.

Names that start with `_`, and modules the capability registry marks
`experimental`, `eval`, or `legacy-deprecation-candidate`, are not
supported. Today that includes `ctxpack.modules` (the opt-in prototypes),
`ctxpack.core.confidence`, `ctxpack.agent.session` (legacy rolling
merge), and `ctxpack.agent.state_parser` (eval-tier trace parser behind
`compress_state`).

## Supported CLI

These commands are the session-memory product. Flags not listed here can
change; the command names and the jobs below do not, inside a major
version.

| Command | Job |
|---|---|
| `ctxpack checkpoint` | Pack the live transcript into the ledger (`.claude/ctx` by default). |
| `ctxpack hook pre-compact\|session-start\|session-end\|stop` | Hook entry points `onboard` wires into Claude Code. |
| `ctxpack install-hooks` | Write those hooks into `.claude/settings.json`. |
| `ctxpack onboard` | Hooks, MCP server entry, CLAUDE.md conventions block, ledger directory. Idempotent. |
| `ctxpack identity` | Print the running package version and root. This is what `onboard --check` executes. |
| `ctxpack session resume` | One-call resume: gist, decisions, constraints, literals. |
| `ctxpack session recall` | Index, then hydrate. |
| `ctxpack session why` | Provenance and supersession for one key. Cross-session by default; `--session` scopes to one. |
| `ctxpack session literals` | Every verbatim identifier in the ledger. |
| `ctxpack session decisions` | Decisions, constraints, failed approaches. |
| `ctxpack session timeline` | Ledger events, filterable by `--kinds`. |
| `ctxpack session stats` | Adoption and capture metrics. |
| `ctxpack session graph` | Entity-graph query over the ledger. |
| `ctxpack lessons` | The curated cross-repo lessons registry. |
| `ctxpack backfill` | Pack transcripts the hooks missed. Archive mode: does not touch `latest-gist`. |
| `ctxpack retention` | Plan (default) or apply deletion of old per-session artifacts. `--apply` requires the plan hash. |

### Verify

Verification is read-only and fail-loud. These are supported:

- `ctxpack onboard --check` — hooks and MCP resolve to one ctxpack, and the CLAUDE.md block is current.
- `ctxpack lessons --check` — the lessons registry is internally valid.
- `ctxpack scorecard --check` — `scorecard-latest.json` still matches the inputs it recorded.
- `ctxpack identity` — the probe `onboard --check` runs.

`ctxpack session ratify` records a local intent marker. It is bookkeeping
by an unauthenticated local actor. It is not owner approval, and it is
not a verify command.

### Brief

The supported v1.0 briefing API is `ctxpack.agent.brief`, live on this
tree:

- CLI `ctxpack brief` (`--budget`, `--unit`, `--format`, `--ack`)
- Python `ctxpack.brief(...)`, which calls `ctxpack.agent.brief.brief`
- MCP `ctx/brief`
- CLI `ctxpack ack check --token T` for the delivery acknowledgement

The same ledger and the same arguments produce the same markdown from
the CLI, the Python function, and the MCP tool when ack is off. The
composer is supported product surface.

### Knowledge packer

Still supported, still zero-dependency:

| Command | Job |
|---|---|
| `ctxpack pack` | Pack a corpus to `.ctx`. |
| `ctxpack hydrate` | Hydrate sections by name or query. |
| `ctxpack parse` | Parse a `.ctx` file. |
| `ctxpack validate` | Validate a `.ctx` file. |
| `ctxpack fmt` | Format a `.ctx` file. |
| `ctxpack diff` | AST-level diff of two `.ctx` files. |
| `ctxpack telemetry` | Summarize the hydration log. |

### Experimental and legacy commands

These run real code and are not supported. They can change or disappear
without a deprecation cycle. Several drive modules the registry marks
experimental:

| Command | Why it is not supported |
|---|---|
| `ctxpack codebase` (`analyze`, `export`, `harness`) | Codebase map and harness generator. `export --format claude-md` writes a supplementary map; hand-written CLAUDE.md text passed into `export_claude_md` is preserved in the returned string and is not a supported integration. |
| `ctxpack dream` | Consolidation prototype. |
| `ctxpack elicit` | Expert-elicitation capture. |
| `ctxpack eval` | Eval runner. Research only. |
| `ctxpack bench` | Latency benchmark. Research only. |
| `ctxpack scaling` | Scaling-curve experiment. Research only. |

`ctxpack scorecard` (without `--check`) aggregates cohort telemetry. The
`--check` mode is the supported verify. The HTML/Markdown renderers are
not a stable document format.

## Supported Python API

Import these. Do not import private helpers, `ctxpack.benchmarks`, or
`ctxpack.modules` from product code.

| Entrypoint | Role |
|---|---|
| `ctxpack.__version__` | Package version. Single source, matched to `pyproject.toml`. |
| `ctxpack.brief(...)` | Budgeted briefing (`ctxpack.agent.brief.brief`). Same bytes as the CLI and `ctx/brief` for the same ledger and arguments, with ack off. |
| `ctxpack.core.parser.parse` | Parse `.ctx` text. |
| `ctxpack.core.serializer.serialize` | Serialize a document. `serialize_section` for one section. |
| `ctxpack.core.validator.validate` | Validate a document. |
| `ctxpack.core.packer.pack` | Pack a corpus directory. Returns `PackResult`. |
| `ctxpack.core.hydrator.hydrate_by_name` | Hydrate named sections. |
| `ctxpack.core.hydrator.hydrate_by_query` | Hydrate by query string. |
| `ctxpack.core.hydrator.list_sections` | Section index. |
| `ctxpack.core.entity_graph.EntityGraph` | Parents, BFS, path, `query`. |
| `ctxpack.core.factid.EVENTS_SCHEMA` | Ledger event schema stamp (`ctx-events/v1`). |
| `ctxpack.core.factid.EXTRACTOR_VERSION` | Extractor stamp (`tp/1.5`). |
| `ctxpack.agent.checkpoint.run_checkpoint` | Pack a transcript into the ledger. |
| `ctxpack.agent.checkpoint.read_startup_context` | Text the SessionStart hook injects. |
| `ctxpack.agent.session_reader.session_resume` | One-call resume. |
| `ctxpack.agent.session_reader.session_recall` | Recall. |
| `ctxpack.agent.session_reader.session_why` | Single-session why. |
| `ctxpack.agent.session_reader.session_why_across` | Cross-session why (the CLI default). |
| `ctxpack.agent.session_reader.session_literals` | Verbatim identifiers. |
| `ctxpack.agent.session_reader.session_decisions` | Decisions and constraints. |
| `ctxpack.agent.session_reader.session_timeline` | Timeline. |
| `ctxpack.agent.session_reader.session_stats` | Adoption metrics. |

`ctxpack.agent.compress_state` is an eval-tier trace compressor. It is
not the session-memory product path.

The core and agent trees stay zero-dependency. Optional extras are
`mcp` (pinned `mcp>=1.0,<2`), `code` (tree-sitter and tiktoken), and
`analytics` (PyYAML). The server uses the mcp 1.x `list_tools` /
`inputSchema` API. An mcp 2.x install does not satisfy the extra.

## Supported MCP tools

The server is `python -m ctxpack.integrations.mcp_server` and needs the
`mcp` extra. The default agent-facing surface is five tools. The others
are supported but not the default advertisement.

| Group | Tools |
|---|---|
| Default surface | `ctx/resume`, `ctx/session_recall`, `ctx/why`, `ctx/session_literals`, `ctx/checkpoint` |
| Brief | `ctx/brief` |
| Advanced session | `ctx/session_timeline`, `ctx/session_decisions`, `ctx/graph_query` |
| Documents | `ctx/pack`, `ctx/parse`, `ctx/validate`, `ctx/format`, `ctx/hydrate` |
| Code packer (`[code]` extra) | `ctx/code_pack`, `ctx/code_version`, `ctx/code_list_symbols`, `ctx/code_hydrate_symbol`, `ctx/code_search_symbols`, `ctx/code_raw_file`, `ctx/code_telemetry` |

Session-read tool results pass the egress scan before they leave the
process. A scanner failure returns the stable `egress_scan_failed` code
and does not return unscanned bytes.

Tool description text has a committed character budget enforced by
`tests/test_mcp_tool_budget.py`. Adding a tool to the default surface,
or raising that budget, is a reviewed change to this file and that test.
