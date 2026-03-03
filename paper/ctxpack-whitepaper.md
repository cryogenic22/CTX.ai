# CtxPack: Perceptual Context Compression for Large Language Models

**Kapil Pant**
Independent Researcher

**Abstract.** Large language models consume context tokens linearly in cost and quadratically in attention computation, yet most injected context — domain rules, entity definitions, operational knowledge — contains significant structural redundancy. We present CtxPack, an open-source, deterministic context compression codec that exploits the gap between *information density as written for humans* and *information density as consumed by transformers*. CtxPack introduces `.ctx`, a multi-resolution text format with a formal grammar, and a packer that converts structured domain corpora (YAML, Markdown, JSON) into semantically compressed context through entity resolution, deduplication, heuristic salience scoring, and hierarchical notation. In controlled evaluations across 12 models from 3 ecosystems (Anthropic, OpenAI, Google) — including frontier models (Claude Sonnet 4.5, GPT-5.2 Pro), reasoning models (o3, o4-mini), and lightweight models (Haiku 4.5, Gemini 2.5 Flash Lite) — CtxPack's L2 notation achieves a 92–100% fidelity floor at 139 tokens (3x compression of 417-token L1 prose), with 4 models reaching 100%. Critically, L2 fidelity meets or exceeds L1 on 11 of 12 models, demonstrating that compact semantic notation is not a barrier to comprehension — it is at least as effective as natural-language prose at one-third the token cost. In scaling evaluations across corpus sizes from 690 to 37,000 tokens, CtxPack achieves 5.6–8.3x compression while raw context stuffing collapses at scale due to the lost-in-the-middle effect. An LLM-generated summary baseline at equivalent token budgets performs substantially worse than CtxPack, demonstrating that structured compression consistently outperforms free-form summarization. A proof-of-concept agent compression experiment compresses a 30-step coding agent trace to 485 tokens with 9 entities merged in 0.71ms. We release the codec, evaluation framework, cross-ecosystem results, and all raw API logs under AGPL-3.0.

---

## 1. Introduction

The economic and computational cost of LLM context windows creates a fundamental tension: organizations possess rich domain knowledge (data contracts, entity definitions, business rules, regulatory policies) that dramatically improves LLM output quality when injected as context, but the cost of injecting this knowledge scales linearly with token count at $3–15 per million input tokens for frontier models. A 40,000-token domain corpus costs $0.12–0.60 per query — prohibitive for production systems handling thousands of daily requests.

Existing approaches to this problem fall into three categories, each with significant limitations:

**Token-level compression** (LLMLingua [Jiang et al., 2023], Selective Context [Li et al., 2023]) removes tokens deemed low-information by a smaller model. These methods achieve 2–5x compression but operate without semantic understanding, risking removal of structurally critical tokens (entity identifiers, threshold values, relationship markers) that are lexically common but semantically load-bearing.

**Embedding-based compression** (Gist Tokens [Mu et al., 2023], AutoCompressors [Chevalier et al., 2023]) project context into continuous vector representations. These achieve high compression ratios but produce opaque, non-inspectable representations that cannot be cached across sessions, versioned, debugged, or audited — requirements in regulated industries.

**Retrieval-augmented generation** (RAG) avoids full-corpus injection by retrieving relevant chunks per query. However, RAG introduces its own failure modes: retrieved chunks are redundant (the same fact appears across multiple chunks), critical cross-entity relationships span chunk boundaries, and information positioned in the middle of retrieved context is systematically ignored by transformer attention (Liu et al., 2023).

CtxPack takes a fundamentally different approach inspired by perceptual audio codecs. MP3 does not compress audio by removing random samples; it exploits a psychoacoustic model of human hearing to discard information the ear cannot perceive. Analogously, CtxPack exploits a *transformer-perceptual model* of how LLMs consume structured context: entity-relationship hierarchies compress into dense notation without information loss because the model reconstructs the full semantics from structural cues, while prose filler words ("the", "is used for", "this means that") can be stripped without affecting comprehension.

### 1.1 Contributions

1. **The `.ctx` format**: A formal, multi-resolution text compression format with a PEG grammar, three conformance levels (L1: structured prose, L2: semantic graph notation, L3: abstract gist), and a defined operator alphabet for entity relationships, status flows, retention policies, and cross-references (Section 3).

2. **A deterministic packer**: A pure-Python, zero-dependency pipeline that converts YAML + Markdown + JSON domain corpora into `.ctx` L2 output through entity extraction, resolution, deduplication, conflict detection, and heuristic salience scoring (Section 4).

3. **Cross-ecosystem empirical evidence**: Controlled evaluations across 12 models from 3 ecosystems (Anthropic, OpenAI, Google) demonstrating a 92–100% fidelity floor on L2 notation, with L2 meeting or exceeding L1 fidelity on 11 of 12 models (Section 5). Scaling evaluations across 690–37K tokens confirm structured compression outperforms all baselines at scale (Section 5.3).

4. **A counterintuitive finding**: At the per-question level, the packer's scope inference (Section 4.2) disambiguates implicit qualifiers that models misread in raw YAML, producing higher-fidelity answers on specific questions. The codec does not merely preserve information — it can clarify it (Section 5.4).

5. **An open evaluation framework**: A reproducible benchmark with 25 curated questions (including adversarial hallucination traps), dual grading (rule-based + LLM-as-judge), a scaling corpus generator, and complete raw logs of all API calls — released under AGPL-3.0.

6. **Agent context compression**: A proof-of-concept demonstrating the format's applicability beyond static knowledge packing — compressing a 30-step coding agent trace into structured `.ctx` output with entity merging and provenance tracking in sub-millisecond latency (Section 5.7).

---

## 2. Related Work

### 2.1 Token-Level Context Compression

LLMLingua (Jiang et al., 2023) uses a small language model to compute per-token perplexity and removes low-perplexity tokens. LongLLMLingua (Jiang et al., 2024) extends this with question-aware compression for RAG scenarios. Selective Context (Li et al., 2023) applies a similar approach using self-information to identify and remove low-information-content tokens. These methods operate at the token level without understanding document structure, making them effective for narrative prose but poorly suited for structured domain knowledge where every field name, threshold value, and entity reference carries high information density regardless of lexical frequency.

### 2.2 Learned Soft Compression

Gist Tokens (Mu et al., 2023) train a model to compress instructions into a small number of virtual tokens in the embedding space. AutoCompressors (Chevalier et al., 2023) extend this to multi-step compression. ICAE (Ge et al., 2024) uses an autoencoder approach. While achieving very high compression ratios (10–25x), these methods produce opaque representations that cannot be inspected, cached as text, version-controlled, or audited. They also require training or fine-tuning, limiting applicability to specific model families.

### 2.3 Retrieval-Augmented Generation

RAG (Lewis et al., 2020) retrieves relevant document chunks at query time, avoiding full-corpus injection. However, Liu et al. (2023) demonstrated that LLMs systematically fail to use information positioned in the middle of their context window — the "lost-in-the-middle" phenomenon. RAG pipelines typically retrieve 10–20 chunks (15–25K tokens), introducing redundancy across chunks and fragmentation of cross-entity relationships. CtxPack is complementary to RAG: it can serve as a post-processing layer that compresses retrieved chunks before injection.

### 2.4 Structured Knowledge Representation

Traditional approaches like RDF, OWL, and knowledge graphs represent structured knowledge formally but are not designed for LLM consumption — they require query languages (SPARQL) and inference engines rather than direct context injection. JSON-LD and Schema.org provide structured markup but optimize for machine interoperability, not token efficiency. CtxPack occupies a novel position: a format designed specifically for the LLM-as-consumer use case, balancing human readability, machine parseability, and token density. Concurrently, Gloaguen et al. (2026) demonstrate that unstructured repository-level context files (AGENTS.md) reduce coding agent task success by 0.5–2% while increasing cost 20%+, attributing failures to redundancy and unnecessary requirements — failure modes that CtxPack's entity resolution and salience scoring are designed to address.

---

## 3. The `.ctx` Format

### 3.1 Design Principles

The `.ctx` format is guided by four principles:

1. **Plain text, not binary.** `.ctx` files are UTF-8 text that can be read by humans, diffed with standard tools, and version-controlled in git. This enables domain experts to inspect and validate compressed knowledge without special tooling.

2. **Multi-resolution.** A single document can contain content at different compression levels, enabling progressive hydration — serve L3 (gist) for simple queries, L2 (semantic graph) for detailed questions, L1 (compressed prose) when verbatim detail matters.

3. **Deterministic and reproducible.** Given the same input corpus, the packer produces identical output. No randomness, no model-dependent compression, no floating-point accumulation. The same `.ctx` file produces the same results regardless of when or where it was generated.

4. **Format-aware, not model-specific.** The `.ctx` notation is designed for general transformer consumption, not optimised for any single model's tokeniser. Cross-ecosystem evaluation (Section 5) confirms portability across 12 models from 3 ecosystems while revealing that compact notation is at least as effective as natural-language prose.

### 3.2 Document Structure

A `.ctx` document begins with a header line and contains a sequence of sections:

```
§CTX v1.0 L2 DOMAIN:customer-data-platform
COMPRESSED:2026-02-22 SOURCE_TOKENS:~647

±ENTITY-CUSTOMER ★GOLDEN-SOURCE:CRM-(Salesforce)
IDENTIFIER:customer_id(UUID,immutable)
MATCH-RULES:[email:exact-match(case-insensitive),
  phone:normalise(E.164),
  name+address:fuzzy-match(Jaro-Winkler>0.92)]
PII:name+email+phone+address→RESTRICTED
RETENTION:active→indefinite|churned→36mo→anonymise

±ENTITY-ORDER
IDENTIFIER:order_id(UUID,immutable)
BELONGS-TO:@ENTITY-CUSTOMER(customer_id,mandatory)
STATUS-MACHINE:draft→submitted→processing→shipped→delivered
FINANCIAL-FIELDS:[subtotal,tax,shipping_cost,total]→DECIMAL(19,4)
```

### 3.3 Operator Alphabet

The L2 notation uses a defined set of operators:

| Operator | Meaning | Example |
|----------|---------|---------|
| `§` | Document header | `§CTX v1.0 L2` |
| `±` | Section boundary | `±ENTITY-CUSTOMER` |
| `→` | Flow / transition | `draft→submitted→delivered` |
| `\|` | Alternative / branch | `active→indefinite\|churned→36→anonymise` |
| `+` | Conjunction / list | `name+email+phone` |
| `★` | High-salience marker | `★GOLDEN-SOURCE:CRM` |
| `⚠` | Warning / conflict | `⚠ Retention conflict detected` |
| `@` | Entity cross-reference | `@ENTITY-CUSTOMER` |
| `¬` | Negation / exclusion | `¬FLOAT-for-financial` |

These operators are chosen for their visual distinctiveness to transformer tokenizers. Unicode operators (`→`, `★`, `⚠`) tokenize as single or two-token units in most tokenizers, providing high information density per token.[^1]

[^1]: We did not measure tokenizer-specific token counts for the `.ctx` output across models. The token counts reported throughout use whitespace-split approximation. Actual tokenizer differences between models may produce slightly different effective token counts and compression ratios. We expect the difference to be small (<10%) given the operator-dense, ASCII-heavy nature of the format, but precise cross-tokenizer measurement is left to future work.

### 3.4 Conformance Levels

The format defines three conformance levels:

- **L1 (Compressed Prose):** Filler words removed, sentences shortened, but natural language structure preserved. Readable by non-technical stakeholders.
- **L2 (Semantic Graph):** Entity-relationship notation with operators. The primary level for domain knowledge packing. Human-readable with brief familiarization.
- **L3 (Abstract Gist):** Maximally compressed summaries using entity references and operator chains. Suitable for system prompts and routing decisions.

### 3.5 Formal Grammar

The format is specified by a PEG grammar (105 production rules). A compliant parser is provided as a recursive-descent implementation in pure Python (410 lines, zero external dependencies). The parser handles all three conformance levels and produces a frozen-dataclass AST (CTXDocument, Header, Section, KeyValue, InlineList, PlainLine, QuotedBlock).

---

## 4. The Packer

### 4.1 Pipeline Overview

The packer converts a directory of YAML, Markdown, and JSON source files into a single `.ctx` L2 document through a six-stage pipeline:

```
Discover → Parse → Entity Resolve → Conflict Detect → Score → Compress
```

**Stage 1: Discovery.** Walk the corpus directory, classify files by extension (.yaml/.yml, .md, .json), and load optional `ctxpack.yaml` configuration (domain name, entity aliases, golden source mappings, include/exclude patterns).

**Stage 2: Parsing.** YAML files are parsed by a stdlib-only subset parser (722 lines, handling maps, sequences, nested structures, flow notation, and scalars; rejecting anchors, tags, and multi-line scalars with clear error messages). Markdown files are parsed by a heading/list extractor that maps H1/H2 headings to entity boundaries and bullet lists to rules. JSON files are parsed with support for JSON Schema entity definitions and nested arrays. All parsers produce an intermediate representation (IR) of entities, fields, and warnings.

**Stage 3: Entity Resolution.** Entities from multiple source files are merged through a four-strategy cascade: exact name match → case-insensitive match → configured alias match → singular/plural match. Fields are deduplicated by key + value identity, with provenance tracked across all sources.

**Stage 4: Conflict Detection.** A rule-based conflict detector identifies contradictions across the resolved corpus: retention policy conflicts (e.g., entity says 36 months, regulation says 7 years), null-policy contradictions (never-null vs. nullable for the same field), type mismatches, and PII classification inconsistencies. Detected conflicts are surfaced as `⚠` warnings in the output.

**Stage 5: Salience Scoring.** Each entity and field receives a salience score determining its position and inclusion priority in the output. The Phase 1 scorer uses a heuristic formula:

$$\text{entity\_score} = (\text{source\_count} \times 1.0 + \text{cross\_refs} \times 2.0 + \text{warnings} \times 1.5) \times \text{golden\_boost}(1.5)$$

Fields are boosted by marker presence (★: 2.0x), warning presence (⚠: 1.5x), and high-value key types (IDENTIFIER, PII, MATCH-RULES: 1.3x). Entities are sorted by descending salience in the output, placing the most important information at the beginning and end of the context — the positions where transformer attention is strongest (Liu et al., 2023).

**Stage 6: Compression.** The scored IR is converted to a CTXDocument AST bottom-up. Entity fields are compressed according to type-specific rules:

| Source Pattern | Compressed Notation |
|---|---|
| `identifier: {name: X, type: T, immutable: true}` | `IDENTIFIER:X(T,immutable)` |
| `retention: {active: indef, churned: {months: 36, action: anonymise}}` | `RETENTION:active→indefinite\|churned→36→anonymise` |
| `status_flow: [draft, submitted, ..., delivered]` | `STATUS-MACHINE:draft→submitted→...→delivered` |
| `pii: [name, email, phone] + pii_classification: RESTRICTED` | `PII:name+email+phone→RESTRICTED` |
| `belongs_to: {entity: CUSTOMER, field: cust_id, mandatory: true}` | `BELONGS-TO:@ENTITY-CUSTOMER(cust_id,mandatory)` |

### 4.2 Scope Inference

A notable packer behavior is *scope inference* from entity descriptions. When an entity's identifier has a boolean `unique: true` flag and the entity description mentions a scope qualifier ("one per merchant", "per tenant", "per organization"), the packer enriches the compressed identifier:

```yaml
# Source YAML
entity: PRODUCT
description: Product catalog entity, one per merchant
identifier:
  name: sku
  type: string
  unique: true
```

```
# Compressed .ctx
±ENTITY-PRODUCT
IDENTIFIER:sku(string,unique-per-merchant)
```

The raw YAML states `unique: true` without specifying scope. The packer infers `unique-per-merchant` from the description field. This is a form of *disambiguation during compression* — the codec makes implicit knowledge explicit, improving downstream LLM comprehension (see Section 5.4 for empirical evidence).

This inference is implemented through pattern matching against a fixed set of scope markers ("per merchant", "per tenant", "per organization", etc.) and can be disabled via a `--strict` flag for environments where only explicit field values should be preserved.

### 4.3 L1 Serialization

In addition to the primary L2 output, the packer supports L1 (compressed prose) serialization. L1 output preserves natural language structure — sentences are shortened and filler words removed, but the result reads as conventional prose with headings and bullet points. This provides a baseline for evaluating whether L2's compact notation imposes a comprehension cost: if models perform equally well on L1 and L2, the notation itself is not a barrier. The L1 serializer produces output approximately 3x larger than L2 (417 vs. 139 tokens on the golden set), establishing the cost-fidelity tradeoff between the two conformance levels.

### 4.4 Implementation

The packer is implemented in pure Python with zero external dependencies (2,407 lines across 10 modules). The YAML subset parser avoids the need for PyYAML. All operations are deterministic and reproducible. The implementation is packaged as a CLI tool (`ctxpack pack <corpus-dir>`) and a Python API (`from ctxpack.core.packer import pack`).

---

## 5. Evaluation

### 5.1 Methodology

We evaluate CtxPack on two axes: **compression efficiency** (ratio of source tokens to compressed tokens) and **information fidelity** (percentage of factual questions correctly answered by an LLM using only the compressed context).

**Golden Set.** A fixed corpus of 10 source files (4 entity YAMLs, 2 rule YAMLs, 3 Markdown documents, 1 configuration YAML) representing a customer data platform domain. The corpus contains 4 entities (CUSTOMER, ORDER, PAYMENT, PRODUCT) with cross-entity relationships, 2 planted retention-policy conflicts, entity aliases, and operational tribal knowledge. Total source size: 690 tokens.

**Questions.** 25 question-answer pairs graded by difficulty:
- **Easy** (7): Direct field lookups (e.g., "What type is the customer_id field?")
- **Medium** (11): Multi-field extraction requiring inference (e.g., "What matching algorithm is used for name+address?")
- **Hard** (7): Cross-document conflict detection, adversarial hallucination traps, and cross-entity negation inference

The question set includes 5 adversarial questions: 2 hallucination traps where the correct answer is "not specified in context" (testing whether the LLM confabulates from the compressed representation), 2 low-salience edge cases testing preservation of operationally critical but infrequently referenced details, and 1 cross-entity negation requiring inference of a mandatory relationship constraint.

**Baselines.** We compare four methods at each corpus scale:

1. **Raw stuffing**: Concatenate all source files verbatim (upper bound on information content, lower bound on compression).
2. **CtxPack L2**: Packer-compressed `.ctx` output (our method).
3. **LLM summary**: Ask the evaluation model to summarize the corpus into the same token budget as CtxPack's output. This is the key competitive baseline — "why not just ask the LLM to summarize?"
4. **Naive truncation**: Take the first N words of the concatenated source to match CtxPack's token count. This establishes a floor.

**Grading.** Each question is graded by two independent methods:

1. **Rule-based grading**: Normalized keyword matching with prefix-aware fuzzy matching. The answer and expected answer are normalized (hyphens/underscores collapsed, punctuation stripped), then key terms (>2 characters) are extracted from the expected answer and matched against the actual answer. A 60% term-match threshold is required. For adversarial "NOT_IN_CONTEXT" questions, the grader checks for explicit signals ("not found in context", "not specified", etc.).

2. **LLM-as-judge**: The same LLM is prompted to compare the candidate answer against the expected answer and respond with CORRECT or INCORRECT. This provides a more nuanced assessment that can recognize semantic equivalence beyond keyword overlap.

Both scores are reported. In cross-model comparisons, we use LLM-as-judge as the primary metric because the rule-based grader has format sensitivity to answer phrasing that varies between models.

**Self-judging note.** Each model generates its own answers and serves as its own judge. This avoids cross-model grading bias (e.g., Claude judging GPT-4o's phrasing) but introduces potential model-specific grading leniency.

**Prompt equalization.** All models receive identical system and user messages at every stage (answering and judging). The system message for Q&A is: *"You are a precise Q&A assistant. Answer concisely based only on the provided context."* The judging system message is: *"You are an expert grader evaluating answer correctness."* Temperature is set to 0 for all providers to reduce inter-run variance.[^3]

[^3]: Google's Gemini API accepts `temperature=0` but may still exhibit minor non-determinism on some model versions. All Gemini evaluation runs completed without errors at this setting.

**Evaluation models.** 12 models across 3 ecosystems:

- **Anthropic** (2): Claude Sonnet 4.5, Claude Haiku 4.5
- **OpenAI** (7): GPT-5.2, GPT-5.2 Pro, GPT-4.1, GPT-4o, GPT-4o-mini, o3, o4-mini
- **Google** (3): Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 2.5 Flash Lite

Each model is tested on both L2 (139 tokens) and L1 (417 tokens) representations of the same golden set, producing 24 evaluation runs.[^2] All API calls are logged with timestamps and full request/response payloads for reproducibility.

[^2]: GPT-5.2 and GPT-5.2 Pro are the same base model with different reasoning effort settings; we treat them as separate evaluation targets because they produce different fidelity results (92% vs. 100% on L2).

**L2/L1 protocol.** Each model answers the same 25 questions twice: once with the L2 (semantic graph, 139 tokens) context and once with the L1 (compressed prose, 417 tokens) context. This paired design isolates the effect of notation density from information content — both representations encode the same facts from the same corpus, but L2 uses 3x fewer tokens via operator notation.

**Scaling evaluation.** Two models (Claude Sonnet 4.6, GPT-4o) are additionally evaluated across corpus scales from 690 to 37K tokens with all four baselines. The scaling curve uses the v0.2 evaluation methodology (Section 5.3).

**Total evaluation cost.** The complete evaluation (golden set cross-ecosystem + scaling curve) required approximately 3,000 API calls across two evaluation rounds (v0.2 scaling curve + v0.3 cross-ecosystem golden set). Total API cost was approximately $40 across all providers.

### 5.2 Cross-Ecosystem Golden Set Results

Table 1 presents L2 and L1 fidelity (LLM-as-judge) for all 12 models on the golden set (690 source tokens, 25 questions), sorted by L2 fidelity.

**Table 1.** Cross-ecosystem golden set evaluation. L2 = 139 tokens (semantic graph notation). L1 = 417 tokens (compressed prose). Fidelity = LLM-as-judge score. All models receive identical prompts, temperature = 0.

| Model | Ecosystem | L2 (139 tok) | L1 (417 tok) | L2 ≥ L1? |
|-------|-----------|:---:|:---:|:---:|
| Claude Sonnet 4.5 | Anthropic | 100% | 100% | = |
| Claude Haiku 4.5 | Anthropic | 100% | 100% | = |
| GPT-5.2 Pro | OpenAI | 100% | 96% | ✓ |
| o4-mini | OpenAI | 100% | 100% | = |
| GPT-4.1 | OpenAI | 96% | 100% | ✗ |
| GPT-4o-mini | OpenAI | 96% | 96% | = |
| GPT-5.2 | OpenAI | 92% | 92% | = |
| o3 | OpenAI | 92% | 92% | = |
| GPT-4o | OpenAI | 92% | 88% | ✓ |
| Gemini 2.5 Pro | Google | 92% | 92% | = |
| Gemini 2.5 Flash | Google | 92% | 84% | ✓ |
| Gemini 2.5 Flash Lite | Google | 92% | 92% | = |

Four findings emerge from the cross-ecosystem comparison:

**1. A 92% fidelity floor across all ecosystems.** Every model tested — from the cheapest (Gemini 2.5 Flash Lite) to the most capable (GPT-5.2 Pro) — achieves at least 92% on L2 at 139 tokens. This floor holds across all three ecosystems, confirming that `.ctx` notation is not ecosystem-specific.

**2. Four models achieve 100% L2 fidelity.** Claude Sonnet 4.5, Claude Haiku 4.5, GPT-5.2 Pro, and o4-mini answer all 25 questions correctly from just 139 tokens. Notably, this includes both the cheapest Anthropic model (Haiku) and OpenAI's reasoning model (o4-mini), suggesting that `.ctx` fluency is not correlated with model size or cost.

**3. L2 meets or exceeds L1 on 11 of 12 models.** Despite using 3x fewer tokens, L2 matches or outperforms L1 on all models except GPT-4.1 (96% L2 vs. 100% L1). Three models show L2 strictly outperforming L1: GPT-5.2 Pro (100% vs. 96%), GPT-4o (92% vs. 88%), and Gemini 2.5 Flash (92% vs. 84%). This is the most important finding: compact notation is not a comprehension barrier — it is at least as effective as prose, and for some models, the reduced token count improves attention focus.

**4. Ecosystem-level consistency.** Aggregating by ecosystem: Anthropic models average 100% L2, OpenAI models range 92–100%, Google models are uniformly 92%. No ecosystem shows systematic weakness, confirming cross-ecosystem portability.

### 5.3 Scaling Curve

To test whether compression advantages hold at scale, we evaluated two models (Claude Sonnet 4.6, GPT-4o) across synthetic corpora at 1K, 5K, 20K, and 50K source tokens using a multi-domain entity generator covering retail, logistics, healthcare, fintech, HR, and marketing entities. The scaling curve was conducted with Claude Sonnet 4.6 during an earlier evaluation phase; the golden set cross-ecosystem evaluation (Table 1) uses the current model version (Sonnet 4.5). Minor version differences between Sonnet 4.5 and 4.6 are not expected to materially affect scaling characteristics. Questions were generated proportionally (24–25 per scale, stratified by difficulty). The golden set (690 tokens) was re-evaluated as the first scale point; minor differences from Table 1 reflect LLM-as-judge variance between independent runs.

**Table 2.** Fidelity (LLM-as-judge) across corpus scale for CtxPack and raw stuffing. Compression ratio in parentheses.

| Source Tokens | CtxPack (Claude) | CtxPack (GPT-4o) | Raw (Claude) | Raw (GPT-4o) |
|---------------|-----------------|-----------------|-------------|-------------|
| 690 | **100%** (5.6x) | 88% (5.6x) | 96% (1x) | 84% (1x) |
| 1,202 | **100%** (7.0x) | 82% (7.0x) | 100% (1x) | 86% (1x) |
| 4,098 | **90%** (7.9x) | 66% (7.9x) | 100% (1x) | 86% (1x) |
| 15,244 | **97%** (8.2x) | 63% (8.2x) | 100% (1x) | 83% (1x) |
| 37,411 | **57%** (8.3x) | **63%** (8.3x) | 13% (1x) | 47% (1x) |

**Table 3.** LLM summary and naive truncation fidelity (LLM-as-judge) across scale.

| Source Tokens | LLM Sum (Claude) | LLM Sum (GPT-4o) | Naive (Claude) | Naive (GPT-4o) |
|---------------|-----------------|-----------------|---------------|---------------|
| 690 | 76% | 48% | 24% | 32% |
| 1,202 | 39% | 54% | 25% | 57% |
| 4,098 | 31% | 28% | 21% | 38% |
| 15,244 | 30% | 57% | 30% | 50% |
| 37,411 | — | — | 3% | 60% |

Three scaling characteristics emerge:

**1. Compression ratio is model-independent.** The same packer produces the same `.ctx` file regardless of which model will read it. Ratios improve from 5.6x at 690 tokens to 8.3x at 37K tokens, confirming that larger corpora contain more structural redundancy.

**2. Raw stuffing collapses at scale, and CtxPack surpasses it.** At 37K source tokens, raw stuffing drops to 13% on Claude and 47% on GPT-4o. CtxPack outperforms raw stuffing at 37K on *both* models: 57% vs. 13% on Claude (44pp advantage) and 63% vs. 47% on GPT-4o (16pp advantage). This confirms the lost-in-the-middle effect generalises across model families.

**3. LLM summarization degrades consistently.** Claude's LLM summary drops from 76% to 30% as the corpus grows. Free-form summarization cannot preserve the specific thresholds, identifiers, relationship constraints, and cross-entity rules that structured domain knowledge requires.

Note: The scaling curve is limited to Claude Sonnet 4.6 and GPT-4o. Cross-ecosystem scaling across all 12 models is future work. The golden set cross-ecosystem evaluation (Table 1) provides the portability evidence; the scaling curve demonstrates compression characteristics at larger corpus sizes.

### 5.4 The Disambiguation Finding (Q13)

The most striking individual result concerns question Q13: "What is the SKU identifier type for products?" Expected answer: "string, unique per merchant."

The raw YAML source contains:

```yaml
entity: PRODUCT
description: Product catalog entity, one per merchant
identifier:
  name: sku
  type: string
  unique: true
```

The scope qualifier "per merchant" appears only in the human-readable description field, not in the structured identifier definition. When the full YAML is provided as raw context, models read `unique: true` as a boolean flag and answer "string, unique" — omitting the scope. The CtxPack output makes the scope explicit:

```
IDENTIFIER:sku(string,unique-per-merchant)
```

Across the 12-model evaluation, 8 of 12 models correctly extract the scope qualifier from the L2 notation (Q13 correct). Four models — GPT-5.2, o3, Gemini 2.5 Pro, and Gemini 2.5 Flash Lite — answer "string" without the scope, missing the enriched qualifier even when it is explicit in the notation. This pattern suggests that scope extraction is a precision task where some models attend to the full parenthetical while others latch onto the primary type and stop. The disambiguation benefit is format-general: the information is present in the notation, and the majority of models extract it.

### 5.5 Grader Agreement

**Rule-based vs. LLM judge agreement.** Agreement between the two grading methods varies across models. On Anthropic models, agreement is near-perfect. On models with more concise answer styles (e.g., Gemini Flash Lite's "No." for Q25), the rule-based grader produces more false negatives, while the LLM judge correctly recognizes semantic equivalence. This validates our decision to use LLM-as-judge as the primary cross-ecosystem metric.

**Adversarial results.** All 12 models correctly reject both hallucination traps (Q21: return/refund policy, Q22: GDPR/CCPA) on both L2 and L1 inputs. The compressed format does not induce hallucination.

### 5.6 Cost Analysis

Table 4 presents per-query costs for the L2 representation across model pricing tiers, demonstrating the economic impact of 139-token context injection versus raw stuffing.

**Table 4.** Per-query input cost for golden set (L2 = 139 tokens vs. raw = 720 tokens). Selected model pricing.

| Model | Input Price ($/M tok) | Raw Cost | L2 Cost | Reduction |
|-------|----------------------|----------|---------|-----------|
| Claude Sonnet 4.5 | $3.00 | $0.00216 | $0.00042 | 81% |
| GPT-4o | $2.50 | $0.00180 | $0.00035 | 81% |
| Claude Haiku 4.5 | $0.80 | $0.00058 | $0.00011 | 81% |
| o4-mini | $1.10 | $0.00079 | $0.00015 | 81% |
| Gemini 2.5 Flash Lite | $0.075 | $0.00005 | $0.00001 | 81% |

At the cheapest tier (Gemini 2.5 Flash Lite at $0.075/M input tokens), L2 context injection costs $0.00001 per query — effectively free. Even at frontier pricing, the 81% cost reduction from 5.2x compression makes high-frequency context injection economically viable. These cost reductions reflect the golden set's 5.2x compression ratio; at production corpus sizes (8.3x compression at 37K tokens), reductions exceed 88%. For an organization making 10,000 queries per day against a 37K-token domain corpus compressed to ~4.5K tokens, annual savings range from $50,000 (frontier models) to near-zero marginal cost (Flash Lite tier).

### 5.7 Agent Context Compression

As a proof-of-concept beyond static domain knowledge, we evaluated CtxPack on a 30-step coding agent trace — a sequence of tool calls (file reads, grep searches, test runs, load tests, security scans) generated by an AI coding assistant exploring a FastAPI application.

**Results:** The packer compressed the 567-token raw trace into 485 tokens of structured `.ctx` output, merging observations across steps into 9 coherent entities (API-SERVER, AUTH, DATABASE, USER, ORDER, etc.) with field-level provenance (`SRC:step-N`). Mean pack latency was 0.71ms (10 iterations, p95: 1.06ms). The compression ratio (1.17x) is modest because agent traces are already information-dense, but the value lies in *structural reorganization*: scattered observations across 30 steps are unified into entity-centric sections with conflict-free field deduplication.

This demonstrates that the `.ctx` format extends beyond static knowledge packing to dynamic agent context — enabling compressed session state for long-running agents without losing provenance or introducing hallucinated connections between steps.

---

## 6. Cross-Ecosystem Portability

The 12-model evaluation across 3 ecosystems enables analysis of format portability at a resolution impossible with the original 2-model comparison.

### 6.1 Ecosystem-Level Summary

Aggregating L2 fidelity by ecosystem:

| Ecosystem | Models | L2 Range | L2 Mean |
|-----------|--------|----------|---------|
| Anthropic | 2 | 100% | 100% |
| OpenAI | 7 | 92–100% | 95.4% |
| Google | 3 | 92% | 92% |

No ecosystem falls below 92%. The format requires no adaptation, fine-tuning, or ecosystem-specific configuration to achieve high fidelity across all three major commercial LLM providers.

### 6.2 Per-Question Failure Analysis

Across the 12 L2 evaluation runs (one per model), failures concentrate on a small set of questions:

| Question | Difficulty | L2 Failures | Failure Models | Pattern |
|----------|-----------|:-----------:|----------------|---------|
| Q05 | Medium | 5/12 | GPT-4.1, GPT-4o, o3, Gemini Pro, Flash Lite | Threshold precision — models identify "Jaro-Winkler" but drop the ">0.92" qualifier |
| Q13 | Easy | 4/12 | GPT-5.2, o3, Gemini Pro, Flash Lite | Scope extraction — models answer "string" without "unique per merchant" |
| Q25 | Hard | 2/12 | GPT-4o, GPT-4o-mini | Cross-reference resolution — `BELONGS-TO:@ENTITY-ORDER(order_id,mandatory)` not parsed |
| Q23 | Hard | 2/12 | GPT-5.2, Gemini Flash | Completeness — models state "auto-deactivated" but omit "manual review by merchandising" |
| Q15 | Hard | 1/12 | Gemini Flash | Truncation — answer cut off mid-sentence |

**Key insight: failures are precision-based, not structural.** No model fails to understand the `.ctx` format itself. Every failure involves a model correctly parsing the relevant section but dropping a specific qualifier, threshold, or constraint detail. The information is present in the notation; the failures reflect attention allocation within dense notation, not inability to read the notation. This is analogous to how a human reader might skim past a parenthetical — the format is legible, but dense details require focused attention.

**Per-difficulty breakdown.** Where rule-based and difficulty data is available (Anthropic + OpenAI models), models show ceiling performance on easy (86–100%) and medium (91–100%) questions. The Hard tier discriminates more: Claude models and o4-mini achieve 100% on Hard, while GPT-5.2 and GPT-4o drop to 71%. This pattern is consistent with the precision-based failure hypothesis — Hard questions require multi-field synthesis and cross-entity inference, which is where attention to dense notation detail matters most.

### 6.3 L2 vs. L1: Compact Notation Is Not a Barrier

The paired L2/L1 evaluation protocol directly tests whether `.ctx` operator notation imposes a comprehension cost compared to natural-language prose.

| Comparison | Count | Models |
|------------|:-----:|--------|
| L2 = L1 | 8 | Sonnet 4.5, Haiku 4.5, o4-mini, GPT-5.2, o3, GPT-4o-mini, Gemini Pro, Flash Lite |
| L2 > L1 | 3 | GPT-5.2 Pro (+4pp), GPT-4o (+4pp), Gemini Flash (+8pp) |
| L1 > L2 | 1 | GPT-4.1 (−4pp) |

L2 meets or exceeds L1 on 11 of 12 models. On 3 models, L2 *strictly outperforms* L1 despite using 3x fewer tokens — likely because the reduced token count concentrates attention on the information-dense notation rather than diluting it across filler prose. The single L1 > L2 case (GPT-4.1, 4pp difference) falls within measured judge variance.

**Specific L2/L1 flip evidence.** Detailed per-question comparison across 6 Anthropic + OpenAI models reveals that L2 and L1 fail on *different* questions: across all 150 graded question-pairs, only 1 question has an L2-wins-over-L1 flip (GPT-4o on Q02: "What happens to churned customer data?" — L2 answers correctly, L1 says "not found in context"), and only 1 has an L1-wins-over-L2 flip (GPT-4.1 on Q05). Five cases fail on both formats (format-independent model limitation). This near-zero flip rate confirms that L2 and L1 are informationally equivalent — neither format consistently misleads models.

**Attention dilution evidence.** The GPT-4o Q02 flip is particularly instructive: the L1 representation spreads the same information across 417 tokens of prose, and GPT-4o responds "not found in context" — a false negative caused by attention dilution. The L2 representation encodes the same fact as `RETENTION:active→indefinite|churned→36→anonymise` in one dense line, which GPT-4o correctly parses. This is direct evidence that compact notation can improve retrieval by concentrating attention.

**Ensemble upper bound.** Because L2 and L1 failures are complementary, serving both formats and taking the best answer per question would recover fidelity: GPT-4.1 rises from 96% to 100% (ensemble recovers Q05). However, 3 models have format-independent failures (GPT-5.2 at 92%, GPT-4o at 92%, GPT-4o-mini at 96%) where neither format helps — these are genuine model limitations, not notation barriers.

**Implication:** Organizations can deploy L2 notation across all major model ecosystems without fidelity penalty. The 3x token reduction is a pure cost saving — the information loss from compact notation is zero or negative (i.e., a gain). For models where marginal fidelity matters, dual-format serving (L2 + L1) at 556 total tokens provides a modest but real gain over either format alone.

### 6.4 Implications for Deployment

The cross-ecosystem results have three practical implications:

1. **No vendor lock-in.** The same `.ctx` file achieves ≥92% fidelity on all tested models. Organizations can switch providers, use multiple models, or route by cost tier without reformatting their compressed context.

2. **Cost optimization on cheapest tiers.** The cheapest models tested (Haiku 4.5 at 100%, Gemini Flash Lite at 92%) perform at or near ceiling. For high-volume production use cases, L2 context can be served to the cheapest available model with negligible fidelity loss.

3. **Remaining failures are addressable.** The 5 failure questions (Q05, Q13, Q23, Q25, Q15) involve precision details — thresholds, scope qualifiers, completeness of multi-part answers. These could be addressed by notation adjustments (e.g., promoting threshold values to standalone fields rather than embedding them in parentheticals) without changing the overall format.

### 6.5 Reasoning Models: Extended Thinking Does Not Help

The evaluation includes two OpenAI reasoning models (o3, o4-mini) that use chain-of-thought reasoning before answering. A natural hypothesis is that reasoning models would better parse dense `.ctx` notation, since they can "think through" operator semantics before answering.

The results contradict this hypothesis:

| Model | Type | L2 Judge | L1 Judge | Elapsed (s) |
|-------|------|:--------:|:--------:|:-----------:|
| o4-mini | Reasoning | 100% | 100% | 72.7 |
| o3 | Reasoning | 92% | 92% | 78.9 |
| GPT-5.2 Pro | Standard | 100% | 96% | 201.0 |
| GPT-4.1 | Standard | 96% | 100% | — |

o3 (92%) underperforms the standard GPT-4.1 (96%) and GPT-5.2 Pro (100%) despite using extended reasoning. o3's failures are on Q05 (threshold precision), Q13 (scope extraction), and Q20 (regulatory detail omission) — the same precision-based failure patterns seen in standard models. Reasoning overhead does not help with structured context retrieval because the task is not reasoning-limited — it is attention-to-detail-limited.

o4-mini achieves 100% L2 fidelity with shorter elapsed time than o3, suggesting that focused attention allocation matters more than extended deliberation for `.ctx` comprehension. This has cost implications: o4-mini at $1.10/M input tokens achieves the same 100% fidelity as Claude Sonnet 4.5 at $3.00/M.

### 6.6 Rule-Based vs. LLM-Judge Grading Divergence

The dual-grading methodology reveals systematic divergence patterns that inform metric selection:

| Model | Rule Score | Judge Score | Gap | Pattern |
|-------|:----------:|:----------:|:---:|---------|
| o4-mini L2 | 92% | 100% | +8pp | Judge recognises "seven years" = "7 years", "locale/time-zone" = "customer locale" |
| Gemini 2.5 Pro L2 | 96% | 92% | −4pp | Judge stricter than rules on Q05 phrasing |
| Gemini 2.5 Flash L2 | 84% | 92% | +8pp | Judge recovers truncated-but-correct answers |

The rule-based grader is sensitive to surface-level formatting (numeric vs. spelled-out numbers, hyphenation) but misses semantic errors. The LLM-as-judge is more robust to paraphrase but occasionally grades leniently on partially correct answers. Neither is uniformly better; the dual-grading methodology surfaces these edge cases for manual review. We use LLM-as-judge as the primary cross-ecosystem metric because format sensitivity varies more across models than semantic accuracy.

---

## 7. Discussion

### 7.1 Why Structured Compression Beats Summarization

The LLM summary baseline's degradation reveals a fundamental limitation of free-form summarization for domain knowledge. On Claude, summaries drop from 76% to 30%; on GPT-4o, performance is inconsistent, ranging from 28% to 57% across scales. Three categories of information are systematically lost:

1. **Specific thresholds and parameters.** Both models' summaries dropped "5 minutes" (inventory staleness SLA), "0.92" (Jaro-Winkler threshold), and "Royal Mail" (UK address format). These values have low lexical salience but high operational importance.

2. **Cross-entity relationships.** Summaries failed to preserve that PAYMENT requires an ORDER (mandatory foreign key) and that ORDER belongs to CUSTOMER. Relationship chains that span entity boundaries are condensed into vague references or dropped entirely.

3. **Contradiction awareness.** At scale, LLM summaries smoothed over retention-policy conflicts rather than preserving them. CtxPack's explicit `⚠` warning markers ensure conflicts survive compression.

This suggests a general principle: **summarization optimizes for narrative coherence, while domain knowledge requires fact preservation.** The `.ctx` format's structured notation inherently preserves facts (as key-value pairs within entity sections) rather than narrativizing them.

### 7.2 The Lost-in-the-Middle Effect

The raw stuffing baseline's collapse at 37K tokens occurs on *both* scaling models — Claude to 13%, GPT-4o to 47% — providing cross-model evidence of the lost-in-the-middle phenomenon in a domain knowledge context. CtxPack's salience-ordered output places the most-referenced entities first and last, exploiting the known attention distribution of transformer models.

CtxPack at 37K compresses to 4,520 tokens. Claude's fidelity on this compressed output (57%) is down from 100% at smaller scales, suggesting that even 4,520 tokens may exhibit mild position-dependent attention effects. However, 57% substantially outperforms Claude's 13% on the full 37K raw context.

### 7.3 Limitations

**Golden-set-only cross-ecosystem data.** The 12-model cross-ecosystem evaluation uses only the golden set (690 source tokens, 25 questions). Cross-ecosystem scaling curve data (testing all 12 models at 1K–37K tokens) would strengthen generality claims and is planned for future work.

**Scaling curve limited to 2 models.** The scaling experiment (Table 2–3) uses Claude Sonnet 4.6 and GPT-4o only. While it demonstrates compression characteristics at scale, it does not capture how the 12-model fidelity distribution shifts at larger corpus sizes.

**Synthetic scaling corpora.** The scaling experiment uses synthetic entities generated from templates. While the entity patterns are realistic (drawn from 6 different industries), the corpora lack the organic inconsistencies, ambiguous phrasing, and unexpected structures of real-world documentation. We report the golden set (hand-authored) results separately for this reason.

**Model coverage.** Google models tested are from the Gemini 2.5 family; Gemini 3 Pro was not available via API at the time of evaluation. Open-source models (Llama, Mistral, DeepSeek) are not covered. The 12-model evaluation captures the three major commercial ecosystems but does not extend to self-hosted or open-weight models.

**Domain coverage.** All evaluation corpora use entity-relationship patterns typical of data platform documentation (YAML entities, business rules, regulatory policies). Highly narrative domains (legal opinions, strategy memos, research papers) would likely see lower compression ratios because they contain less structural redundancy.

**Scope inference risk.** The packer's scope inference (Section 4.2) enriches compressed output with information inferred from entity descriptions. If the inference is incorrect, the packer injects misinformation. The current implementation uses a conservative, fixed set of scope markers and can be disabled via `--strict` mode.

**LLM-as-judge variance.** Our primary metric (LLM-as-judge) shows ±4–12pp variance between independent runs on the same data. This is inherent to LLM-based evaluation and means that small fidelity differences (e.g., 92% vs. 96%) should not be over-interpreted.

### 7.4 Ethical Considerations

CtxPack compresses but does not generate content. It cannot introduce hallucinated facts that are not present in the source corpus (with the exception of the scope inference feature, which can be disabled). The conflict detection pipeline actively surfaces contradictions rather than resolving them, ensuring that domain experts remain aware of inconsistencies. The format is inspectable and auditable, unlike embedding-based compression approaches.

---

## 8. Future Work

**Cross-ecosystem scaling.** Extend the scaling curve experiment from 2 models to all 12, measuring how the fidelity distribution shifts at corpus sizes from 1K to 100K tokens. This would map the cross-ecosystem portability landscape at scale.

**Multi-file split and query-adaptive serving.** For corpora exceeding useful single-context budgets, we plan a MANIFEST-based multi-file split that indexes entities by keyword and serves only query-relevant sections, with always-include files for cross-cutting rules.

**RAG post-processing.** CtxPack as a layer between retriever and LLM: `pack_chunks(retrieved_chunks) → compressed .ctx context`. This would directly address chunk redundancy and lost-in-the-middle in RAG pipelines.

**Agent compression extension.** The proof-of-concept (Section 5.7) demonstrates feasibility; a production agent compression system would require incremental packing (compress as steps arrive), conflict resolution across steps, and integration with agent frameworks (LangChain, CrewAI, Claude Code).

**Learned salience scoring.** The current heuristic scorer can be augmented with a small learned model trained on click-through data or expert annotations to better predict which fields are most relevant to downstream queries.

**Perceptual model formalization.** The current notation is designed by intuition about transformer attention patterns. A rigorous study mapping `.ctx` operator tokens to attention weights would enable principled optimization of the notation itself — tuning the codec to the perceptual model, as MP3's psychoacoustic tables were tuned empirically.

---

## 9. Conclusion

CtxPack demonstrates that structured context compression, designed around how transformer models consume information rather than how humans write it, achieves broad cross-ecosystem portability: 12 models from 3 ecosystems (Anthropic, OpenAI, Google) achieve 92–100% fidelity on L2 notation at 139 tokens, with 4 models reaching 100%.

Four key findings generalise across all tested models:

1. **Compact notation is not a barrier.** L2 fidelity meets or exceeds L1 (compressed prose, 3x larger) on 11 of 12 models. The token reduction from L2 is a pure cost saving with zero or negative fidelity cost.

2. **Structured compression outperforms LLM summarization** at equivalent token budgets — by 24–67 percentage points on Claude and 6–40 points on GPT-4o — because summarization optimizes for narrative coherence while domain knowledge requires fact preservation.

3. **Raw context stuffing collapses at scale.** Both scaling models show severe fidelity loss at 37K tokens (Claude: 13%, GPT-4o: 47%), while CtxPack maintains 57% and 63% respectively — confirming the lost-in-the-middle effect and demonstrating that structured compression outperforms raw context at scale.

4. **Cross-ecosystem portability requires no adaptation.** The same 139-token `.ctx` file works on Claude, GPT, Gemini, and reasoning models without any model-specific formatting. Remaining failures (8% on 8 models) are precision-based — dropped thresholds and scope qualifiers — not structural parsing failures.

The counterintuitive result that compression can *improve* per-question fidelity — the packer's scope inference disambiguates implicit qualifiers that models misread in raw YAML (Section 5.4) — suggests that the gap between how domain knowledge is typically documented and how LLMs optimally consume it represents a significant, underexploited opportunity. A codec that bridges this gap is not merely a cost optimization — it is a quality improvement.

CtxPack, the `.ctx` format specification, the evaluation framework, cross-ecosystem results, and all raw experimental logs are available at https://github.com/cryogenic22/CTX.ai under AGPL-3.0.

---

## References

Chevalier, A., Wettig, A., Anirudh, R., & Chen, D. (2023). Adapting Language Models to Compress Contexts. *Proceedings of EMNLP 2023*.

Ge, T., Hu, J., Wang, X., Chen, S., & Wei, F. (2024). In-context Autoencoder for Context Compression in a Large Language Model. *Proceedings of ICLR 2024*.

Gloaguen, V., et al. (2026). Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents? *arXiv preprint*.

Jiang, H., Wu, Q., Lin, C., Yang, Y., & Qiu, L. (2023). LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Models. *Proceedings of EMNLP 2023*.

Jiang, H., Wu, Q., Luo, X., Li, D., Lin, C., Yang, Y., & Qiu, L. (2024). LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via Prompt Compression. *Proceedings of ACL 2024*.

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., ... & Kiela, D. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *Proceedings of NeurIPS 2020*.

Li, Y., Dong, B., Lin, C., & Guerin, F. (2023). Compressing Context to Enhance Inference Efficiency of Large Language Models. *Proceedings of EMNLP 2023*.

Liu, N. F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., & Liang, P. (2023). Lost in the Middle: How Language Models Use Long Contexts. *Transactions of the Association for Computational Linguistics*, 12, 157-173.

Mu, J., Li, X. L., & Goodman, N. (2023). Learning to Compress Prompts with Gist Tokens. *Proceedings of NeurIPS 2023*.

---

## Appendix A: Cross-Ecosystem Per-Question Results

**Table A1.** Per-question CtxPack L2 fidelity (LLM-as-judge) across all 12 models. ✓ = correct, ✗ = incorrect. Models abbreviated: Son = Claude Sonnet 4.5, Hai = Claude Haiku 4.5, 5.2P = GPT-5.2 Pro, o4m = o4-mini, 4.1 = GPT-4.1, 4om = GPT-4o-mini, 5.2 = GPT-5.2, o3 = o3, 4o = GPT-4o, GPr = Gemini 2.5 Pro, GFl = Gemini 2.5 Flash, GFL = Gemini 2.5 Flash Lite.

| ID | Diff | Son | Hai | 5.2P | o4m | 4.1 | 4om | 5.2 | o3 | 4o | GPr | GFl | GFL |
|----|------|:---:|:---:|:----:|:---:|:---:|:---:|:---:|:--:|:--:|:---:|:---:|:---:|
| Q01 | Easy | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q02 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q03 | Easy | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q04 | Easy | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q05 | Med | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Q06 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q07 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q08 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q09 | Easy | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q10 | Easy | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q11 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q12 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q13 | Easy | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ |
| Q14 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q15 | Hard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Q16 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q17 | Easy | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q18 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q19 | Med | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q20 | Hard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q21 | Hard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q22 | Hard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q23 | Hard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Q24 | Hard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Q25 | Hard | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| **Total** | | **25** | **25** | **25** | **25** | **24** | **24** | **23** | **23** | **23** | **23** | **23** | **23** |
| **Score** | | **100%** | **100%** | **100%** | **100%** | **96%** | **96%** | **92%** | **92%** | **92%** | **92%** | **92%** | **92%** |

Questions with no failures (20/25): Q01–Q04, Q06–Q12, Q14, Q16–Q22, Q24. These span all difficulty levels and question types, confirming robust cross-ecosystem comprehension of the `.ctx` format.

## Appendix B: Scaling Curve — Full Results

**Table B1.** Complete scaling results with all four baselines, both models, LLM-as-judge scores. Data from scaling curve experiment (v0.2.1, equalized prompts). The 690-token row represents an independent re-evaluation of the golden set; differences from Table 1 reflect LLM-as-judge variance between independent runs.

| Scale | Model | CtxPack | Raw | Naive | LLM Sum |
|-------|-------|---------|-----|-------|---------|
| 690 | Claude | 100% | 96% | 24% | 76% |
| 690 | GPT-4o | 88% | 84% | 32% | 48% |
| 1,202 | Claude | 100% | 100% | 25% | 39% |
| 1,202 | GPT-4o | 82% | 86% | 57% | 54% |
| 4,098 | Claude | 90% | 100% | 21% | 31% |
| 4,098 | GPT-4o | 66% | 86% | 38% | 28% |
| 15,244 | Claude | 97% | 100% | 30% | 30% |
| 15,244 | GPT-4o | 63% | 83% | 50% | 57% |
| 37,411 | Claude | 57% | 13% | 3% | — |
| 37,411 | GPT-4o | 63% | 47% | 60% | — |

Note: The scaling curve is limited to Claude Sonnet 4.6 and GPT-4o. Extending this to all 12 models is future work.

## Appendix C: Compression Example

**Input** (customer.yaml, 36 lines):
```yaml
entity: CUSTOMER
description: Core customer entity for the data platform
aliases:
  - client
  - buyer
golden_source: "CRM (Salesforce)"
identifier:
  name: customer_id
  type: UUID
  immutable: true
match_rules:
  - field: email
    method: exact match
    options:
      case-insensitive: true
      trim-whitespace: true
  - field: phone
    method: normalise
    options:
      format: "E.164"
  - field: name+address
    method: fuzzy match
    options:
      algorithm: "Jaro-Winkler>0.92"
pii:
  - name
  - email
  - phone
  - address
pii_classification: RESTRICTED
retention:
  active: indefinite
  churned:
    months: 36
    action: anonymise
```

**Output** (CtxPack L2, selected lines from CUSTOMER section):
```
±ENTITY-CUSTOMER ★GOLDEN-SOURCE:CRM-(Salesforce)
IDENTIFIER:customer_id(UUID,immutable)
MATCH-RULES:[email:exact-match(case-insensitive,trim-whitespace),
  phone:normalise(E.164),
  name+address:fuzzy-match(Jaro-Winkler>0.92)]
PII:name+email+phone+address
PII-CLASSIFICATION:RESTRICTED
RETENTION:active→indefinite|churned→36→anonymise
```

36 lines of YAML → 8 lines of `.ctx`. All entity relationships, field types, matching rules, PII classifications, and retention policies are preserved in the compressed notation.

## Appendix D: Raw Log Provenance

All experimental results are accompanied by timestamped raw logs containing full API request/response payloads for every question asked of every model. These logs are stored in:

- `ctxpack/benchmarks/golden_set/results/logs/` — Golden set eval logs (24 files, one per model × format)
- `ctxpack/benchmarks/scaling/results/logs/` — Scaling curve eval logs

Each log file is named `{timestamp}_{model}.json` and contains the `log_type`, `timestamp`, `model`, `provenance` metadata (tool version, platform), and the complete results payload including every question, every answer, and every grading decision. These logs constitute the primary evidence for all claims in this paper and are committed to the repository for independent verification.

## Appendix E: Latency Benchmarks

The packer was benchmarked on synthetic corpora of varying sizes (10 iterations each, Python 3.12, single-threaded).

**Table E1.** Packer latency by corpus size.

| Corpus Size | Source Tokens | Ctx Tokens | Pack Mean (ms) | Pack p95 (ms) | Serialize Mean (ms) | Throughput (tok/ms) |
|------------|--------------|------------|---------------|--------------|--------------------|--------------------|
| 1K chars | 1,202 | 278 | 6.73 | 8.38 | 0.06 | 178.6 |
| 5K chars | 4,098 | 882 | 26.27 | 40.31 | 0.10 | 156.0 |
| 10K chars | 7,807 | 1,659 | 70.48 | 110.22 | 0.34 | 110.8 |

Serialization is consistently sub-millisecond at all tested scales. Packing latency scales roughly linearly with corpus size, with throughput decreasing from 179 to 111 tokens/ms as entity resolution complexity grows with more entities. At 10K characters (~7.8K tokens), end-to-end packing completes in under 71ms — suitable for real-time applications.

## Appendix F: Agent Compression

A 30-step AI coding agent trace (tool calls: file reads, grep searches, test runs, load tests, security scans, dependency analysis) was compressed using the standard packer pipeline.

| Metric | Value |
|--------|-------|
| Steps | 30 |
| Raw tokens | 567 |
| Compressed tokens | 485 |
| Compression ratio | 1.17x |
| Entities merged | 9 |
| Conflicts detected | 0 |
| Pack latency (mean, 10 iter) | 0.71ms |
| Pack latency (p95) | 1.06ms |

The modest compression ratio (1.17x) reflects that agent traces are already information-dense. The value lies in structural reorganization: observations scattered across 30 chronological steps are unified into 9 entity-centric sections (API-SERVER, AUTH, DATABASE, USER, ORDER, REDIS, CI-CD, WEBHOOKS, MONITORING) with field-level provenance (`SRC:step-N`), conflict-free deduplication, and a DECISION section capturing architectural conclusions. This enables an agent to resume from compressed state without re-reading raw tool outputs.

## Appendix G: This Paper, Compressed

The following is the complete content of this whitepaper compressed into `.ctx` L2 notation by hand-applying the same principles the packer uses. This appendix serves as a live demonstration of the thesis: structured compression preserves information that narrative summarization drops.

```
§CTX v1.0 L2 DOMAIN:ctxpack-whitepaper
COMPRESSED:2026-02-24 SOURCE_TOKENS:~12000 AUTHOR:Kapil-Pant(Independent-Researcher)
LICENSE:AGPL-3.0 REPO:github.com/cryogenic22/CTX.ai

±CORE-THESIS
LLM-context→linear-cost($3-15/M-tokens)+quadratic-attention
Domain-knowledge(YAML,MD,JSON,rules,entities)→high-structural-redundancy
★INSIGHT:gap-between(human-written-density,transformer-consumed-density)→exploitable
ANALOGY:MP3→psychoacoustic-model|CtxPack→transformer-perceptual-model
CODEC-TYPE:deterministic,open-source,text-based,inspectable,versionable

±CTX-FORMAT ★FORMAL-SPEC:PEG-grammar(105-rules)
PRINCIPLES:[plain-text(UTF-8,diffable,git-friendly),multi-resolution,deterministic,format-aware(not-model-specific)]
CONFORMANCE-LEVELS:L1(compressed-prose,417tok)→L2(semantic-graph,139tok)→L3(abstract-gist)
OPERATORS:[§(header),±(section),→(flow/transition),|(alternative),+(conjunction),★(high-salience),⚠(warning),@(cross-ref),¬(negation)]
PARSER:recursive-descent,pure-Python(410-lines),zero-deps→frozen-dataclass-AST

±PACKER PIPELINE:Discover→Parse→EntityResolve→ConflictDetect→Score→Compress
SOURCES:YAML+MD+JSON|stdlib-only-parsers
RESOLVE:exact→case-insensitive→alias→singular/plural|field-dedup|provenance-tracked
CONFLICT:retention-policy|null-policy|type-mismatch|PII-classification→⚠warnings
SALIENCE:entity_score=(source_count×1.0+cross_refs×2.0+warnings×1.5)×golden_boost(1.5)
★SCOPE-INFERENCE:entity-description-pattern-match→enrich-identifiers|disable-via(--strict)
IMPL:pure-Python,zero-deps,2407-lines|CLI:ctxpack-pack|API:from-ctxpack.core.packer-import-pack

±CROSS-ECOSYSTEM-EVAL ★12-MODELS,3-ECOSYSTEMS
ANTHROPIC(2):Claude-Sonnet-4.5(100%),Haiku-4.5(100%)
OPENAI(7):GPT-5.2-Pro(100%),o4-mini(100%),GPT-4.1(96%),GPT-4o-mini(96%),GPT-5.2(92%),o3(92%),GPT-4o(92%)
GOOGLE(3):Gemini-2.5-Pro(92%),Flash(92%),Flash-Lite(92%)
★FLOOR:92%-across-ALL-ecosystems|4-models-at-100%
★L2≥L1:11/12-models|L2>L1-on-3(5.2-Pro,4o,Flash)|compact-notation=not-barrier
TOKENS:L2=139|L1=417|RAW=720
PROTOCOL:25-Qs×2-formats×12-models=24-runs|dual-grading(rule+judge)|temperature=0

±FAILURE-ANALYSIS(L2,12-models)
Q05(5/12):threshold-precision→models-drop->0.92-qualifier
Q13(4/12):scope-extraction→answer-"string"-without-"unique-per-merchant"
Q25(2/12):cross-ref-resolution→BELONGS-TO-not-parsed(4o,4o-mini)
Q23(2/12):completeness→missing-"manual-review-by-merchandising"
Q15(1/12):truncation→answer-cut-off(Flash)
★INSIGHT:failures=precision-based,¬structural|format-legible,dense-details-require-focused-attention

±SCALING(Claude-Sonnet-4.6+GPT-4o)
RATIOS:5.6x(690)→7.0x(1K)→7.9x(5K)→8.2x(15K)→8.3x(37K)
RAW-COLLAPSE-37K:Claude=13%,GPT-4o=47%|CtxPack=57%,63%→beats-raw-both-models
LLM-SUMMARY:degrades-76%→30%(Claude)|¬fact-preservation

±AGENT-COMPRESSION
TRACE:30-steps,567→485-tokens,ratio-1.17x,9-entities-merged,0.71ms
VALUE:structural-reorganization|chronological→entity-centric|provenance(SRC:step-N)

±COST
L2-PRICING:Haiku=$0.00011/q|Flash-Lite=$0.00001/q|Sonnet=$0.00042/q
REDUCTION:81%(5.2x-compression)|cheapest-tiers→effectively-free

±LIMITATIONS
GOLDEN-SET-ONLY-cross-ecosystem|scaling-curve=2-models|synthetic-corpora|single-domain
SCOPE-INFERENCE-RISK:disable-via(--strict)|JUDGE-VARIANCE:±4-12pp
```
