# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-03-13

### Added
- Cross-ecosystem evaluation: 12 models from 3 ecosystems (Anthropic, OpenAI, Google)
- Real-world corpus validation: FDA drug labels (93x compression), Twilio Video API (8.7x)
- Structured-prompt baseline ("LLM-as-packer") comparison
- BPE token analysis and `bpe_optimized` serialization mode
- Trust layer: certainty tiers, field-level provenance, L3 gist generation
- JSON source parser for entity extraction
- Relationship modeling (has_many, has_one, references, depends_on)
- `ctxpack diff` command for AST-level .ctx comparison
- Streaming serializer (`serialize_iter()`)
- GitHub Actions CI (3 OS x 4 Python versions)
- CONTRIBUTING.md, issue templates, PR template

### Changed
- License changed from AGPL-3.0 to Apache-2.0
- Version bumped from 0.2.0 to 0.3.0

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
