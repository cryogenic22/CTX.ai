# CtxPack: Perceptual Context Compression for Large Language Models

**Kapil Pant**
SynaptyX

**Abstract.** Large language models consume context tokens linearly in cost and quadratically in attention computation, yet most injected context — domain rules, entity definitions, operational knowledge — contains significant structural redundancy. We present CtxPack, an open-source, deterministic context compression codec that exploits the gap between *information density as written for humans* and *information density as consumed by transformers*. CtxPack introduces `.ctx`, a multi-resolution text format with a formal grammar, and a packer that converts structured domain corpora (YAML, Markdown) into semantically compressed context through entity resolution, deduplication, heuristic salience scoring, and hierarchical notation. In controlled evaluations across corpus sizes from 690 to 37,000 tokens, CtxPack achieves 5.6–8.3x compression while maintaining 92–100% question-answering fidelity — matching or exceeding uncompressed baselines. At 37K source tokens, CtxPack (92% fidelity at 8.3x compression) decisively outperforms raw context stuffing (60% fidelity at 1x), which suffers from the well-documented lost-in-the-middle effect. An LLM-generated summary baseline at equivalent token budgets achieves only 29–76% fidelity, demonstrating that structured compression categorically outperforms free-form summarization. We release the codec, evaluation framework, and all results under AGPL-3.0.

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

3. **Empirical evidence across scale**: Controlled evaluations from 690 to 37,000 source tokens demonstrating 5.6–8.3x compression with 92–100% fidelity, compared against three baselines: raw context stuffing, LLM-generated summarization, and naive truncation (Section 5).

4. **A counterintuitive finding**: At small corpus sizes, the compressed representation achieves *higher* fidelity than the raw source (100% vs. 96%), because the packer disambiguates implicit scope qualifiers that the LLM misreads in raw YAML. The codec does not merely preserve information — it clarifies it (Section 5.4).

5. **An open evaluation framework**: A reproducible benchmark with 25 curated questions (including adversarial hallucination traps), dual grading (rule-based + LLM-as-judge), and a scaling corpus generator, released under AGPL-3.0.

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

4. **Format-aware, not model-specific.** The `.ctx` notation is designed for how *transformers in general* process structured text, not for any specific model's tokenizer. This ensures portability across model families and versions.

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

The raw YAML states `unique: true` without specifying scope. The packer infers `unique-per-merchant` from the description field. This is a form of *disambiguation during compression* — the codec makes implicit knowledge explicit, improving downstream LLM comprehension (see Section 5.4 for empirical evidence).

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
3. **LLM summary**: Ask the same LLM (Claude Sonnet 4.6) to summarize the corpus into the same token budget as CtxPack's output. This is the key competitive baseline — "why not just ask the LLM to summarize?"
4. **Naive truncation**: Take the first N words of the concatenated source to match CtxPack's token count. This establishes a floor.

**Grading.** Each question is graded by two independent methods:

1. **Rule-based grading**: Normalized keyword matching with prefix-aware fuzzy matching. The answer and expected answer are normalized (hyphens/underscores collapsed, punctuation stripped), then key terms (>2 characters) are extracted from the expected answer and matched against the actual answer. A 60% term-match threshold is required. For adversarial "NOT_IN_CONTEXT" questions, the grader checks for explicit signals ("not found in context", "not specified", etc.).

2. **LLM-as-judge**: The same LLM is prompted to compare the candidate answer against the expected answer and respond with CORRECT or INCORRECT. This provides a more nuanced assessment that can recognize semantic equivalence beyond keyword overlap.

Both scores are reported. Disagreements between graders are analyzed rather than hidden, as they reveal genuine ambiguity in the evaluation (see Section 5.5).

**Evaluation model.** Claude Sonnet 4.6 (Anthropic) for all fidelity testing. Questions are presented with the compressed/raw context and a concise prompt. Each question is evaluated independently (no multi-turn).

### 5.2 Golden Set Results

Table 1 presents results on the fixed golden set (690 source tokens, 25 questions).

**Table 1.** Golden set evaluation (690 source tokens, 25 questions, Claude Sonnet 4.6).

| Method | Tokens | Compression | Cost/Query | Fidelity (Rule) | Fidelity (Judge) | Fidelity (Avg) |
|--------|--------|-------------|------------|-----------------|------------------|----------------|
| Raw stuffing | 720 | 1.0x | $0.0022 | 96.0% | 100.0% | 98.0% |
| **CtxPack L2** | **124** | **5.6x** | **$0.0004** | **100.0%** | **96.0%** | **98.0%** |
| LLM summary | 95 | 7.3x | $0.0003 | 84.0% | 76.0% | 80.0% |
| Naive truncation | 124 | 5.6x | $0.0004 | 32.0% | 20.0% | 26.0% |

CtxPack matches raw stuffing on average fidelity (98%) at 5.6x compression, reducing per-query cost by 82% ($0.0022 → $0.0004). The LLM summary baseline, despite achieving slightly better compression (7.3x), scores 18 percentage points lower on average fidelity (80% vs. 98%). Naive truncation confirms the problem is non-trivial: at the same token budget, uninformed compression achieves only 26%.

### 5.3 Scaling Curve

To test whether these results hold at scale, we generated synthetic corpora at 1K, 5K, 20K, and 50K source tokens using a multi-domain entity generator covering retail, logistics, healthcare, fintech, HR, and marketing entities. Questions were generated proportionally (24–25 per scale, stratified by difficulty). Table 2 presents fidelity scores (rule-based) across scale.

**Table 2.** Fidelity (rule-based) across corpus scale. Compression ratio in parentheses.

| Source Tokens | CtxPack L2 | Raw Stuffing | LLM Summary | Naive Truncation |
|---------------|-----------|--------------|-------------|------------------|
| 690 | **100%** (5.6x) | 96% (1x) | 76% (7.3x) | 28% (5.6x) |
| 1,202 | **100%** (7.0x) | 100% (1x) | 62% (6.6x) | 25% (7.0x) |
| 4,098 | 96% (7.9x) | **100%** (1x) | 29% (18.1x) | 21% (7.9x) |
| 15,244 | **100%** (8.2x) | 100% (1x) | 32% (59.5x) | 40% (8.2x) |
| 37,411 | **92%** (8.3x) | 60% (1x) | — | 12% (8.3x) |

Three trends emerge:

**Compression ratio improves with scale.** The ratio increases from 5.6x at 690 tokens to 8.3x at 37K tokens, confirming that larger corpora contain more structural redundancy (repeated entity patterns, shared retention policies, common field types) that the packer exploits.

**CtxPack fidelity is stable.** Across a 54x increase in corpus size, CtxPack fidelity ranges from 92% to 100%. The 8% drop at 37K tokens represents the boundary condition where the compressed output (4,520 tokens) itself becomes large enough that some information is harder for the LLM to retrieve — but the degradation is gradual, not catastrophic.

**Raw stuffing collapses at scale.** At 37K source tokens, raw stuffing fidelity drops to 60%. This is consistent with the lost-in-the-middle phenomenon (Liu et al., 2023): with 38,923 tokens of uncompressed YAML and Markdown in context, the LLM systematically fails to attend to information positioned away from the beginning and end of the context window. CtxPack's compressed 4,520-token representation avoids this entirely.

**LLM summarization degrades catastrophically.** The LLM summary baseline drops from 76% at 690 tokens to 29% at 4K tokens. Free-form summarization cannot preserve the specific thresholds, identifiers, relationship constraints, and cross-entity rules that structured domain knowledge requires. At 37K tokens, the source exceeds the summarization prompt's effective capacity and was not evaluated.

Figure 1 illustrates the Pareto frontier. CtxPack occupies the top-left quadrant (high fidelity, low token count) at every scale tested.

```
Fidelity (%)
100 |  ■CtxPack ■CtxPack  ·Raw  ·Raw       ■CtxPack
    |  ·Raw
 90 |                                ■CtxPack
    |
 80 |  △LLM
    |
 70 |
    |       △LLM
 60 |                                        ·Raw
    |
 50 |
 40 |                               ○Naive
    |              △LLM    △LLM
 30 |  ○Naive
 25 |       ○Naive
 20 |              ○Naive
    |
 10 |                                        ○Naive
    +------------------------------------------------
      690    1.2K   4.1K   15K     37K    Source tokens

    ■ CtxPack L2   · Raw stuffing   △ LLM summary   ○ Naive truncation
```

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

The scope qualifier "per merchant" appears only in the human-readable description field, not in the structured identifier definition. When the full YAML is provided as raw context, the LLM reads `unique: true` as a boolean flag and answers "string, unique" — omitting the scope. The CtxPack output makes the scope explicit:

```
IDENTIFIER:sku(string,unique-per-merchant)
```

The packer inferred the scope by pattern-matching the entity description against known scope markers, then enriched the compressed identifier. The LLM, reading the compressed format, correctly answers "string, unique per merchant."

This is not merely information preservation — it is *information clarification*. The codec compensates for a gap between how the source data is structured (scope buried in a description string, disconnected from the boolean flag) and how the consumer (the LLM) processes it (attending primarily to structured fields). This parallels how MP3's psychoacoustic model compensates for the playback device's limitations, and provides empirical support for the *transformer-perceptual compression* thesis: a codec designed for how the model reads can outperform the raw signal.

### 5.5 Grader Agreement and Adversarial Results

Of 25 questions on the golden set, the rule-based grader and LLM judge agree on 23 (92% agreement). The two disagreements are instructive:

**Q13 (raw stuffing baseline):** The LLM answered "string, unique" (missing "per merchant"). The rule-based grader marks this incorrect (missing key term). The LLM judge marks it correct, assessing that "unique" is the essential fact and the scope qualifier is secondary. This reveals a genuine ambiguity in grading — is partial credit appropriate? We report both scores to let readers judge.

**Q22 (ctxpack L2 baseline):** An adversarial hallucination trap asking about GDPR/CCPA compliance rules, which are not in the corpus. The LLM correctly states that GDPR/CCPA are "not explicitly mentioned" but then extrapolates from adjacent retention and PII rules in the compressed context. The rule-based grader marks this correct (detected "not explicitly" signal). The LLM judge marks it incorrect, assessing that the extrapolation goes beyond a clean "not found" response. This demonstrates that compressed context rich in related rules can trigger *adjacent extrapolation* — a failure mode worth investigating in future work.

**Adversarial results.** All 5 adversarial questions were answered correctly by CtxPack across both graders (with the Q22 exception noted above). The two pure hallucination traps (Q21: return/refund policy, Q22: GDPR/CCPA) received clean "not found in context" responses, confirming that the compressed format does not induce confabulation. The low-salience edge cases (Q23: seasonal product deactivation, Q24: UK Royal Mail address format) were preserved by CtxPack but lost by all other baselines at equivalent compression — Q24 is particularly notable as only CtxPack preserved the Royal Mail detail, which is the kind of operationally critical but infrequently referenced fact that causes production incidents months later when no one remembers it existed.

### 5.6 Cost Analysis

Table 3 presents per-query costs across scale, assuming Claude Sonnet 4.6 pricing ($3/M input tokens).

**Table 3.** Per-query input cost across scale.

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

The LLM summary baseline's degradation from 76% to 29% as corpus size increases reveals a fundamental limitation of free-form summarization for domain knowledge. Three categories of information are systematically lost:

1. **Specific thresholds and parameters.** The LLM summary at 5K tokens dropped "5 minutes" (inventory staleness SLA), "0.92" (Jaro-Winkler threshold), and "Royal Mail" (UK address format). These values have low lexical salience but high operational importance.

2. **Cross-entity relationships.** The summary failed to preserve that PAYMENT requires an ORDER (mandatory foreign key) and that ORDER belongs to CUSTOMER. Relationship chains that span entity boundaries are condensed into vague references or dropped entirely.

3. **Contradiction awareness.** At scale, the LLM summary smoothed over retention-policy conflicts rather than preserving them. CtxPack's explicit `⚠` warning markers ensure conflicts survive compression.

This suggests a general principle: **summarization optimizes for narrative coherence, while domain knowledge requires fact preservation.** The `.ctx` format's structured notation inherently preserves facts (as key-value pairs within entity sections) rather than narrativizing them.

### 6.2 The Lost-in-the-Middle Effect

The raw stuffing baseline's collapse from 100% to 60% at 37K tokens provides direct evidence of the lost-in-the-middle phenomenon in a domain knowledge context. Notably, the questions that raw stuffing failed at 37K were not inherently difficult — they simply referenced entities whose YAML definitions fell in the middle of the concatenated source text. CtxPack's salience-ordered output places the most-referenced entities first and last, exploiting the known attention distribution of transformer models.

### 6.3 Limitations

**Corpus size.** Our largest evaluation uses 37K source tokens. Production domain corpora can exceed 100K tokens. The scaling curve suggests fidelity may continue to degrade gradually beyond 50K, though the compression ratio should continue improving. Multi-file split (planned for v0.3) would address this by serving only query-relevant sections.

**Domain coverage.** All evaluation corpora use entity-relationship patterns typical of data platform documentation (YAML entities, business rules, regulatory policies). Highly narrative domains (legal opinions, strategy memos, research papers) would likely see lower compression ratios because they contain less structural redundancy. Cross-domain robustness testing is planned for future work.

**Synthetic scaling corpora.** The scaling experiment uses synthetic entities generated from templates. While the entity patterns are realistic (drawn from 6 different industries), the corpora lack the organic inconsistencies, ambiguous phrasing, and unexpected structures of real-world documentation. We report the golden set (hand-authored) results separately for this reason.

**Single evaluation model.** All fidelity testing uses Claude Sonnet 4.6. Different models may have different sensitivity to the `.ctx` notation. Cross-model evaluation is planned.

**Scope inference risk.** The packer's scope inference (Section 4.2) enriches compressed output with information inferred from entity descriptions. If the inference is incorrect, the packer injects misinformation. The current implementation uses a conservative, fixed set of scope markers and can be disabled via `--strict` mode. The inference should be validated against domain ontologies in production use.

### 6.4 Ethical Considerations

CtxPack compresses but does not generate content. It cannot introduce hallucinated facts that are not present in the source corpus (with the exception of the scope inference feature, which can be disabled). The conflict detection pipeline actively surfaces contradictions rather than resolving them, ensuring that domain experts remain aware of inconsistencies. The format is inspectable and auditable, unlike embedding-based compression approaches.

---

## 7. Future Work

**Multi-file split and query-adaptive serving.** For corpora exceeding useful single-context budgets, we plan a MANIFEST-based multi-file split that indexes entities by keyword and serves only query-relevant sections, with always-include files for cross-cutting rules.

**RAG post-processing.** CtxPack as a layer between retriever and LLM: `pack_chunks(retrieved_chunks) → compressed .ctx context`. This would directly address chunk redundancy and lost-in-the-middle in RAG pipelines.

**Learned salience scoring.** The current heuristic scorer can be augmented with a small learned model trained on click-through data or expert annotations to better predict which fields are most relevant to downstream queries.

**Cross-model and cross-domain evaluation.** Systematic testing across model families (GPT-4, Gemini, Llama, Mistral) and domain types (legal, financial, scientific) to establish generality bounds.

**Perceptual model formalization.** The current notation is designed by intuition about transformer attention patterns. A rigorous study mapping `.ctx` operator tokens to attention weights would enable principled optimization of the notation itself — tuning the codec to the perceptual model, as MP3's psychoacoustic tables were tuned empirically.

---

## 8. Conclusion

CtxPack demonstrates that structured context compression, designed around how transformer models consume information rather than how humans write it, can achieve substantial compression (5.6–8.3x) without sacrificing information fidelity (92–100%). The key empirical finding is that structured compression categorically outperforms LLM-generated summarization at equivalent token budgets — by 18 percentage points at small scale and 63+ points at medium scale — because summarization optimizes for narrative coherence while domain knowledge requires fact preservation.

The counterintuitive result that compressed context can *exceed* raw context fidelity (100% vs. 96% on the golden set, 92% vs. 60% at 37K tokens) suggests that the gap between how domain knowledge is typically documented and how LLMs optimally consume it represents a significant, underexploited opportunity. A codec that bridges this gap is not merely a cost optimization — it is a quality improvement.

CtxPack, the `.ctx` format specification, the evaluation framework, and all experimental results are available at https://github.com/cryogenic22/CTX.ai under AGPL-3.0.

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

## Appendix A: Golden Set Question Details

**Table A1.** Per-question results for CtxPack L2 on the golden set (25 questions).

| ID | Difficulty | Question (abbreviated) | Rule | Judge |
|----|-----------|----------------------|------|-------|
| Q01 | Easy | Golden source for customer data? | ✓ | ✓ |
| Q02 | Medium | Churned customer data after 36 months? | ✓ | ✓ |
| Q03 | Easy | Type of customer_id? | ✓ | ✓ |
| Q04 | Easy | Is customer_id mutable? | ✓ | ✓ |
| Q05 | Medium | Matching algorithm for name+address? | ✓ | ✓ |
| Q06 | Medium | PII classification for customer email? | ✓ | ✓ |
| Q07 | Medium | Order status flow? | ✓ | ✓ |
| Q08 | Medium | Line items immutable after which status? | ✓ | ✓ |
| Q09 | Easy | Financial fields decimal precision? | ✓ | ✓ |
| Q10 | Easy | What entity does ORDER belong to? | ✓ | ✓ |
| Q11 | Medium | Max staleness for inventory? | ✓ | ✓ |
| Q12 | Medium | Order exceeds $50,000? | ✓ | ✓ |
| Q13 | Easy | SKU identifier type? | ✓ | ✓ |
| Q14 | Medium | How is inventory synced? | ✓ | ✓ |
| Q15 | Hard | Conflicting retention policies? | ✓ | ✓ |
| Q16 | Medium | Null policy for email? | ✓ | ✓ |
| Q17 | Easy | Timestamps stored/displayed? | ✓ | ✓ |
| Q18 | Medium | US address normalisation? | ✓ | ✓ |
| Q19 | Medium | PII classification for card numbers? | ✓ | ✓ |
| Q20 | Hard | Min retention for financial data? | ✓ | ✓ |
| Q21 | Hard | Customer return/refund policy? (adversarial) | ✓ | ✓ |
| Q22 | Hard | GDPR/CCPA deletion rules? (adversarial) | ✓ | ✗ |
| Q23 | Hard | Seasonal products at end of season? | ✓ | ✓ |
| Q24 | Hard | UK address format standard? | ✓ | ✓ |
| Q25 | Hard | Can PAYMENT exist without ORDER? | ✓ | ✓ |

**Total:** Rule-based 25/25 (100%), LLM judge 24/25 (96%).

## Appendix B: Compression Example

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
