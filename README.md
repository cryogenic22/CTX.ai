# CtxPack

**Progressive hydration for cost-efficient LLM domain knowledge serving.**

CtxPack is a deterministic knowledge compiler that structures domain files (YAML, Markdown, JSON) into an indexed knowledge base and serves relevant sections per query through progressive hydration — delivering 93% of frontier-model fidelity at 3.8% of the per-query token cost.

```
Your domain knowledge:                     What CtxPack does:
  23 YAML entity definitions                 1. Pack: resolve, dedup, detect conflicts
  11 Markdown runbooks            ------>    2. Index: ultra-lean L3 directory (1.8K tokens)
   5 governance rule files                   3. Serve: hydrate 1-3 sections per query
  92,000 BPE tokens total                      3,500 tokens per query (26x cheaper)
```

## Why

LLM APIs charge per token. Stuffing 92K tokens of domain knowledge into every prompt costs $1.39/query on Claude Opus — $42K/month at 1,000 queries/day.

But the problem isn't just cost. Wang & Sun (ICML 2025) demonstrate that LLM retrieval accuracy **degrades log-linearly** as competing information accumulates in context, regardless of window size. Stuffing 37 entity definitions with overlapping field names creates exactly the interference conditions that degrade retrieval.

CtxPack addresses both: **26x cost reduction** by hydrating only relevant sections, and **interference reduction** by eliminating the competing information that degrades accuracy.

### Key results

Evaluated on a 92K-token enterprise corpus (37 entities, 30 questions), cross-model GPT-4o judge, zero judge failures:

| Method | BPE/Query | Fidelity | Cost/Query |
|--------|:---------:|:--------:|:----------:|
| Raw context stuffing | 92,482 | 87% | $1.39 |
| **CtxPack hydrated** | **3,523** | **80%** | **$0.05** |

Fidelity gap is stable at 7pp across model sizes:

| Model | Raw | Hydrated | Gap |
|-------|:---:|:--------:|:---:|
| Claude Opus 4.6 | 87% | 80% | 7pp |
| Claude Haiku 4.5 | 77% | 70% | 7pp |

Easy/medium questions score identically (92%/92%). The gap comes from multi-hop questions requiring 4+ entity sections.

## Install

```bash
pip install -e .
```

Requires Python 3.10+. Zero runtime dependencies.

## Quick start

### Pack a corpus

```bash
ctxpack pack path/to/corpus/
```

The corpus directory should contain YAML entity files, Markdown docs, and an optional `ctxpack.yaml` config.

### Hydrate sections

```bash
# List available sections
ctxpack hydrate output.ctx --list

# Hydrate a specific section
ctxpack hydrate output.ctx --section ENTITY-CUSTOMER

# Keyword-based hydration
ctxpack hydrate output.ctx --query "retention policy PII"
```

### Parse and validate

```bash
ctxpack parse file.ctx
ctxpack validate file.ctx
ctxpack fmt file.ctx          # Canonical formatting
```

### Compression presets

```bash
ctxpack pack corpus/ --preset conservative   # Keep everything
ctxpack pack corpus/ --preset balanced       # Default
ctxpack pack corpus/ --preset aggressive     # Drop low-salience fields
```

## How it works

### 1. Pack pipeline (encoder)

The packer compiles domain files through six deterministic stages:

1. **Discover** — classify files (YAML/MD/JSON), load config
2. **Parse** — extract entities, fields, relationships from each format
3. **Entity resolution** — normalize names, merge aliases, deduplicate fields across sources
4. **Conflict detection** — flag contradictions: retention mismatches, type conflicts, PII inconsistencies
5. **Salience scoring** — rank entities/fields by cross-reference density, golden-source status, relationship keys
6. **Compress** — build output AST with provenance and certainty annotations

Same input = byte-identical output. No LLM, no ML, no network calls.

### 2. Progressive hydration (decoder)

Rather than injecting the entire knowledge base, CtxPack serves content through a three-step protocol:

**L3 Directory Index** (~1,800 BPE) — lists available sections with identifiers. Goes in the system prompt permanently.

**LLM-as-Router** — the LLM reads the directory, decides which 1-3 sections are relevant to the question. No embeddings, no vector database.

**Section Hydration** (~3,500 BPE avg) — requested sections are injected as focused context. The LLM answers from targeted, low-interference content.

### 3. MCP server integration

```bash
python -m ctxpack.integrations
```

Exposes five tools: `ctx/pack`, `ctx/parse`, `ctx/validate`, `ctx/format`, `ctx/hydrate`.

## The .ctx format

Multi-resolution layer system with a formal [PEG grammar](spec/ctx.peg):

| Layer | Purpose | Token budget |
|-------|---------|:------------:|
| L0 | Raw source (lossless) | Full |
| L1 | Compressed prose | ~400 tokens |
| L2 | Semantic graph (entities + KV) | ~140 tokens |
| L3 | Directory index / gist | ~50 tokens |

Specification: [`spec/CTXPACK-SPEC.md`](spec/CTXPACK-SPEC.md)

## Project structure

```
ctxpack/
  core/              # Parser, serializer, validator, packer (zero deps)
    packer/          # Entity extraction, resolution, compression, budget allocation
    hydrator.py      # Section-level hydration (hydrate_by_name, hydrate_by_query)
    hydration_protocol.py  # L3 directory index, LLM-as-router protocol
  integrations/      # MCP server (5 tools)
  cli/               # Command-line interface
  benchmarks/        # Evaluation framework, baselines, metrics
    ctxpack_eval/    # Golden set (20 questions, 8 entities)
    scaling/         # Enterprise corpus (37 entities, 30 questions, 92K BPE)
    metrics/         # BPE-primary compression, fidelity (with retry + cross-model judge)
    results/         # Clean eval results (definitive, scaling, model spread)
spec/                # CTXPACK-SPEC v1.0, PEG grammar
paper/               # Whitepaper v3, LinkedIn posts
tests/               # 565 tests, ~8 seconds, no network calls
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -x -q
```

565 tests including 25 eval pipeline tests and 7 metric sanity guards. All deterministic, no API keys required.

### Metric sanity guards

Seven CI-gated tests specifically prevent measurement errors:

| Guard | What it catches |
|-------|----------------|
| BPE/word ratio ≤ 5.0 | Encoding that games word-count metrics |
| Compression ratio divergence ≤ 3.0x | Word vs BPE ratio inconsistency |
| Header token accuracy | Misleading CTX_TOKENS metadata |
| L3 size < 50% of L2 | Bloated system prompt |
| NL prose readability | Degenerate serialization |
| Judge failure detection | Rate-limit errors scored as failures |
| Retry logic | Transient API errors handled correctly |

## Evaluation

The evaluation framework uses BPE tokens (tiktoken) as the primary metric, cross-model judging (GPT-4o grades other models' answers), exponential backoff retry, and automated red-team checks.

### Running evaluations

```bash
# Enterprise-scale eval (requires API keys in .env)
python run_scaling_eval.py

# Model spread test (Haiku + GPT-4o-mini)
python run_model_spread_eval.py
```

### Red team checks (run automatically)

| Check | Threshold |
|-------|-----------|
| L3 index budget | < 10% of corpus |
| Hydration cost vs raw | ≤ 20% |
| Hydration fidelity floor | ≥ 50% |
| Fidelity gap | ≤ 15pp |
| Rule/Judge divergence | ≤ 30pp |
| Judge failure rate | ≤ 10% |

See the [whitepaper](paper/ctxpack-whitepaper-v3.md) for complete methodology and results.

## Research foundation

CtxPack's architecture is grounded in:

- **Wang & Sun (2025)**, "Unable to Forget: Proactive Interference Reveals Working Memory Limits in LLMs Beyond Context Length" (ICML 2025 Workshop). Demonstrates that LLM retrieval degrades with competing information — validates progressive hydration as interference reduction.

## Limitations

- **7pp fidelity gap on multi-hop questions** — queries needing 4+ entities lose accuracy with 1-3 section retrieval
- **Minimum model requirement** — LLM-as-router needs Haiku-class capability; GPT-4o-mini is too weak
- **File-level BPE compression is ~1.0x** — value comes from per-query hydration, not file compression
- **Synthetic corpus** — evaluated on generated enterprise data; real-world data is messier
- **30-question sample** — directionally reliable but not statistically definitive (±18pp at 95% CI)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, code style, and PR process.

Key policies:
- Zero external dependencies for `ctxpack/core/`
- All 565 tests must pass before merge
- BPE tokens as primary metric for all compression/cost claims
- Type hints on public functions

## Disclaimer

CtxPack is a research tool provided as-is. It is not a substitute for professional judgment in regulated industries. Users are responsible for validating output against source material before production use. See [NOTICE](NOTICE) for trademark attributions.

Benchmark results reference commercial LLM products by name for factual comparison purposes only.

## License

Apache-2.0. See [LICENSE](LICENSE).

The `.ctx` format specification ([`spec/CTXPACK-SPEC.md`](spec/CTXPACK-SPEC.md)) is licensed under CC-BY-SA 4.0.
