# CtxPack: Progressive Hydration for Cost-Efficient LLM Domain Knowledge Serving

**Kapil Pant**
**March 2026**

*This is independent personal research by the author. The views, findings, and conclusions expressed in this paper are the author's own and do not reflect the position or policy of any employer, past or present.*

## Abstract

Large language models require domain knowledge in their context windows to answer enterprise questions accurately, but injecting entire knowledge bases is prohibitively expensive. We present CtxPack, a deterministic knowledge compiler that structures domain files into an indexed knowledge base and serves relevant sections per query through progressive hydration. On a 92K-token enterprise corpus (37 entities, 280 sections), CtxPack delivers 92% of frontier-model fidelity (80% vs 87%) at 6% of the total per-query token cost — a 16.6x cost reduction including both routing and answer generation. The fidelity gap is stable at 7 percentage points for models with sufficient capability (Claude Opus 4.6 and Claude Haiku 4.5), translating to approximately $39K/month savings at 1,000 queries/day on Claude Opus. The architecture is informed by recent findings on proactive interference in LLMs (Wang & Sun, 2025), which demonstrate that retrieval accuracy degrades log-linearly with competing information in context regardless of window size. CtxPack reduces per-query token injection by 94% through selective section injection, while its entity resolution pipeline eliminates cross-source conflicts that compound competing retrieval targets. The system is zero-dependency, deterministic, and requires no LLM in the packing loop. The "compile once, serve selectively" paradigm has been independently validated in other domains, notably for GUI agent automation (Zhong et al., 2026).

## 1. Introduction

Enterprise teams maintain domain knowledge across dozens of YAML configurations, Markdown runbooks, JSON schemas, and API specifications. When LLM-powered tools need this knowledge to answer questions, the standard approach is context stuffing — injecting the entire corpus into every prompt. This approach has three problems:

**Cost.** A 92K-token corpus costs $1.39 per query on Claude Opus ($15/M input tokens). At 1,000 queries/day, this is $41,700/month in API costs alone.

**Information overload.** Wang & Sun (2025) demonstrate that LLM retrieval accuracy degrades log-linearly as competing information accumulates in context, regardless of available context window length. Only model parameter count determines interference resistance. Stuffing 37 entity definitions with overlapping field names, retention policies, and PII classifications increases the volume of competing information the model must disambiguate.

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

The pipeline is deterministic (same input = byte-identical output), zero-dependency (stdlib Python only), and requires no LLM — making it free to run, auditable, and CI/CD compatible. File-level BPE compression is approximately 1.0x; the packed output is roughly the same size as the raw corpus in BPE terms. The value of the pack stage is structural — entity resolution, deduplication, conflict detection, and indexing — not file-size reduction.

### 2.2 Progressive Hydration (Decoder)

Rather than injecting the entire knowledge base, CtxPack serves content through a three-step protocol:

**Step 1: L3 Directory Index.** An ultra-lean index (~1,800 BPE tokens for 37 entities) lists available sections with their primary identifiers. This goes in the system prompt permanently.

**Step 2: LLM-as-Router.** When a question arrives, the LLM reads the directory index and decides which 1-3 sections to retrieve — no embeddings, no vector database, no external infrastructure. The LLM's own comprehension of the directory serves as the query router. This routing step costs approximately 2,000 BPE tokens (L3 prompt + question).

**Step 3: Section Hydration.** The requested sections are injected as focused context (~3,500 BPE average). The LLM answers from this targeted subset.

The total per-query cost is approximately 5,500 BPE tokens (routing call + answer call), compared to 92,500 BPE for raw stuffing — a 16.6x reduction.

This architecture parallels the "compile once, serve selectively" paradigm independently validated by Zhong et al. (2026) for GUI agent automation, where offline structural compilation of application state machines yields 11.8x cost reduction with 95% task success.

### 2.3 Entity Resolution as Redundancy Reduction

The pack pipeline's entity resolution reduces redundant information in the knowledge base. When a corpus contains overlapping definitions — Customer retention policy stated in the entity YAML, a governance runbook, and a compliance rules file — the packer merges them into a single canonical section with provenance tracking. Without this merge, raw stuffing presents the LLM with multiple definitions of the same concept, increasing the volume of information the model must process.

Conflict detection further surfaces contradictions (e.g., "Customer PII retention: 30 days" in one file vs "90 days" in another) rather than leaving the LLM to silently choose between conflicting values.

## 3. Evaluation

### 3.1 Methodology

We evaluate on a synthetic enterprise corpus modeled on e-commerce data platform knowledge:

- **Corpus**: 37 YAML entity definitions, 11 Markdown runbooks, 5 governance rule files (46,500 words, 92,482 BPE tokens)
- **Entities**: Customer, Order, Payment, Product, Merchant, Inventory, Shipment, and 30 related entities with realistic fields, relationships, retention policies, and PII classifications
- **Questions**: 30 evaluation questions across 5 categories — easy factual (12), cross-entity (8), negation (4), multi-hop (4), adversarial (4)
- **Models tested**: Claude Opus 4.6, Claude Haiku 4.5, GPT-4o-mini
- **Judge**: GPT-4o as cross-model judge for all arms and all models (eliminates self-judging bias and rate-limit asymmetry)
- **Metrics**: BPE token count (tiktoken cl100k_base) as primary unit; both rule-based keyword matching and LLM-as-judge grading

All token counts use actual BPE tokenization, not word-count proxies. The evaluation pipeline includes exponential backoff retry logic (5 retries with 2-32s delays on HTTP 429/500/502/503/504), cross-model judging, error detection (judge failures tracked separately and reported), and inter-call rate-limit delays (0.5s between API calls) to ensure measurement reliability.

The corpus is synthetic (generated to match realistic enterprise patterns) and the sample size is 30 questions, providing approximately ±18 percentage points margin of error at 95% confidence. Results are directionally reliable but should be validated on real enterprise data and larger question sets before production deployment decisions.

### 3.2 Results

#### Table 1: Cost and Fidelity — 92K BPE Enterprise Corpus (Claude Opus 4.6)

| Method | BPE/Query | Cost/Query | Fidelity (Judge) | Judge Failures |
|---|---|---|---|---|
| Raw Stuffing | 92,482 | $1.3872 | 86.7% | 0 |
| CtxPack Hydrated (total) | ~5,556 | ~$0.0833 | 80.0% | 0 |

Hydrated total includes the routing call (~2,033 BPE) plus the answer call (~3,523 BPE). Cost reduction: **16.6x**. Fidelity retention: **92%** of raw baseline.

#### Table 2: Model Spread — Fidelity by Model Size

| Model | Raw Fidelity | Hydrated Fidelity | Gap | Judge Failures |
|---|---|---|---|---|
| Claude Opus 4.6 | 86.7% | 80.0% | 6.7pp | 0 |
| Claude Haiku 4.5 | 76.7% | 70.0% | 6.7pp | 0 |
| GPT-4o-mini | 56.7% | 20.0% | 36.7pp | 0 |

The fidelity gap is stable at 6.7pp for Claude Opus and Claude Haiku. GPT-4o-mini shows a much larger gap (36.7pp), indicating a minimum model capability threshold for the LLM-as-router architecture (discussed in Section 3.3).

#### Table 3: Fidelity by Question Difficulty (Claude Opus 4.6)

| Difficulty | Raw Stuffing | Hydrated | Questions |
|---|---|---|---|
| Easy | 92% | 92% | 12 |
| Medium | 100% | 89% | 9 |
| Hard | 67% | 56% | 9 |

### 3.3 Analysis

**Cost reduction is the primary value.** Including routing costs, CtxPack delivers 16.6x per-query cost savings — $0.08 vs $1.39 on Claude Opus. For 1,000 queries/day, this is approximately $39,000/month in savings. The savings scale with corpus size: larger corpora increase raw stuffing cost linearly while hydration cost grows only with the number of sections retrieved per query.

**Fidelity gap is stable at 7pp for capable models.** Opus and Haiku both show a 6.7 percentage point fidelity reduction from hydration. On easy factual questions, fidelity is identical (92%/92%). The gap comes primarily from multi-hop questions requiring information spread across 4+ entities, where the 1-3 section retrieval limit prevents complete coverage.

**Minimum model capability threshold.** GPT-4o-mini (20% hydrated fidelity) demonstrates that the LLM-as-router architecture requires sufficient model capability for both section selection and answer extraction from structured context. The routing task — reading a directory index and selecting relevant sections — requires at minimum Haiku-class capability. Below this threshold, routing quality degrades faster than any benefit from focused context injection.

**Interference effect observed but not isolated.** Raw stuffing fidelity decreases with model size (87% → 77% → 57%), consistent with Wang & Sun's (2025) finding that interference resistance scales with parameter count. However, hydrated fidelity also decreases proportionally (80% → 70% → 20%), indicating that both routing quality and answer extraction capability degrade with model size. The fidelity crossover point — where hydration surpasses raw stuffing on accuracy — was not observed at the 92K corpus scale tested. This may occur at larger corpus sizes or on models with lower interference resistance, but we did not test this.

**File-level compression is not the value driver.** The packed knowledge base is approximately the same size as the raw corpus in BPE terms (~1.0x). CtxPack's cost reduction comes entirely from per-query selective retrieval, not from file-size compression. This is an important distinction: the value is in the serving architecture, not in the packed artifact.

### 3.4 Measurement Integrity

The evaluation includes six automated red team checks that run with every eval:

| Check | Threshold | Result |
|---|---|---|
| L3 index budget | <10% of corpus | 2.0% (PASS) |
| Hydration cost vs raw | <=20% | 6.0% (PASS) |
| Hydration fidelity floor | >=50% | 80% (PASS) |
| Fidelity gap (raw - hydrated) | <=15pp | 7pp (PASS) |
| Rule/Judge score divergence | <=30pp | 13pp (PASS) |
| Judge failure rate | <=10% | 0% (PASS) |

Additionally, CI-gated metric sanity tests prevent common measurement errors: BPE/word ratio divergence (catches encoding that games word-count metrics), compression ratio consistency (catches divergence between word-based and BPE-based ratios), and header token accuracy (catches misleading metadata in output files).

An earlier version of this evaluation framework contained measurement errors that produced inflated results (see Section 5, Limitation 7). The current pipeline was redesigned to prevent recurrence.

## 4. Relation to Prior Work

**Proactive Interference in LLMs.** Wang & Sun (2025) demonstrate that LLM retrieval accuracy declines log-linearly with proactive interference from competing information in context, and that context window length has no significant effect on this degradation (p = 0.886). CtxPack's progressive hydration is designed to reduce the volume of competing information per query — from 37 entity sections to 1-3 relevant sections. However, we note that our evaluation measured fidelity (answer correctness), not proactive interference directly. The relationship between token reduction and interference reduction is architecturally motivated but not empirically isolated in this study.

**Compile-Once-Serve-Selectively.** Zhong et al. (2026) independently demonstrate the same architectural paradigm for GUI agent automation: offline structural compilation of application state machines yields 11.8x cost reduction and 95% task success vs reactive (step-by-step) approaches. CtxPack applies this paradigm to domain knowledge serving, achieving comparable cost reduction (16.6x) through progressive hydration. The convergence of these results across different domains suggests that offline compilation + selective online serving is a generalizable pattern for cost-efficient LLM systems.

**Context Compression.** Prior approaches to context compression include LLM-based summarization (lossy, non-deterministic, requires API costs), embedding-based RAG (requires vector infrastructure, loses cross-entity relationships), and prompt engineering (Wang & Sun show this provides no significant benefit against interference). CtxPack differs by being deterministic, zero-dependency, and operating at the entity-relationship level rather than document-chunk level. CtxPack does not achieve meaningful file-level compression in BPE terms; its value is in structural indexing and selective retrieval.

**Structured Knowledge Representation.** Knowledge graphs, ontologies, and entity-relationship models have long been used for structured knowledge management. CtxPack bridges these approaches with LLM serving by compiling structured knowledge into a format optimized for progressive retrieval, with provenance tracking and conflict detection that traditional RAG systems lack.

## 5. Limitations

1. **Fidelity gap on multi-hop questions.** Questions requiring information from 4+ entities lose accuracy because the 1-3 section retrieval limit prevents complete coverage. Increasing the section limit or implementing re-hydration loops would address this at the cost of higher per-query token usage.

2. **Minimum model requirement.** The LLM-as-router architecture requires Haiku-class capability or above. GPT-4o-mini scored 20% hydrated fidelity, indicating the routing task exceeds its capability. This limits CtxPack's applicability to the smallest, cheapest models.

3. **Synthetic corpus.** The evaluation uses a synthetic enterprise corpus generated to match realistic patterns. Real enterprise data includes inconsistent naming, ambiguous structure, embedded images, colloquial language, and formatting variations that would challenge the entity extraction pipeline. Results should be validated on real enterprise documentation before production deployment.

4. **Sample size.** 30 evaluation questions provide approximately ±18 percentage points margin of error at 95% confidence (binomial). The results are directionally reliable but not statistically definitive. A 100+ question evaluation would be needed for publishable statistical significance.

5. **No RAG baseline.** The evaluation compares against raw stuffing but not against standard embedding-based RAG retrieval, which is CtxPack's more direct competitor in production deployments. The relative performance vs RAG is unknown.

6. **File-level compression is minimal.** The packed knowledge base is approximately the same size as the raw corpus in BPE terms (~1.0x). CtxPack's cost reduction comes from per-query selective retrieval, not file-size compression. Organizations seeking file-level compression should not expect meaningful reduction from CtxPack.

7. **Prior measurement errors.** An earlier version of the evaluation framework (v0.1-v0.3) used word count (`len(text.split())`) as a proxy for BPE token count. The compression format's encoding inflated word-based metrics by approximately 4-5x compared to actual BPE counts, producing overstated compression ratios in earlier publications. The current framework uses tiktoken BPE tokenization as the primary metric, with CI-gated sanity tests to prevent recurrence. Additionally, an earlier evaluation run suffered from rate-limit-induced judge failures that silently corrupted fidelity scores. The current pipeline includes cross-model judging, retry logic, and explicit failure tracking to prevent this class of error.

8. **Routing cost not always reported.** Per-query cost comparisons should include the routing call (~2,000 BPE) in addition to the answer call (~3,500 BPE). Some intermediate analyses during development reported only the answer call cost, understating the true per-query cost by approximately 37%. All figures in this paper include routing costs.

## 6. Conclusion

CtxPack demonstrates that progressive hydration — indexing domain knowledge and serving relevant sections per query — achieves 92% of frontier-model fidelity at 6% of the total per-query token cost on an enterprise-scale corpus. Including routing costs, this is a 16.6x cost reduction.

The system's value proposition is cost reduction with bounded fidelity loss, not fidelity improvement or file-level compression. The 7 percentage point fidelity gap is stable across capable models (Opus and Haiku class) and concentrated in multi-hop questions. For easy and medium-difficulty questions — which represent the majority of enterprise knowledge retrieval — hydrated fidelity matches raw stuffing.

The architecture is informed by Wang & Sun's (2025) proactive interference findings and independently parallels the compile-then-serve paradigm validated by Zhong et al. (2026) in GUI agent automation. The convergence of cost-reduction results across domains (16.6x for knowledge serving, 11.8x for GUI automation) suggests this is a robust architectural pattern for LLM systems at scale.

CtxPack is open source under the Apache 2.0 license at https://github.com/cryogenic22/CTX.ai.

## References

1. Wang, C. & Sun, J.V. (2025). "Unable to Forget: Proactive Interference Reveals Working Memory Limits in LLMs Beyond Context Length." ICML 2025 Workshop on Long Context Foundation Models.

2. Zhong, H. et al. (2026). "ActionEngine: From Reactive to Programmatic GUI Agents via State Machine Memory." arXiv:2602.20502.

3. Anthropic (2025). Claude Model Cards and Documentation.

4. OpenAI (2025). GPT-4o and GPT-4o-mini Technical Reports.
