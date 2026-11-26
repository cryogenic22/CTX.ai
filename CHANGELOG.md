# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.1.0] - 2026-11-26

### Changed
- The mypy ratchet on product code (`ctxpack/`, benchmarks excluded) is now **0**. CI keeps that count at zero with mypy 2.4.1. The product-code coverage floor in CI is **85%** (measured 88.60% on the non-slow suite). (#39)
- Package version is `1.1.0`.

### Fixed
- Backfill no longer treats an 8-character session-id prefix as the live session when two transcripts share it. Matching uses the full id, with the unique legacy-prefix fallback. (#39)
- Read commands `brief`, `session`, and `verify` name an explicit ledger directory that does not exist, instead of treating that path as an empty ledger. Write commands still create their directories. (#39)
- A markdown blockquote (`> Decision:` / `> Constraint:`) is quoted text and is not banked as a live marker. (#39)
- `ctxpack lessons suggest` contract patches validate under `TaskContract.from_mapping`. Bare filenames such as `README.md` and `drop.sql` are path globs. Alias codes that are not contract blocking codes map to `CONTRACT_RULE_VIOLATION`. (#39)

### Added
- `ctxpack verify --record-findings` / `--findings-log` appends one JSONL row per finding to `.ctx/findings.jsonl` (or the path given). Omitting both flags writes nothing. `ctxpack lessons suggest` groups that log by a stable `(code, pattern)` key and prints copy-pasteable task-contract proposals for groups at or above `--min-count` (default 3). It reports `count` and `distinct_heads`, and it does not edit the contract. (#38)
- `ctxpack verify` task contracts accept `require_verifier_evidence`, `verifier_command`, and `one_way_paths`. A verifier attestation must be a same-line `verifier: <command> | pass | <head-sha>` (or the documented equivalents) whose SHA is a 7+ hex prefix of head; a missing, short, or mismatched SHA emits `VERIFIER_EVIDENCE_MISSING` (severity error). `verifier_command` matches whole shell tokens, so `verify` does not match `notverify` or `my-verify-fake`. A merge-base diff that touches `one_way_paths` emits `ONE_WAY_PATH_TOUCHED` (severity error) and blocks even in report-only mode unless the PR body has a same-line non-placeholder `one-way-ack:` and a matching `verified-sha:`. `ctxpack onboard` appends an idempotent attestation block to `.github/pull_request_template.md`. (#37)

## [1.0.0] - 2026-11-26

### Added
- Offline deterministic replay benchmark (`python -m ctxpack.benchmarks.replay`) with synthetic fixture + pinned baseline report for CTX Legions L1 acceptance testing.
- `ctxpack brief` / `ctxpack.brief()` / MCP `ctx/brief`: one budgeted briefing shared with the SessionStart hook. Default cap is 12000 characters. Priority is conflicts, open constraints, decisions, dead ends, plan progress, then file names (overridable in `ctxpack.toml` `[brief]`). Facts are kept whole; a budget drop is named per kind on the last line. `ctxpack brief --ack` and `ctxpack ack check --token T` record whether the delivery token was echoed. (#30)
- `ctxpack verify` ledger-to-PR gate (issue #16): deterministic findings for unrecorded markers, stale identifiers, superseded identifiers still in the diff, and constraint conflicts, plus a per-task contract (`ctxpack/agent/contract.py`) and an optional advisory `ctxpack[jev]` extra that does not change verify's exit code. See `docs/verify-ci.md`. (#33)

### Fixed
- Gist and brief budgets use one offline counter (`chars`, or `max(1, (len + 3) // 4)` tokens after newline normalization). They no longer call tiktoken or switch counters when that extra is missing. `count_bpe_tokens` fails instead of silently estimating when a caller asks for the optional tokenizer. (#30)
- Ledger capture ignores harness briefings and probe exchanges, banks sentence-start `Rejected:` / `Dead end:` lines as `FAILED-APPROACH` (`marker_stated`), and strips leading markdown bullets from banked marker lines without changing unbulleted fact ids (extractor `tp/1.5`). (#29)
- One live set feeds the project gist, the session gist, and the brief: superseded, retracted, and milestone-stale facts drop; replacements render under `Changed choices`; unresolved forks render as conflicts. `Supersedes:` accepts exact 16-hex and 64-hex ids and flags an ambiguous mixed-ledger match instead of guessing. (#29)
- Hook and MCP launches use `sys.executable` (`-P` only on Python 3.11+). Ledger, gist, and events rewrites are atomic. A sanitized or over-long session id gets a hash suffix so distinct ids cannot share a filename. A corrupt session ledger is reported and skipped. When the brief budget can hold them, up to two live dead ends are considered before decisions. SessionStart redacts, then shrinks the brief to the budget. Shared path and write helpers live in `ctxpack/agent/ledger.py`. (#34)
- `ctxpack verify` emits `UNVERIFIED_CLAIM` when required test evidence is an explicit not-run admission, and diffs `--range` from the merge-base so files added only on the base after the branch point are not blamed on the PR. (#35)

### Changed
- CI locks the current quality floor: ruff pyflakes on `ctxpack/` (benchmarks excluded) at zero, a mypy error-count ratchet, import-linter contracts (`ctxpack.core` does not import agent/cli/modules/mcp/benchmarks; layers descend cli → agent → core), `tests/code` on every OS/Python cell, and a product-code line-coverage floor. `pyproject.toml` version must match `ctxpack.__version__`, and a tag must name that version. The `mcp` extra is capped below 2 (mcp 2.x removes `Server.list_tools` and renames `Tool.inputSchema`). The telemetry JSON schema is included in the wheel. The supported v1.0 surface is declared in `SUPPORTED.md`. (#31)
- `export_claude_md` keeps hand-written CLAUDE.md text and refreshes one generated codebase-map block. `build_hydration_tool_schema` is defined once. `_annotate_authority` is annotated with the journal dict it returns. (#31)
- Package version is `1.0.0`. The project classifier is `Development Status :: 5 - Production/Stable`.

## [0.5.0] - 2026-03-16

### Added
- **Opt-in modules** (`ctxpack/modules/`): grounding, keywords, guard, catalog_queries, analytics
- Grounding wrapper: sandwich prompt with auto-generated few-shot examples and entity count reminder
- Keyword index: word-boundary matching (`\bmarket\b`), one-to-many resolution, auto-generated from entity names
- Context guard: post-response hallucination detection with warn/retry/new_session recommendations
- Catalog-wide query detection: "how many?" / "list all" intent classifier with grouped summary builder
- Analytics domain pack compiler: parses YAML domain packs into unified IR with cross-domain deduplication
- TOML parser (stdlib `tomllib` with 3.10 fallback) and CSV parser (entity-per-row + entity-per-file layouts)
- Hydration telemetry: append-only JSONL logging with CLI dashboard (`ctxpack telemetry`)
- Entity relationship graph: BFS traversal, shortest path, multi-hop discovery
- Multi-hop re-hydration: low-confidence detection triggers second retrieval pass
- RAG baseline comparison in eval framework
- Prose serializer V2: dense notation converted to readable Markdown
- Integration guides for pharma team and analytics teams

### Changed
- **ctx/hydrate defaults to Markdown prose** (not .ctx notation) — LLMs cannot reliably consume .ctx format
- `--raw` flag for machine-use .ctx notation output
- 770 tests (up from 461 in v0.3.0)

### Fixed
- Production hallucination: .ctx notation caused Claude to ignore context and generate from training data
- Word-boundary matching: "market" no longer matches "marketing"
- One-to-many keywords: "patient services" now matches both value streams

## [0.4.0] - 2026-03-14

### Added
- Progressive hydration architecture: L3 directory index + LLM-as-router + section-level injection
- `ctxpack hydrate` CLI command (--section, --query, --list)
- Variable bitrate compression presets (conservative, balanced, aggressive)
- Must-preserve contracts: boolean/identifier/enum fields never dropped
- MCP server with 5 tools (ctx/pack, ctx/parse, ctx/validate, ctx/format, ctx/hydrate)
- Enterprise-scale evaluation corpus (37 entities, 11 runbooks, 5 rule files, 30 questions, 92K BPE)
- Cross-model judging (GPT-4o grades other models' answers)
- Retry logic with exponential backoff for API calls (handles 429, 500, 502, 503, 504)
- Judge error detection (judge_error flag, judge_failures counter)
- 7 CI-gated metric sanity tests (BPE/word ratio, compression divergence, L3 budget, etc.)
- Model spread evaluation (Opus, Haiku, GPT-4o-mini)
- Whitepaper v3 with clean empirical results

### Changed
- **BPE tokens as primary metric** — all reporting uses tiktoken BPE, not word count
- Removed space-to-hyphen encoding in compressor values (was inflating word-count compression)
- L3 system prompt rewritten as ultra-lean directory index (304 BPE, down from 3,888)
- max_tokens increased from 200 to 512 for answer generation
- Evaluation pipeline: inter-call delays, cross-model judging, error detection
- Version bumped from 0.3.0 to 0.4.0

### Removed
- Old evaluation results (ablation, structured_prompt, tokenizer_mapping) — replaced with clean BPE-primary results
- Old whitepaper v2 — replaced with v3 using corrected methodology

### Fixed
- Word-count compression metric was being gamed by hyphenated encoding (8.4x words vs 1.2x BPE)
- Rate-limited judge calls were silently scored as INCORRECT
- L3 system prompt was larger than the L2 document it indexed (103% of L2)

## [0.3.0] - 2026-03-13

### Added
- Cross-ecosystem evaluation: 12 models from 3 ecosystems (Anthropic, OpenAI, Google)
- Trust layer: certainty tiers, field-level provenance, L3 gist generation
- JSON source parser for entity extraction
- Relationship modeling (has_many, has_one, references, depends_on)
- `ctxpack diff` command for AST-level .ctx comparison
- Streaming serializer (`serialize_iter()`)
- GitHub Actions CI (3 OS x 4 Python versions)
- CONTRIBUTING.md, issue templates, PR template

### Changed
- License changed from AGPL-3.0 to Apache-2.0

## [0.2.0] - 2026-02-22

### Added
- Domain knowledge packer pipeline (YAML, Markdown sources)
- Evaluation framework with golden set (25 questions, dual grading)
- Baselines: raw stuffing, naive truncation, LLM summary
- Scaling corpus generator (690 to 37K tokens)
- `ctxpack pack` and `ctxpack eval` CLI commands
- Parser hardening (depth markers, inline lists, unclosed brackets)

## [0.1.0] - 2026-02-21

### Added
- Deterministic .ctx parser (recursive descent, zero dependencies)
- Serializer (default, canonical, ASCII modes)
- Validator (E001-E010 errors, W001-W003 warnings)
- Operator extraction (Level 3)
- JSON export
- CLI: `ctxpack parse`, `ctxpack validate`, `ctxpack fmt`
- CTXPACK-SPEC v1.0 with PEG grammar
