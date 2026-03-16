# Changelog

All notable changes to this project will be documented in this file.

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
