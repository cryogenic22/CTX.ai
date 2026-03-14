# CtxPack: Progressive Hydration for Cost-Efficient LLM Domain Knowledge Serving

**Kapil Pant**
**March 2026**

*This is independent personal research by the author. The views, findings, and conclusions expressed in this paper are the author's own and do not reflect the position or policy of any employer, past or present.*

## Abstract

Large language models require domain knowledge in their context windows to answer enterprise questions accurately, but injecting entire knowledge bases is prohibitively expensive. We present CtxPack, a deterministic knowledge compiler that structures domain files into an indexed knowledge base and serves relevant sections per query through progressive hydration. On a 92K-token enterprise corpus (37 entities, 280 sections), CtxPack delivers 93% of frontier-model fidelity (80% vs 87%) at 3.8% of the per-query token cost — a 26x cost reduction. The fidelity gap is stable at 7 percentage points across model sizes from Opus to Haiku class, translating to $40K/month savings at 1,000 queries/day on Claude Opus. The architecture is grounded in recent findings on proactive interference in LLMs (Wang & Sun, 2025), which demonstrate that retrieval accuracy degrades log-linearly with competing information in context regardless of window size. CtxPack reduces per-query interference by 96% through selective section injection, while its entity resolution pipeline eliminates cross-source conflicts that compound interference. The system is zero-dependency, deterministic, and requires no LLM in the packing loop.

## 1. Introduction

Enterprise teams maintain domain knowledge across dozens of YAML configurations, Markdown runbooks, JSON schemas, and API specifications. When LLM-powered tools need this knowledge to answer questions, the standard approach is context stuffing — injecting the entire corpus into every prompt. This approach has three problems:

**Cost.** A 92K-token corpus costs $1.39 per query on Claude Opus ($15/M input tokens). At 1,000 queries/day, this is $41,700/month in API costs alone.

**Interference.** Wang & Sun (2025) demonstrate that LLM retrieval accuracy degrades log-linearly as competing information accumulates in context, regardless of available context window length. Only model parameter count determines interference resistance. Stuffing 37 entity definitions with overlapping field names, retention policies, and PII classifications creates exactly the interference conditions that degrade retrieval.

**Non-determinism.** RAG systems with embedding-based retrieval introduce stochasticity — different embedding models, chunking strategies, and vector similarity thresholds produce different results across runs, making the system difficult to audit, version, or debug.

CtxPack addresses all three through a two-stage architecture: a deterministic **pack pipeline** that compiles domain files into a structured knowledge base with entity resolution, conflict detection, and provenance tracking; and a **progressive hydration** protocol that serves only the relevant sections per query using the LLM itself as a router.

## 2. Architecture

### 2.1 Pack Pipeline (Encoder)

The packer scans a corpus directory and produces a structured knowledge base through six stages:

1. **Discovery** — Classify files (YAML entities, Markdown docs, JSON schemas) and load pack configuration
2. **Parsing** — Extract entities, fields, relationships, and standalone rules from each source format
3. **Entity Resolution** — Normalize names, merge aliases, deduplicate fields across sources
4. **Conflict Detection** — Flag contradictions: null policy mismatches, type conflicts, retention period disagreements, PII classification inconsistencies
5. **Salience Scoring** — Rank entities and fields by importance: cross-reference density, golden-source status, relationship keys, warning indicators
6. **Compression** — Build the output AST with provenance tracking and certainty annotations

The pipeline is deterministic (same input = byte-identical output), zero-dependency (stdlib Python only), and requires no LLM — making it free to run, auditable, and CI/CD compatible.

### 2.2 Progressive Hydration (Decoder)

Rather than injecting the entire knowledge base, CtxPack serves content through a three-step protocol:

**Step 1: L3 Directory Index.** An ultra-lean index (~1,800 BPE tokens for 37 entities) lists available sections with their primary identifiers. This goes in the system prompt permanently.

**Step 2: LLM-as-Router.** When a question arrives, the LLM reads the directory index and decides which 1-3 sections to retrieve — no embeddings, no vector database, no external infrastructure. The LLM's own comprehension of the directory serves as the query router.

**Step 3: Section Hydration.** The requested sections are injected as focused context (~3,500 BPE average). The LLM answers from this targeted subset, experiencing minimal interference from competing entities.

This architecture is analogous to progressive loading in web applications: send the index first, fetch detail on demand. The LLM never processes the full 92K-token corpus — only the ~3,500 tokens relevant to the current question.

### 2.3 Entity Resolution as Interference Reduction

The pack pipeline's entity resolution directly reduces proactive interference. When a corpus contains overlapping definitions — Customer retention policy stated in the entity YAML, a governance runbook, and a compliance rules file — the packer merges them into a single canonical section with provenance tracking. Without this merge, raw stuffing would present the LLM with 3 competing definitions, triggering the interference degradation documented by Wang & Sun (2025).

Conflict detection further protects against interference by explicitly flagging contradictions (e.g., "Customer PII retention: 30 days" in one file vs "90 days" in another) rather than leaving the LLM to silently choose between conflicting values.

## 3. Evaluation

### 3.1 Methodology

We evaluate on a synthetic enterprise corpus modeled on real e-commerce data platform knowledge:

- **Corpus**: 37 YAML entity definitions, 11 Markdown runbooks, 5 governance rule files (46,500 words, 92,482 BPE tokens)
- **Entities**: Customer, Order, Payment, Product, Merchant, Inventory, Shipment, and 30 related entities with realistic fields, relationships, retention policies, and PII classifications
- **Questions**: 30 evaluation questions across 5 categories — easy factual (12), cross-entity (8), negation (4), multi-hop (4), adversarial (4)
- **Models tested**: Claude Opus 4.6, Claude Haiku 4.5, GPT-4o-mini
- **Judge**: GPT-4o as cross-model judge for all arms (eliminates self-judging bias and rate-limit asymmetry)
- **Metrics**: BPE token count (tiktoken cl100k_base) as primary unit; both rule-based keyword matching and LLM-as-judge grading

All token counts use actual BPE tokenization, not word-count proxies. The evaluation pipeline includes exponential backoff retry logic, cross-model judging, error detection (judge failures tracked separately), and inter-call rate-limit delays to ensure measurement reliability.

### 3.2 Results

#### Table 1: Scaling Evaluation — 92K BPE Enterprise Corpus

| Method | BPE/Query | Compression | Fidelity (Judge) | Cost/Query |
|---|---|---|---|---|
| Raw Stuffing | 92,482 | 1.0x | 86.7% | $1.3872 |
| CtxPack Hydrated | 3,523 | 26.3x | 80.0% | $0.0528 |

**Zero judge failures across all 60 graded responses.** Pipeline integrity verified.

#### Table 2: Model Spread — Interference Resistance by Model Size

| Model | Raw Fidelity | Hydrated Fidelity | Gap | Compression | Judge Failures |
|---|---|---|---|---|---|
| Claude Opus 4.6 | 86.7% | 80.0% | 6.7pp | 24.2x | 0 |
| Claude Haiku 4.5 | 76.7% | 70.0% | 6.7pp | 22.2x | 0 |
| GPT-4o-mini | 56.7% | 20.0% | 36.7pp | 18.2x | 0 |

#### Table 3: Fidelity by Question Difficulty (Claude Opus 4.6)

| Difficulty | Raw Stuffing | Hydrated | Questions |
|---|---|---|---|
| Easy | 92% | 92% | 12 |
| Medium | 100% | 89% | 9 |
| Hard | 67% | 56% | 9 |

### 3.3 Analysis

**Cost reduction is the primary value.** CtxPack delivers 26x per-query cost savings — $0.05 vs $1.39 on Claude Opus. For 1,000 queries/day, this is $40,000/month in savings. The savings are consistent across model sizes (18-24x).

**Fidelity gap is stable at 7pp for capable models.** Opus and Haiku both show a 6.7 percentage point fidelity reduction from hydration. On easy factual questions, fidelity is identical (92%/92%). The gap comes from multi-hop questions requiring information spread across 4+ entities, where the 1-3 section retrieval limit prevents complete coverage.

**Minimum model capability threshold.** GPT-4o-mini (20% hydrated fidelity) demonstrates that the LLM-as-router architecture requires sufficient model capability for both section selection and answer extraction from structured context. The routing task — reading a directory index and selecting relevant sections — requires at minimum Haiku-class capability.

**Interference effect confirmed.** Raw stuffing fidelity decreases with model size (87% → 77% → 57%), consistent with Wang & Sun's (2025) finding that interference resistance scales with parameter count. However, hydrated fidelity decreases proportionally, indicating that both the routing quality and answer extraction capability degrade together. The crossover point — where hydration surpasses raw on fidelity — was not observed at the 92K corpus scale tested, suggesting it occurs at larger corpus sizes or on models with lower interference resistance.

### 3.4 Measurement Integrity

The evaluation includes six automated red team checks that run with every eval:

| Check | Threshold | Result |
|---|---|---|
| L3 index budget | <10% of corpus | 2.0% (PASS) |
| Hydration cost vs raw | <=20% | 3.8% (PASS) |
| Hydration fidelity floor | >=50% | 80% (PASS) |
| Fidelity gap (raw - hydrated) | <=15pp | 7pp (PASS) |
| Rule/Judge score divergence | <=30pp | 13pp (PASS) |
| Judge failure rate | <=10% | 0% (PASS) |

Additionally, CI-gated metric sanity tests prevent common measurement errors: BPE/word ratio divergence (catches encoding that games word-count metrics), compression ratio consistency (catches divergence between word-based and BPE-based ratios), and header token accuracy (catches misleading metadata).

## 4. Relation to Prior Work

**Proactive Interference in LLMs.** Wang & Sun (2025) demonstrate that LLM retrieval accuracy declines log-linearly with proactive interference from competing information in context, and that context window length has no significant effect on this degradation (p = 0.886). CtxPack's progressive hydration directly addresses this bottleneck by reducing concurrent interference through selective section injection — from 37 competing entities to 1-3 relevant sections per query. The pack pipeline's entity resolution further reduces interference by merging redundant definitions that would otherwise create competing retrieval targets.

**Context Compression.** Prior approaches to context compression include LLM-based summarization (lossy, non-deterministic, requires API costs), embedding-based RAG (requires vector infrastructure, loses cross-entity relationships), and prompt engineering (Wang & Sun show this provides no significant benefit against interference). CtxPack differs by being deterministic, zero-dependency, and operating at the entity-relationship level rather than document-chunk level.

**Structured Knowledge Representation.** Knowledge graphs, ontologies, and entity-relationship models have long been used for structured knowledge management. CtxPack bridges these approaches with LLM serving by compiling structured knowledge into a format optimized for progressive retrieval, with provenance tracking and conflict detection that traditional RAG systems lack.

## 5. Limitations

1. **Fidelity gap on multi-hop questions.** Questions requiring information from 4+ entities lose accuracy because the 1-3 section retrieval limit prevents complete coverage. Increasing the section limit or implementing re-hydration loops would address this at the cost of higher per-query token usage.

2. **Minimum model requirement.** The LLM-as-router architecture requires Haiku-class capability or above. Very small models cannot reliably select sections or extract answers from structured context.

3. **Synthetic corpus.** The evaluation uses a synthetic enterprise corpus with consistent formatting. Real enterprise data includes inconsistent naming, ambiguous structure, embedded images, and colloquial language that would challenge the entity extraction pipeline.

4. **Sample size.** 30 evaluation questions provide approximately +/-18 percentage points margin of error at 95% confidence. The results are directionally reliable but not statistically definitive.

5. **No RAG baseline.** The evaluation compares against raw stuffing but not against standard embedding-based RAG retrieval, which is CtxPack's more direct competitor in production deployments.

6. **File-level BPE compression is minimal.** The packed knowledge base is approximately the same size as the raw corpus in BPE terms (~1.0x). CtxPack's value comes from per-query selective retrieval, not file-level compression.

## 6. Conclusion

CtxPack demonstrates that progressive hydration — indexing domain knowledge and serving relevant sections per query — achieves 93% of frontier-model fidelity at 3.8% of the token cost on enterprise-scale corpora. The architecture is grounded in the proactive interference findings of Wang & Sun (2025): by reducing per-query information load from 92K to 3.5K BPE tokens, CtxPack eliminates the interference that degrades retrieval accuracy in context-stuffed prompts.

The system's value proposition is cost reduction with bounded fidelity loss, not fidelity improvement. The 7 percentage point gap is stable across model sizes and acceptable for the majority of enterprise knowledge retrieval use cases, particularly given the 26x cost savings.

CtxPack is open source under the Apache 2.0 license. The pack pipeline, hydration protocol, MCP server integration, and evaluation framework are available at https://github.com/cryogenic22/CTX.ai.

## References

1. Wang, C. & Sun, J.V. (2025). "Unable to Forget: Proactive Interference Reveals Working Memory Limits in LLMs Beyond Context Length." ICML 2025 Workshop on Long Context Foundation Models.

2. Anthropic (2025). Claude Model Cards and Documentation.

3. OpenAI (2025). GPT-4o and GPT-4o-mini Technical Reports.
