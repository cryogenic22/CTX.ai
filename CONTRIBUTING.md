# Contributing to CtxPack

Thank you for your interest in contributing to CtxPack! This project is open-source under AGPL-3.0 and welcomes contributions from the community.

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

If you don't have a `pyproject.toml` with dev extras yet, install test dependencies manually:

```bash
pip install pytest
```

### Running Tests

```bash
python -m pytest tests/ -x -q
```

All 461+ tests should pass. Tests run in ~2 seconds with no network calls.

### Running Benchmarks

Benchmarks require API keys (Anthropic, OpenAI, and/or Google) in a `.env` file:

```bash
cp .env.example .env
# Edit .env with your API keys
python -m ctxpack eval          # Golden-set evaluation
python -m ctxpack pack <dir>    # Pack a corpus
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
5. **Run the test suite** — `python -m pytest tests/ -x -q` must pass
6. **Commit** with a clear message describing what and why
7. **Open a Pull Request** against `main`

### Code Style

- Pure Python, zero external dependencies for `ctxpack/core/`
- Type hints on all public functions
- Docstrings on modules and public functions
- No unnecessary abstractions — three similar lines > a premature helper
- Tests go in `tests/` and follow `test_<module>.py` naming

### Areas Where Help is Wanted

- **New source parsers** — adding support for TOML, CSV, or other structured formats in the packer
- **Sector-specific templates** — pack configs for healthcare, fintech, legal, etc.
- **MCP server integration** — query-adaptive context hydration
- **Additional evaluations** — new domains, languages, or models
- **Documentation** — improving README, adding tutorials, API docs

## Project Structure

```
ctxpack/
  core/           # Parser, serializer, validator, packer (zero deps)
    packer/       # Entity extraction, resolution, compression pipeline
  cli/            # Command-line interface
  benchmarks/     # Evaluation framework, baselines, metrics
    golden_set/   # Fixed evaluation corpus + questions
    baselines/    # raw stuffing, minified, LLM summary, structured prompt
    metrics/      # fidelity, compression, cost
    scaling/      # Cross-scale experiments
    realworld/    # FDA, Twilio corpus downloaders
  agent/          # Agent context compression (experimental)
spec/             # CTXPACK-SPEC v1.0, PEG grammar
paper/            # Whitepaper source + figure generation
tests/            # Test suite (461+ tests)
```

## License

By contributing, you agree that your contributions will be licensed under AGPL-3.0-or-later, consistent with the project license.
