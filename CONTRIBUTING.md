# Contributing to CtxPack

Thank you for your interest in contributing to CtxPack! This project is open-source under Apache-2.0 and welcomes contributions from the community.

## Getting Started

### Prerequisites

- Python 3.10+
- No external dependencies for the core library (stdlib only)
- Optional: `tiktoken` for BPE token counting, `python-docx` for paper generation

### Setup

```bash
git clone https://github.com/cryogenic22/CTX.ai.git
cd CTX.ai
pip install -e ".[dev]"
```

If you don't have dev extras configured, install test dependencies manually:

```bash
pip install pytest
```

### Running Tests

```bash
python -m pytest tests/ -x -q
```

All 565 tests should pass. Tests run in ~8 seconds with no network calls.

### Running Evaluations

Evaluations require API keys (Anthropic, OpenAI) in a `.env` file:

```bash
cp .env.example .env
# Edit .env with your API keys

# Enterprise-scale eval (Claude Opus, ~$44)
python run_scaling_eval.py

# Model spread test (Haiku + GPT-4o-mini, ~$5)
python run_model_spread_eval.py
```

## How to Contribute

### Reporting Bugs

- Use the [Bug Report](https://github.com/cryogenic22/CTX.ai/issues/new?template=bug_report.md) issue template
- Include the output of `python -m ctxpack --version` and your Python version
- Provide a minimal reproducing example if possible

### Suggesting Features

- Use the [Feature Request](https://github.com/cryogenic22/CTX.ai/issues/new?template=feature_request.md) issue template
- Describe the use case, not just the solution

### Submitting Code

1. **Fork** the repository
2. **Create a branch** from `main` (`git checkout -b feature/my-feature`)
3. **Make your changes** — follow the existing code style
4. **Add tests** — new features need tests, bug fixes need regression tests
5. **Run the test suite** — all 565 tests must pass
6. **Run metric sanity checks** — `python -m pytest tests/test_metric_sanity.py -v`
7. **Commit** with a clear message describing what and why
8. **Open a Pull Request** against `main`

### Code Style

- Pure Python, zero external dependencies for `ctxpack/core/`
- Type hints on all public functions
- Docstrings on modules and public functions
- No unnecessary abstractions — three similar lines > a premature helper
- Tests go in `tests/` and follow `test_<module>.py` naming
- **BPE tokens as primary metric** — never use word count for compression/cost claims

### Measurement Integrity

CtxPack takes measurement seriously. If you're adding evaluation code:

- Use `count_bpe_tokens()` from `metrics.cost`, not `len(text.split())`
- All API calls must use `_retry_api_call()` for transient error resilience
- Cross-model judging preferred (GPT-4o judges other models' answers)
- Track and report `judge_failures` — silent failures corrupt results
- New metrics should have a corresponding sanity test in `test_metric_sanity.py`

### Areas Where Help is Wanted

- **Multi-hop hydration** — re-hydration loops for questions spanning 4+ entities
- **Real-world corpus testing** — evaluate on actual enterprise documentation (Confluence exports, internal wikis)
- **New source parsers** — TOML, CSV, or other structured formats
- **Sector-specific templates** — pack configs for healthcare, fintech, legal
- **Proactive interference experiments** — PI-LLM-style benchmarks on CtxPack output (Wang & Sun, 2025)
- **RAG baseline comparison** — embedding-based retrieval as a competitor baseline
- **Prose serializer improvement** — convert dense inline values to readable natural language

## Project Structure

```
ctxpack/
  core/              # Parser, serializer, validator, packer (zero deps)
    packer/          # Entity extraction, resolution, compression, budget
    hydrator.py      # Section-level hydration
    hydration_protocol.py  # L3 directory index, LLM-as-router protocol
  integrations/      # MCP server (5 tools)
  cli/               # Command-line interface
  benchmarks/        # Evaluation framework
    ctxpack_eval/    # Golden set (20 questions, 8 entities)
    scaling/         # Enterprise corpus (37 entities, 30 questions, 92K BPE)
    metrics/         # BPE-primary compression, fidelity (retry + cross-model judge)
    results/         # Clean eval results
spec/                # CTXPACK-SPEC v1.0, PEG grammar
paper/               # Whitepaper v3, LinkedIn posts
tests/               # 565 tests (core + pipeline + sanity guards)
```

## License

By contributing, you agree that your contributions will be licensed under Apache-2.0, consistent with the project license.
