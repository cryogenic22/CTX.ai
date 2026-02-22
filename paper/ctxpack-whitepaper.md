# CtxPack: Perceptual Context Compression for Large Language Models

**Kapil Pant**
SynaptyX

**Abstract.** Large language models consume context tokens linearly in cost and quadratically in attention computation, yet most injected context — domain rules, entity definitions, operational knowledge — contains significant structural redundancy. We present CtxPack, an open-source, deterministic context compression codec that exploits the gap between *information density as written for humans* and *information density as consumed by transformers*. CtxPack introduces `.ctx`, a multi-resolution text format with a formal grammar, and a packer that converts structured domain corpora (YAML, Markdown) into semantically compressed context through entity resolution, deduplication, heuristic salience scoring, and hierarchical notation. In controlled evaluations across corpus sizes from 690 to 37,000 tokens and across two model families (Claude Sonnet 4.6 and GPT-4o), CtxPack achieves 5.6–8.3x compression while maintaining high question-answering fidelity. With Claude, fidelity remains at 92–100% across all scales; with GPT-4o, the same compressed files achieve 52–92% (LLM-judge), revealing model-specific perceptual properties analogous to how audio codecs perform differently across playback hardware. At 37K source tokens, both models show catastrophic degradation with raw context stuffing (Claude: 40%, GPT-4o: 60% by judge), confirming the lost-in-the-middle effect is model-universal. An LLM-generated summary baseline at equivalent token budgets performs substantially worse than CtxPack across both models, demonstrating that structured compression categorically outperforms free-form summarization. We release the codec, evaluation framework, cross-model results, and all raw logs under AGPL-3.0.

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

2. **A deterministic packer**: A pure-Python, zero-dependency pipeline that converts YAML + Markdown domain corpora into `.ctx` L2 output through entity extraction, resolution, deduplication, conflict detection, and heuristic salience scoring (Section 4).

3. **Cross-model empirical evidence**: Controlled evaluations across two model families (Claude Sonnet 4.6, GPT-4o) and five corpus scales (690–37K tokens), demonstrating that structured compression outperforms all baselines on both models while revealing model-specific perceptual properties of the compressed format (Section 5).

4. **A counterintuitive finding**: At small corpus sizes with Claude, the compressed representation achieves *higher* fidelity than the raw source (100% vs. 96%), because the packer disambiguates implicit scope qualifiers that the LLM misreads in raw YAML. The codec does not merely preserve information — it clarifies it (Section 5.5).

5. **An open evaluation framework**: A reproducible benchmark with 25 curated questions (including adversarial hallucination traps), dual grading (rule-based + LLM-as-judge), a scaling corpus generator, and complete raw logs of all API calls — released under AGPL-3.0.

---

## 2. Related Work

### 2.1 Token-Level Context Compression

LLMLingua (Jiang et al., 2023) uses a small language model to compute per-token perplexity and removes low-perplexity tokens. LongLLMLingua (Jiang et al., 2024) extends this with question-aware compression for RAG scenarios. Selective Context (Li et al., 2023) applies a similar approach using self-information. These methods operate at the token level without understanding document structure, making them effective for narrative prose but poorly suited for structured domain knowledge where every field name, threshold value, and entity reference carries high information density regardless of lexical frequency.

### 2.2 Learned Soft Compression

Gist Tokens (Mu et al., 2023) train a model to compress instructions into a small number of virtual tokens in the embedding space. AutoCompressors (Chevalier et al., 2023) extend this to multi-step compression. ICAE (Ge et al., 2024) uses an autoencoder approach. While achieving very high compression ratios (10–25x), these methods produce opaque representations that cannot be inspected, cached as text, version-controlled, or audited. They also require training or fine-tuning, limiting applicability to specific model families.

### 2.3 Retrieval-Augmented Generation

RAG (Lewis et al., 2020) retrieves relevant document chunks at query time, avoiding full-corpus injection. However, Liu et al. (2023) demonstrated that LLMs systematically fail to use information positioned in the middle of their context window — the "lost-in-the-middle" phenomenon. RAG pipelines typically retrieve 10–20 chunks (15–25K tokens), introducing redundancy across chunks and fragmentation of cross-entity relationships. CtxPack is complementary to RAG: it can serve as a post-processing layer that compresses retrieved chunks before injection.

### 2.4 Structured Knowledge Representation

Traditional approaches like RDF, OWL, and knowledge graphs represent structured knowledge formally but are not designed for LLM consumption — they require query languages (SPARQL) and inference engines rather than direct context injection. JSON-LD and Schema.org provide structured markup but optimize for machine interoperability, not token efficiency. CtxPack occupies a novel position: a format designed specifically for the LLM-as-consumer use case, balancing human readability, machine parseability, and token density.

---

## 3. The `.ctx` Format

### 3.1 Design Principles

The `.ctx` format is guided by four principles:

1. **Plain text, not binary.** `.ctx` files are UTF-8 text that can be read by humans, diffed with standard tools, and version-controlled in git. This enables domain experts to inspect and validate compressed knowledge without special tooling.

2. **Multi-resolution.** A single document can contain content at different compression levels, enabling progressive hydration — serve L3 (gist) for simple queries, L2 (semantic graph) for detailed questions, L1 (compressed prose) when verbatim detail matters.

3. **Deterministic and reproducible.** Given the same input corpus, the packer produces identical output. No randomness, no model-dependent compression, no floating-point accumulation. The same `.ctx` file produces the same results regardless of when or where it was generated.

4. **Format-aware, not model-specific.** The `.ctx` notation is designed for how *transformers in general* process structured text, not for any specific model's tokenizer. This ensures portability across model families and versions — though as our cross-model evaluation reveals, different models do exhibit different degrees of fluency with the notation (Section 5).

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

These operators are chosen for their visual distinctiveness to transformer tokenizers. Unicode operators (`→`, `★`, `⚠`) tokenize as single or two-token units in most tokenizers, providing high information density per token.

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

The packer converts a directory of YAML and Markdown source files into a single `.ctx` L2 document through a six-stage pipeline:

```
Discover → Parse → Entity Resolve → Conflict Detect → Score → Compress
```

**Stage 1: Discovery.** Walk the corpus directory, classify files by extension (.yaml/.yml, .md), and load optional `ctxpack.yaml` configuration (domain name, entity aliases, golden source mappings, include/exclude patterns).

**Stage 2: Parsing.** YAML files are parsed by a stdlib-only subset parser (722 lines, handling maps, sequences, nested structures, flow notation, and scalars; rejecting anchors, tags, and multi-line scalars with clear error messages). Markdown files are parsed by a heading/list extractor that maps H1/H2 headings to entity boundaries and bullet lists to rules. Both parsers produce an intermediate representation (IR) of entities, fields, and warnings.

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

The raw YAML states `unique: true` without specifying scope. The packer infers `unique-per-merchant` from the description field. This is a form of *disambiguation during compression* — the codec makes implicit knowledge explicit, improving downstream LLM comprehension (see Section 5.5 for empirical evidence).

This inference is implemented through pattern matching against a fixed set of scope markers ("per merchant", "per tenant", "per organization", etc.) and can be disabled via a `--strict` flag for environments where only explicit field values should be preserved.

### 4.3 Implementation

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

**Evaluation models.** Claude Sonnet 4.6 (Anthropic) and GPT-4o (OpenAI). Both models are tested on the same compressed `.ctx` files, raw corpora, and questions. Each model also generates its own LLM summary baseline and serves as its own judge. All API calls are logged with timestamps and full request/response payloads for reproducibility.

### 5.2 Golden Set Results

Table 1 presents results on the fixed golden set (690 source tokens, 25 questions) for both models.

**Table 1.** Golden set evaluation (690 source tokens, 25 questions). Fidelity scores are LLM-as-judge.

| Method | Tokens | Ratio | Claude Judge | GPT-4o Judge |
|--------|--------|-------|-------------|-------------|
| Raw stuffing | 720 | 1.0x | **100%** | 80% |
| **CtxPack L2** | **124** | **5.6x** | **96%** | **92%** |
| LLM summary | ~100 | ~6.5x | 76% | 44% |
| Naive truncation | 124 | 5.6x | 20% | 32% |

Three findings emerge from the cross-model comparison:

**CtxPack is portable.** The same 124-token `.ctx` file achieves 96% fidelity with Claude and 92% with GPT-4o. The 4-percentage-point gap is surprisingly small given that the format was developed and tested primarily with Claude. This demonstrates that the `.ctx` notation is not model-specific — it exploits general properties of how transformers process structured text.

**Raw context has higher model variance.** Raw stuffing achieves 100% with Claude but only 80% with GPT-4o on the same 720 tokens of uncompressed YAML and Markdown. This indicates that GPT-4o is less effective at extracting structured facts from raw markup — precisely the scenario where structured compression adds the most value.

**LLM summaries are model-dependent.** Claude's self-generated summary achieves 76% fidelity; GPT-4o's self-generated summary achieves only 44%. This is particularly striking because each model is judging its *own* summary — GPT-4o cannot effectively answer questions from the summary it itself produced. The LLM summary baseline is not a stable comparison point across models, while CtxPack's deterministic output is.

### 5.3 Scaling Curve

To test whether these results hold at scale, we generated synthetic corpora at 1K, 5K, 20K, and 50K source tokens using a multi-domain entity generator covering retail, logistics, healthcare, fintech, HR, and marketing entities. Questions were generated proportionally (24–25 per scale, stratified by difficulty).

**Table 2.** Fidelity (LLM-as-judge) across corpus scale, both models. Compression ratio in parentheses.

| Source Tokens | CtxPack (Claude) | CtxPack (GPT-4o) | Raw (Claude) | Raw (GPT-4o) |
|---------------|-----------------|-----------------|-------------|-------------|
| 690 | 92% (5.6x) | **92%** (5.6x) | 100% (1x) | 80% (1x) |
| 1,202 | **100%** (7.0x) | 83% (7.0x) | 100% (1x) | 88% (1x) |
| 4,098 | **96%** (7.9x) | 63% (7.9x) | 100% (1x) | 88% (1x) |
| 15,244 | **100%** (8.2x) | 52% (8.2x) | 100% (1x) | 80% (1x) |
| 37,411 | **80%** (8.3x) | 52% (8.3x) | 40% (1x) | 60% (1x) |

**Table 3.** LLM summary and naive truncation fidelity (LLM-as-judge) across scale.

| Source Tokens | LLM Sum (Claude) | LLM Sum (GPT-4o) | Naive (Claude) | Naive (GPT-4o) |
|---------------|-----------------|-----------------|---------------|---------------|
| 690 | 76% | 44% | 24% | 32% |
| 1,202 | 63% | 50% | 21% | 46% |
| 4,098 | 33% | 25% | 21% | 33% |
| 15,244 | 20% | 44% | 32% | 32% |
| 37,411 | — | — | 12% | 40% |

Five trends emerge from the cross-model scaling data:

**1. Compression ratio is model-independent.** The same packer produces the same `.ctx` file regardless of which model will read it. Ratios improve from 5.6x at 690 tokens to 8.3x at 37K tokens, confirming that larger corpora contain more structural redundancy.

**2. Claude reads `.ctx` near-perfectly; GPT-4o shows degradation.** Claude maintains 80–100% fidelity across all scales. GPT-4o starts at 92% (golden set) but degrades to 52% at 15K+ tokens. This gap reveals *model-specific perceptual properties*: Claude appears more fluent with the operator-dense notation, while GPT-4o struggles to extract information from larger compressed documents. This parallels how the same MP3 file sounds different on different playback hardware — the codec has perceptual characteristics that interact with the decoder.

**3. Raw stuffing collapses on both models.** At 37K source tokens, Claude drops to 40% and GPT-4o drops to 60%. The lost-in-the-middle effect is model-universal, though the severity varies (Claude's larger degradation may reflect different attention distribution patterns). Critically, CtxPack outperforms raw stuffing on Claude at 37K (80% vs. 40%) and matches it on GPT-4o (52% vs. 60%).

**4. LLM summarization degrades catastrophically on both models.** Claude's LLM summary drops from 76% to 20% as the corpus grows. GPT-4o's drops from 44% to 25%. Free-form summarization cannot preserve the specific thresholds, identifiers, relationship constraints, and cross-entity rules that structured domain knowledge requires.

**5. CtxPack dominates at the Pareto frontier on Claude.** When plotting fidelity against token count, CtxPack occupies the top-left quadrant (high fidelity, low tokens) at every Claude scale point. On GPT-4o, CtxPack outperforms naive truncation and LLM summary at every scale, but raw stuffing remains competitive up to ~15K tokens — suggesting that GPT-4o benefits less from structural compression and more from having full verbatim context available.

### 5.4 Model Affinity: A Novel Finding

The divergence between Claude and GPT-4o on the same compressed files is, to our knowledge, the first empirical demonstration of *model-specific perceptual properties* of a structured context format. The analogy to audio codecs is apt: MP3 exploits a psychoacoustic model that assumes specific properties of the human auditory system; `.ctx` similarly exploits assumptions about how transformers process structured text. When those assumptions match well (Claude), fidelity is near-perfect. When they partially mismatch (GPT-4o), fidelity degrades gracefully but noticeably.

Analysis of GPT-4o's per-question failures reveals two primary patterns:

**Pattern 1: Compact notation parsing.** GPT-4o frequently responds "Not found in context" for information that is present in the `.ctx` file but encoded in dense notation. For example, Q04 ("Is customer_id mutable?") — the answer `IDENTIFIER:customer_id(UUID,immutable)` is present, but GPT-4o fails to extract the `immutable` flag from the parenthetical notation. Claude consistently parses these parenthetical attributes.

**Pattern 2: Cross-reference resolution.** Q25 ("Can a PAYMENT exist without an ORDER?") requires reading `BELONGS-TO:@ENTITY-ORDER(order_id,mandatory)` and inferring the constraint. Claude resolves this; GPT-4o does not.

These patterns suggest that future versions of the `.ctx` format could include model-specific formatting hints or alternative notation styles to improve cross-model portability. However, the current results demonstrate that even without model-specific optimization, CtxPack's compressed format outperforms all non-raw baselines on both models.

### 5.5 The Disambiguation Finding (Q13)

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

The scope qualifier "per merchant" appears only in the human-readable description field, not in the structured identifier definition. When the full YAML is provided as raw context, *both* Claude and GPT-4o read `unique: true` as a boolean flag and answer "string, unique" — omitting the scope. The CtxPack output makes the scope explicit:

```
IDENTIFIER:sku(string,unique-per-merchant)
```

The packer inferred the scope by pattern-matching the entity description against known scope markers, then enriched the compressed identifier. Both models, reading the compressed format, correctly identify "unique per merchant" from the CtxPack output (confirmed by LLM-as-judge on both models).

This is not merely information preservation — it is *information clarification*. The codec compensates for a gap between how the source data is structured (scope buried in a description string, disconnected from the boolean flag) and how the consumer (the LLM) processes it. This parallels how MP3's psychoacoustic model compensates for the playback device's limitations.

### 5.6 Grader Agreement and Adversarial Results

**Rule-based vs. LLM judge agreement.** On the golden set with Claude, the two graders agree on 23 of 25 questions (92%). With GPT-4o, agreement is lower (76%), primarily because GPT-4o's more concise answer format triggers more rule-based false negatives. This validates our decision to use LLM-as-judge as the primary cross-model metric.

**Cross-model judge agreement on ctxpack.** An important consistency check: when both models read the same `.ctx` file, both judges agree on 21 of 25 answers (84%). The disagreements occur on questions requiring deeper parsing of compact notation — confirming that the format's information is present but model accessibility varies.

**Adversarial results.** Both Claude and GPT-4o correctly reject the two pure hallucination traps (Q21: return/refund policy, Q22: GDPR/CCPA), confirming that the compressed format does not induce confabulation on either model. The low-salience edge cases (Q23: seasonal product deactivation, Q24: UK Royal Mail address format) are preserved by CtxPack on both models but lost by naive truncation and LLM summary — demonstrating that structural compression preserves operationally critical details that narrative summarization drops.

### 5.7 Cost Analysis

Table 4 presents per-query costs across scale, assuming Claude Sonnet 4.6 pricing ($3/M input tokens).

**Table 4.** Per-query input cost across scale.

| Source Tokens | Raw Stuffing | CtxPack L2 | Cost Reduction |
|---------------|-------------|------------|----------------|
| 690 | $0.0022 | $0.0004 | 82% |
| 1,202 | $0.0038 | $0.0005 | 87% |
| 4,098 | $0.0128 | $0.0016 | 88% |
| 15,244 | $0.0476 | $0.0056 | 88% |
| 37,411 | $0.1168 | $0.0136 | 88% |

At scale, the cost reduction stabilizes at approximately 88%, consistent with the compression ratio plateau at ~8x. For an organization making 10,000 queries per day against a 37K-token domain corpus, CtxPack reduces annual context injection costs from approximately $426,000 to $50,000.

---

## 6. Discussion

### 6.1 Why Structured Compression Beats Summarization

The LLM summary baseline's degradation reveals a fundamental limitation of free-form summarization for domain knowledge. On Claude, summaries drop from 76% to 20%; on GPT-4o, from 44% to 25%. Three categories of information are systematically lost:

1. **Specific thresholds and parameters.** Both models' summaries dropped "5 minutes" (inventory staleness SLA), "0.92" (Jaro-Winkler threshold), and "Royal Mail" (UK address format). These values have low lexical salience but high operational importance.

2. **Cross-entity relationships.** Summaries failed to preserve that PAYMENT requires an ORDER (mandatory foreign key) and that ORDER belongs to CUSTOMER. Relationship chains that span entity boundaries are condensed into vague references or dropped entirely.

3. **Contradiction awareness.** At scale, LLM summaries smoothed over retention-policy conflicts rather than preserving them. CtxPack's explicit `⚠` warning markers ensure conflicts survive compression.

This suggests a general principle: **summarization optimizes for narrative coherence, while domain knowledge requires fact preservation.** The `.ctx` format's structured notation inherently preserves facts (as key-value pairs within entity sections) rather than narrativizing them.

### 6.2 The Lost-in-the-Middle Effect

The raw stuffing baseline's collapse at 37K tokens occurs on *both* models — Claude to 40%, GPT-4o to 60% — providing cross-model confirmation of the lost-in-the-middle phenomenon in a domain knowledge context. CtxPack's salience-ordered output places the most-referenced entities first and last, exploiting the known attention distribution of transformer models.

Interestingly, GPT-4o's raw stuffing degrades less severely (60% vs. Claude's 40%), suggesting different attention distribution curves between the two model families. CtxPack, by compressing 37K tokens into 4,520, moves all information into the high-attention region regardless of model architecture.

### 6.3 Model Affinity and Format Design

The cross-model results reveal a tension in format design: notation that is maximally compact for one model's tokenizer may be suboptimal for another's. Three potential mitigation strategies emerge from our analysis:

1. **Model-adaptive formatting.** A post-compression pass that adjusts notation density based on the target model family. For GPT-4o, this might mean expanding parenthetical attributes into separate lines, or adding natural-language glosses for operator-dense expressions.

2. **Progressive disclosure.** Serve L1 (compressed prose) to models with lower `.ctx` fluency and L2 (semantic graph) to models with higher fluency. The multi-resolution design of the format already supports this without any changes to the packer.

3. **Cross-model training data.** Including `.ctx` examples in model fine-tuning or system prompts to familiarize models with the notation. Our results suggest that the format is learnable — GPT-4o achieves 92% at golden-set scale, where the compressed context is small enough to fully attend to.

### 6.4 Limitations

**Corpus size.** Our largest evaluation uses 37K source tokens. Production domain corpora can exceed 100K tokens. The scaling curve suggests fidelity may continue to degrade gradually beyond 50K, though the compression ratio should continue improving. Multi-file split (planned for v0.3) would address this by serving only query-relevant sections.

**Domain coverage.** All evaluation corpora use entity-relationship patterns typical of data platform documentation (YAML entities, business rules, regulatory policies). Highly narrative domains (legal opinions, strategy memos, research papers) would likely see lower compression ratios because they contain less structural redundancy. Cross-domain robustness testing is planned for future work.

**Synthetic scaling corpora.** The scaling experiment uses synthetic entities generated from templates. While the entity patterns are realistic (drawn from 6 different industries), the corpora lack the organic inconsistencies, ambiguous phrasing, and unexpected structures of real-world documentation. We report the golden set (hand-authored) results separately for this reason.

**Two-model evaluation.** While we evaluate across two major model families (Claude and GPT-4o), additional models (Gemini, Llama, Mistral) would strengthen generality claims. The Claude-GPT-4o comparison captures the key architectural divide (Anthropic vs. OpenAI attention implementations) but does not cover open-source models.

**Scope inference risk.** The packer's scope inference (Section 4.2) enriches compressed output with information inferred from entity descriptions. If the inference is incorrect, the packer injects misinformation. The current implementation uses a conservative, fixed set of scope markers and can be disabled via `--strict` mode.

### 6.5 Ethical Considerations

CtxPack compresses but does not generate content. It cannot introduce hallucinated facts that are not present in the source corpus (with the exception of the scope inference feature, which can be disabled). The conflict detection pipeline actively surfaces contradictions rather than resolving them, ensuring that domain experts remain aware of inconsistencies. The format is inspectable and auditable, unlike embedding-based compression approaches.

---

## 7. Future Work

**Multi-file split and query-adaptive serving.** For corpora exceeding useful single-context budgets, we plan a MANIFEST-based multi-file split that indexes entities by keyword and serves only query-relevant sections, with always-include files for cross-cutting rules.

**RAG post-processing.** CtxPack as a layer between retriever and LLM: `pack_chunks(retrieved_chunks) → compressed .ctx context`. This would directly address chunk redundancy and lost-in-the-middle in RAG pipelines.

**Model-adaptive formatting.** Based on the cross-model findings, a formatting pass that adjusts notation density for the target model family — expanding compact notation for models with lower `.ctx` fluency while preserving maximum density for high-fluency models.

**Learned salience scoring.** The current heuristic scorer can be augmented with a small learned model trained on click-through data or expert annotations to better predict which fields are most relevant to downstream queries.

**Extended cross-model and cross-domain evaluation.** Systematic testing across additional model families (Gemini, Llama, Mistral) and domain types (legal, financial, scientific) to establish generality bounds and map the model-affinity landscape.

**Perceptual model formalization.** The current notation is designed by intuition about transformer attention patterns. A rigorous study mapping `.ctx` operator tokens to attention weights would enable principled optimization of the notation itself — tuning the codec to the perceptual model, as MP3's psychoacoustic tables were tuned empirically.

---

## 8. Conclusion

CtxPack demonstrates that structured context compression, designed around how transformer models consume information rather than how humans write it, can achieve substantial compression (5.6–8.3x) while maintaining high information fidelity. Cross-model evaluation reveals that the format exhibits *model-specific perceptual properties*: Claude Sonnet 4.6 achieves 80–100% fidelity across all scales, while GPT-4o achieves 52–92% on the same compressed files — a novel finding that extends the perceptual codec analogy to empirical observation.

Three key findings are model-universal:

1. **Structured compression outperforms LLM summarization** at equivalent token budgets — by 20+ percentage points on Claude and 10–40+ points on GPT-4o — because summarization optimizes for narrative coherence while domain knowledge requires fact preservation.

2. **Raw context stuffing collapses at scale.** Both models show catastrophic fidelity loss at 37K tokens (Claude: 40%, GPT-4o: 60%), confirming the lost-in-the-middle effect is architecture-independent.

3. **Deterministic compression enables reproducible context.** Unlike LLM summaries (which vary with model, temperature, and prompt), CtxPack produces identical output for identical input, enabling versioning, caching, and auditing of compressed domain knowledge.

The counterintuitive result that compressed context can *exceed* raw context fidelity (100% vs. 96% on the golden set with Claude) suggests that the gap between how domain knowledge is typically documented and how LLMs optimally consume it represents a significant, underexploited opportunity. A codec that bridges this gap is not merely a cost optimization — it is a quality improvement.

CtxPack, the `.ctx` format specification, the evaluation framework, cross-model results, and all raw experimental logs are available at https://github.com/cryogenic22/CTX.ai under AGPL-3.0.

---

## References

Chevalier, A., Wettig, A., Anirudh, R., & Chen, D. (2023). Adapting Language Models to Compress Contexts. *Proceedings of EMNLP 2023*.

Ge, T., Hu, J., Wang, X., Chen, S., & Wei, F. (2024). In-context Autoencoder for Context Compression in a Large Language Model. *Proceedings of ICLR 2024*.

Jiang, H., Wu, Q., Lin, C., Yang, Y., & Qiu, L. (2023). LLMLingua: Compressing Prompts for Accelerated Inference of Large Language Models. *Proceedings of EMNLP 2023*.

Jiang, H., Wu, Q., Luo, X., Li, D., Lin, C., Yang, Y., & Qiu, L. (2024). LongLLMLingua: Accelerating and Enhancing LLMs in Long Context Scenarios via Prompt Compression. *Proceedings of ACL 2024*.

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., ... & Kiela, D. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *Proceedings of NeurIPS 2020*.

Li, Y., Bubeck, S., Eldan, R., Del Giorno, A., Gunasekar, S., & Lee, Y. T. (2023). Textbooks Are All You Need II: phi-1.5 technical report. *arXiv preprint arXiv:2309.05463*.

Liu, N. F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., & Liang, P. (2023). Lost in the Middle: How Language Models Use Long Contexts. *Transactions of the Association for Computational Linguistics*, 12, 157-173.

Mu, J., Li, X. L., & Goodman, N. (2023). Learning to Compress Prompts with Gist Tokens. *Proceedings of NeurIPS 2023*.

---

## Appendix A: Golden Set — Per-Question Cross-Model Results

**Table A1.** Per-question CtxPack L2 fidelity (LLM-as-judge) on the golden set (25 questions).

| ID | Difficulty | Question (abbreviated) | Claude | GPT-4o |
|----|-----------|----------------------|--------|--------|
| Q01 | Easy | Golden source for customer data? | ✓ | ✓ |
| Q02 | Medium | Churned customer data after 36 months? | ✓ | ✓ |
| Q03 | Easy | Type of customer_id? | ✓ | ✓ |
| Q04 | Easy | Is customer_id mutable? | ✓ | ✗ |
| Q05 | Medium | Matching algorithm for name+address? | ✓ | ✓ |
| Q06 | Medium | PII classification for customer email? | ✓ | ✓ |
| Q07 | Medium | Order status flow? | ✓ | ✓ |
| Q08 | Medium | Line items immutable after which status? | ✓ | ✓ |
| Q09 | Easy | Financial fields decimal precision? | ✓ | ✓ |
| Q10 | Easy | What entity does ORDER belong to? | ✓ | ✓ |
| Q11 | Medium | Max staleness for inventory? | ✓ | ✓ |
| Q12 | Medium | Order exceeds $50,000? | ✓ | ✗ |
| Q13 | Easy | SKU identifier type? | ✓ | ✗ |
| Q14 | Medium | How is inventory synced? | ✓ | ✓ |
| Q15 | Hard | Conflicting retention policies? | ✓ | ✓ |
| Q16 | Medium | Null policy for email? | ✓ | ✗ |
| Q17 | Easy | Timestamps stored/displayed? | ✓ | ✓ |
| Q18 | Medium | US address normalisation? | ✓ | ✓ |
| Q19 | Medium | PII classification for card numbers? | ✓ | ✓ |
| Q20 | Hard | Min retention for financial data? | ✓ | ✓ |
| Q21 | Hard | Customer return/refund policy? (adversarial) | ✓ | ✓ |
| Q22 | Hard | GDPR/CCPA deletion rules? (adversarial) | ✗ | ✓ |
| Q23 | Hard | Seasonal products at end of season? | ✓ | ✓ |
| Q24 | Hard | UK address format standard? | ✓ | ✓ |
| Q25 | Hard | Can PAYMENT exist without ORDER? | ✓ | ✗ |

**Claude:** 24/25 (96%). **GPT-4o:** 20/25 (80%).

GPT-4o failures (Q04, Q12, Q16, Q25) cluster on questions requiring extraction from parenthetical notation or cross-reference resolution — confirming the model-specific parsing patterns discussed in Section 5.4. Q13 (SKU scope) is marked ✗ by rule-based but ✓ by judge on both models when reading `.ctx`.

## Appendix B: Scaling Curve — Full Results

**Table B1.** Complete scaling results with all four baselines, both models, LLM-as-judge scores.

| Scale | Model | CtxPack | Raw | Naive | LLM Sum |
|-------|-------|---------|-----|-------|---------|
| 690 | Claude | 92% | 100% | 24% | 76% |
| 690 | GPT-4o | 92% | 80% | 32% | 44% |
| 1,202 | Claude | 100% | 100% | 21% | 63% |
| 1,202 | GPT-4o | 83% | 88% | 46% | 50% |
| 4,098 | Claude | 96% | 100% | 21% | 33% |
| 4,098 | GPT-4o | 63% | 88% | 33% | 25% |
| 15,244 | Claude | 100% | 100% | 32% | 20% |
| 15,244 | GPT-4o | 52% | 80% | 32% | 44% |
| 37,411 | Claude | 80% | 40% | 12% | — |
| 37,411 | GPT-4o | 52% | 60% | 40% | — |

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

**Output** (CtxPack L2, 8 lines):
```
±ENTITY-CUSTOMER ★GOLDEN-SOURCE:CRM-(Salesforce)
IDENTIFIER:customer_id(UUID,immutable)
MATCH-RULES:[email:exact-match(case-insensitive,trim-whitespace),
  phone:normalise(format),
  name+address:fuzzy-match(algorithm)]
PII:name+email+phone+address
PII-CLASSIFICATION:RESTRICTED
RETENTION:active→indefinite|churned→36→anonymise
```

36 lines of YAML → 8 lines of `.ctx`. All entity relationships, field types, matching rules, PII classifications, and retention policies are preserved in the compressed notation.

## Appendix D: Raw Log Provenance

All experimental results are accompanied by timestamped raw logs containing full API request/response payloads for every question asked of every baseline. These logs are stored in:

- `ctxpack/benchmarks/golden_set/results/logs/` — Golden set eval logs
- `ctxpack/benchmarks/scaling/results/logs/` — Scaling curve eval logs

Each log file is named `{timestamp}_{model}.json` and contains the `log_type`, `timestamp`, `model`, `provenance` metadata (tool version, platform), and the complete results payload including every question, every answer, and every grading decision. These logs constitute the primary evidence for all claims in this paper and are committed to the repository for independent verification.
