# CtxPack

**MP3 analogy for LLM context** -- a deterministic compression codec for domain knowledge.

CtxPack takes structured corpora (YAML, Markdown, JSON) and compresses them into `.ctx`, a multi-resolution text format designed for how transformers consume information -- not how humans write it.

```
# 36 lines of YAML...                    # ...become 8 lines of .ctx
entity: CUSTOMER                    -->   ±ENTITY-CUSTOMER ★GOLDEN-SOURCE:CRM-(Salesforce)
description: Core customer entity         IDENTIFIER:customer_id(UUID,immutable)
golden_source: "CRM (Salesforce)"         MATCH-RULES:[email:exact-match(case-insensitive),
identifier:                                 phone:normalise(E.164),
  name: customer_id                         name+address:fuzzy-match(Jaro-Winkler>0.92)]
  type: UUID                              PII:name+email+phone+address
  immutable: true                         PII-CLASSIFICATION:RESTRICTED
match_rules:                              RETENTION:active->indefinite|churned->36->anonymise
  - field: email
    method: exact match
    ...
```

## Why

LLM APIs charge per token. Most injected context -- domain rules, entity definitions, operational knowledge -- is full of structural redundancy that models don't need. CtxPack removes it.

**Key results** (from [the whitepaper](paper/ctxpack-whitepaper-v2.md)):

| Method | Compression | Fidelity (rule-based) |
|--------|:-----------:|:---------------------:|
| Raw context stuffing | 1x | 98% |
| LLM summary | 7.3x | 80% |
| **CtxPack L2** | **5.6x** | **98%** |

Tested across 12 models from 3 ecosystems (Anthropic, OpenAI, Google). At 37K source tokens, CtxPack outperforms raw stuffing on 4 of 5 models -- with up to a 60 percentage point advantage on smaller models where the lost-in-the-middle effect makes raw context unusable.

## Install

```bash
pip install -e .
```

Requires Python 3.10+. Zero runtime dependencies.

## Quick start

**Pack a corpus:**

```bash
ctxpack pack path/to/corpus/
```

The corpus directory should contain YAML entity files, Markdown docs, and an optional `ctxpack.yaml` config. See `ctxpack/benchmarks/golden_set/corpus/` for an example.

**Parse and validate a .ctx file:**

```bash
ctxpack parse file.ctx
ctxpack validate file.ctx
```

**Format (canonical output):**

```bash
ctxpack fmt file.ctx
```

**Run the evaluation benchmark** (requires API keys in `.env`):

```bash
ctxpack eval
```

## How it works

CtxPack's packer pipeline:

1. **Discover** -- scan corpus, classify files (YAML/MD/JSON)
2. **Parse** -- extract entities, fields, and rules using stdlib-only parsers
3. **Entity resolution** -- merge aliases, deduplicate fields across sources
4. **Conflict detection** -- surface contradictions (retention policies, null rules, PII classifications)
5. **Salience scoring** -- rank entities and fields by structural importance
6. **Compress** -- emit `.ctx` notation with operators for relationships, flow, salience

The output is deterministic: same input always produces the same `.ctx` file. No LLM, no ML, no network calls.

## The .ctx format

`.ctx` uses a multi-resolution layer system:

| Layer | Analogy | Token budget | Content |
|-------|---------|:------------:|---------|
| L0 | Lossless | Full | Raw source text |
| L1 | 320 kbps | ~400 tokens | Compressed prose |
| L2 | 128 kbps | ~140 tokens | Semantic graph (entities + KV pairs) |
| L3 | 64 kbps | ~50 tokens | Abstract gist |

The formal specification is at [`spec/CTXPACK-SPEC.md`](spec/CTXPACK-SPEC.md) with a standalone [PEG grammar](spec/ctx.peg).

## Project structure

```
ctxpack/
  core/           # Parser, serializer, validator, packer (zero deps)
    packer/       # Entity extraction, resolution, compression pipeline
  cli/            # Command-line interface
  benchmarks/     # Evaluation framework, baselines, metrics
    golden_set/   # Fixed evaluation corpus + 25 Q&A pairs
    baselines/    # Raw stuffing, minified, LLM summary, structured prompt
    scaling/      # Cross-scale experiments (690 to 37K tokens)
    realworld/    # FDA drug labels, Twilio Video API
  agent/          # Agent context compression (experimental)
spec/             # CTXPACK-SPEC v1.0, PEG grammar
paper/            # Whitepaper, figures, generation scripts
tests/            # 461 tests, ~2 seconds, no network calls
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -x -q
```

All 461 tests are deterministic, require no API keys, and run in ~2 seconds.

## Benchmarks

The evaluation framework includes:

- **Golden set**: 10 source files, 4 entities, 25 questions (including 5 adversarial)
- **Cross-ecosystem**: 12 models from Anthropic, OpenAI, Google
- **Scaling curve**: 690 to 37K source tokens across 5 models
- **Real-world corpora**: FDA drug labels (93x compression), Twilio Video API (8.7x)
- **5 baselines**: raw stuffing, naive truncation, LLM summary, minified JSON, structured prompt
- **Full reproducibility**: every API call logged with timestamps in `results/logs/`

See the [whitepaper](paper/ctxpack-whitepaper-v2.md) for complete results and methodology.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, code style, and PR process.

Key policies:
- Zero external dependencies for `ctxpack/core/`
- All tests must pass before merge
- Type hints on public functions

## Disclaimer

CtxPack is a research tool provided as-is. It is not a substitute for professional judgment in regulated industries. Users are responsible for validating compressed output against their source material before use in production systems. The authors make no warranties regarding the accuracy, completeness, or fitness of compressed output for any particular purpose. See the [NOTICE](NOTICE) file for trademark attributions.

Benchmark results reference commercial LLM products by name for factual comparison purposes only. These references do not imply endorsement by or affiliation with Anthropic, OpenAI, or Google.

## License

Apache-2.0. See [LICENSE](LICENSE).

The `.ctx` format specification ([`spec/CTXPACK-SPEC.md`](spec/CTXPACK-SPEC.md)) is licensed under CC-BY-SA 4.0.
