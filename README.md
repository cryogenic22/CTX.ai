# CtxPack

CtxPack packs a coding-agent transcript into a ledger you can commit, and packs domain corpora into a `.ctx` file. Package version 1.1.0 (`ctxpack/__init__.py` and `pyproject.toml`). This page states what the code does.

## What CTX claims

Three claims. Each one names the modules that implement it.

### 1. Deterministic, auditable memory

No model call sits on the write path.

`ctxpack/agent/transcript_parser.py` reads the transcript into facts. `ctxpack/agent/checkpoint.py` packs those facts and calls `serialize` in `ctxpack/core/serializer.py` for the ledger text. `ctxpack/agent/ledger.py` chooses the filenames and writes the bytes. `ledger.py` also calls `serialize_section` when it reads a section back. The compressor and the serializer use the standard library only.

The same transcript produces the same ledger bytes when the header date is pinned. Pass `as_of`, or set `CTXPACK_AS_OF`. Without that pin, `ctxpack/core/packer/clock.py` uses today's date, so two packs on different days are not the same bytes. A checkpoint journal row includes a wall-clock timestamp, so that row is not part of the ledger byte identity.

CI job `replay-byte-pin` in `.github/workflows/ci.yml` runs `python -m ctxpack.benchmarks.replay` on `tests/fixtures/replay/synthetic-l1` and requires `out.json` to equal the committed `expected.json` byte for byte. The job runs on Ubuntu, macOS, and Windows.

### 2. Marked decisions are packed and re-injected at session start

`ctxpack/agent/checkpoint.py` packs the transcript from the PreCompact, SessionEnd, and Stop hooks. `ctxpack/agent/live_set.py` drops superseded, retracted, and stale facts from the live set. Stale here means a fact whose milestone scope is listed in `done_milestones`. An empty list drops nothing for staleness. There is no wall-clock expiry on this path. Those facts stay in the ledger. The brief can still name a replacement or a withdrawal under conflicts. It does not restate the old fact as the current decision. `ctxpack/agent/brief.py` composes the brief. The SessionStart handler in `ctxpack/cli/main.py` (`_cmd_hook`, event `session-start`) prints that brief as Claude Code `additionalContext`.

Capture of a decision or a constraint requires an explicit marker. The line must start with `Decision:` or `Constraint:`. A bullet or bold marker may sit in front of the word. A mention inside backticks does not count. Unmarked prose is not the capture contract. The parser also has verb patterns for some decision-shaped sentences. Those patterns are not a guarantee, and this page does not claim they recover unmarked decisions.

The hook records that it wrote bytes to its own stdout. It does not record whether the harness forwarded those bytes, or whether the model read them.

### 3. Advisory PR verify against a contract

`ctxpack verify` is `ctxpack/agent/verify.py`. It compares a commit range, an optional pull-request body, the ledger, and an optional task contract (`ctxpack/agent/contract.py`). `ctxpack/agent/findings_log.py` appends a findings log only when `--record-findings` or `--findings-log` is set. `verify()` itself does not write the ledger.

The check flags path problems and claim problems. Codes include `ONE_WAY_PATH_TOUCHED`, `STALE_IDENTIFIER`, `UNVERIFIED_CLAIM`, `CONTRACT_RULE_VIOLATION`, `SUPERSEDED_STILL_IN_CODE`, and `UNRECORDED_MARKER`. The default blocking list is empty, so the process exits 0 unless a code is named in `--block`, in `ctxpack.toml` under `[verify] block`, or in the contract's `blocking_codes`. `ONE_WAY_PATH_TOUCHED` still blocks when the list omits it, unless the pull-request body has `one-way-ack:` and a `verified-sha:` that prefixes the head commit.

Verify does not run the program. It does not catch logic bugs or runtime bugs.

## Supported harnesses

Transcript adapters live in `ctxpack/agent/transcript_adapters.py`.

- Claude Code session JSONL (`ClaudeCodeAdapter`) is auto-detected.
- Codex rollout JSONL (`CodexAdapter`) is auto-detected.
- Any other JSONL shape is read only by `GenericJSONLAdapter`, and only when the caller passes an explicit field-map spec (`--format-spec`). An unrecognized file raises `TranscriptFormatError`.

Cursor is not supported. There is no Cursor adapter.

`ctxpack onboard` writes Claude Code hooks into `.claude/settings.json` (PreCompact, SessionStart, SessionEnd, Stop). It does not install hooks for Codex or for Cursor. Codex support is the transcript adapter, not a hook install.

## What CTX does not claim yet

- A reduction in tokens, cost, or prompt size compared with native compaction, grep, retrieval, or raw stuffing.
- A speed-up of packing, hooks, or resume.
- Higher decision recall than native compaction, or than grep over the transcript.
- Support for Cursor, or for any harness other than the Claude Code adapter, the Codex adapter, and the explicit generic spec.
- That `ctxpack verify` finds logic bugs or runtime bugs.
- That unmarked decisions in free prose are captured.

Files under `paper/` and result files under `ctxpack/benchmarks/**/results/` are research records. This README does not repeat their numbers. Those numbers are not product claims.

## Quick start

```bash
pip install "git+https://github.com/cryogenic22/CTX.ai"
cd your-repo
ctxpack onboard
```

`onboard` writes Claude Code hooks, an MCP server entry in `.mcp.json`, a conventions block in `CLAUDE.md`, and the ledger directory. Restart Claude Code and approve the hooks and the server. The process reads that config at startup, so a restart is required before anything fires.

```bash
ctxpack session resume
ctxpack session recall "backoff"
ctxpack session why "pool_size"
ctxpack session literals
ctxpack session stats
ctxpack checkpoint
```

The same operations exist as MCP tools. The default agent surface is five tools: `ctx/resume`, `ctx/session_recall`, `ctx/why`, `ctx/session_literals`, and `ctx/checkpoint`. `ctx/brief` is the budgeted briefing the SessionStart hook sends. `ctx/session_timeline`, `ctx/session_decisions`, and `ctx/graph_query` are available when those five are not enough.

State a decision as its own sentence:

```text
Decision: use exponential backoff with base 750ms because the vendor limit is 40 req/min.
```

State an operating rule the same way:

```text
Constraint: eval results are immutable. Write new versioned files.
```

`ctxpack session stats` reads counters the checkpoint computes from the transcript. `raw_fallback_rate` counts how often a recall attempt used the raw transcript. The field is a usage counter. It is not a recall result.

## Knowledge packer

The packer turns YAML, Markdown, JSON, TOML, and CSV into a `.ctx` file:

```bash
ctxpack pack path/to/corpus/ --layers L2,L3
ctxpack hydrate output.ctx --section ENTITY-CUSTOMER
ctxpack hydrate output.ctx --query "retention policy PII"
```

Packing does not call a model or a network. The same input and the same as-of date produce the same bytes. Negations are not stripped or reordered. `tests/test_negation_preservation.py` gates that rule.

The format is specified in [`spec/CTXPACK-SPEC.md`](spec/CTXPACK-SPEC.md) (CC-BY-SA 4.0). The grammar file is [`spec/ctx.peg`](spec/ctx.peg).

## MCP server

```bash
pip install "ctxpack[mcp] @ git+https://github.com/cryogenic22/CTX.ai"
python -m ctxpack.integrations.mcp_server
```

`ctxpack/integrations/mcp_server.py` defines 21 tools. The count is the number of `name="ctx/..."` entries: 5 document tools, 7 in `_CODE_TOOLS`, and 9 in `_SESSION_TOOLS`, concatenated into `TOOLS`.

| Group | Tools |
|---|---|
| Session memory, default surface | `ctx/resume`, `ctx/session_recall`, `ctx/why`, `ctx/session_literals`, `ctx/checkpoint` |
| Brief | `ctx/brief` |
| Session memory, advanced | `ctx/session_timeline`, `ctx/session_decisions`, `ctx/graph_query` |
| Documents | `ctx/pack`, `ctx/parse`, `ctx/validate`, `ctx/format`, `ctx/hydrate` |
| Code packer (`[code]` extra) | `ctx/code_pack`, `ctx/code_version`, `ctx/code_list_symbols`, `ctx/code_hydrate_symbol`, `ctx/code_search_symbols`, `ctx/code_raw_file`, `ctx/code_telemetry` |

## Install

```bash
pip install "git+https://github.com/cryogenic22/CTX.ai"
pip install "ctxpack[mcp] @ git+https://github.com/cryogenic22/CTX.ai"
pip install "ctxpack[all] @ git+https://github.com/cryogenic22/CTX.ai"
```

Python 3.10 or newer. The core dependency list is empty. Hooks, the checkpoint engine, and `ctxpack session` use the standard library. The `mcp` extra pins `mcp>=1.0,<2`. The `code` extra adds tree-sitter and tiktoken. The `all` extra is code, mcp, and analytics. It does not include the `jev` extra.

Team setup notes: [`docs/session-memory-onboarding.md`](docs/session-memory-onboarding.md). The supported command list is [`SUPPORTED.md`](SUPPORTED.md).

## Project structure

```
ctxpack/
  core/              # parser, serializer, validator, packer (no runtime dependencies)
  agent/             # transcript adapters, checkpoint, brief, verify
  integrations/      # MCP server
  cli/               # ctxpack CLI, including the SessionStart hook
  benchmarks/        # eval code and immutable result files, not product claims
spec/
paper/               # research notes, not the product claims on this page
docs/
tests/               # 2,229 tests collected; see Tests
```

Every module is classed core, eval, experimental, or legacy-deprecation-candidate in [`docs/capability-registry.md`](docs/capability-registry.md). A module that is not classed core is not a product claim.

## Tests

```bash
python -m pytest tests/ -q
```

The full suite is slow. Scope pytest to the files you changed before running all of `tests/`.

On tag `v1.1.0` (this tree; `pyproject.toml` version 1.1.0), this command:

```bash
python3 -m pytest tests/ --collect-only -q
```

printed `2229 tests collected`. The run used Python 3.12.3 and pytest 9.2.0. There was no `-m` filter and no `--ignore`, so the count includes tests marked `slow` and tests under `tests/code`. It is a collection count, not a pass count. The collector reported no errors.

`tests/test_negation_preservation.py` gates negation handling. `tests/test_p0_trust_repairs.py` gates byte-determinism. `scripts/check_claims.py` and `tests/test_claims_gate.py` gate public numerical claims.

Eval result files under `ctxpack/benchmarks/**/results/` are immutable. A new run writes a new file.

## Limitations

- Assistant decisions and constraints are captured from `Decision:` and `Constraint:` lines. Do not assume unmarked prose was stored.
- `ctxpack onboard` installs Claude Code hooks. Codex transcripts can be packed with the Codex adapter. Cursor transcripts cannot.
- SessionStart writes the brief to the hook's stdout. This repo does not measure whether that text reached the model.
- `ctxpack verify` is report-only by default, with the one-way-path exception above. It does not execute tests, and it does not catch logic bugs or runtime bugs.
- The ledger directory belongs to one repo. Other machines see it when the directory is committed.
- Claude Code reads hook config when the process starts. After install or upgrade, restart Claude Code.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). `ctxpack/core/` and `ctxpack/agent/` stay on the standard library. Do not strip negations. Do not overwrite eval result files.

## Disclaimer

CtxPack is provided as-is. It is not a substitute for professional judgment in regulated industries. Check output against the source material before production use. See [NOTICE](NOTICE) for trademark attributions.

## License

Apache-2.0. See [LICENSE](LICENSE). The `.ctx` format specification is CC-BY-SA 4.0.
