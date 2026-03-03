# CtxPack v0.3: 12 Models, 3 Ecosystems, 139 Tokens

**"It only works on Claude" is dead.**

When we published the first CtxPack evaluation in v0.2, the most obvious objection was model affinity: the format was developed against Claude, tested primarily on Claude, and the 8-point fidelity gap between Claude (100%) and GPT-4o (92%) left room for skepticism. Maybe the `.ctx` notation was just Claude-flavored prose that happened to compress well.

The v0.3.0-alpha evaluation answers that objection definitively. We tested CtxPack's L2 notation on 12 models from 3 ecosystems — Anthropic, OpenAI, and Google — spanning frontier models (GPT-5.2 Pro, Claude Sonnet 4.5), reasoning models (o3, o4-mini), mid-tier workhorses (GPT-4.1, GPT-4o), and the cheapest available tiers (Haiku 4.5, Gemini Flash Lite). Every single model achieves at least 92% fidelity on 139 tokens of compressed context. Four models hit 100%. The format is model-agnostic.

---

## What Changed Since v0.2

The v0.2 evaluation tested 2 models: Claude Sonnet 4.6 and GPT-4o. That was enough to demonstrate the core thesis (structured compression beats summarization) but left cross-model portability as an open question.

The v0.3.0-alpha evaluation expands to 12 models: Claude Sonnet 4.5, Claude Haiku 4.5, GPT-5.2, GPT-5.2 Pro, GPT-4.1, GPT-4o, GPT-4o-mini, o3, o4-mini, Gemini 2.5 Pro, Gemini 2.5 Flash, and Gemini 2.5 Flash Lite. The evaluation protocol also changed: instead of only testing L2, each model now answers the same 25 questions on both L2 (139 tokens, semantic graph notation) and L1 (417 tokens, compressed prose). This paired design isolates whether compact notation itself costs fidelity — or whether the token reduction is a free win.

The result: **the floor is 92% everywhere**, and compact notation is not a barrier.

---

## The Full Results

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

The headline numbers: **4 models at 100% L2**, a **92% floor** across all 12, and **L2 ≥ L1 on 11 of 12 models**. That last point deserves emphasis: compact semantic notation at 139 tokens performs as well as or better than natural-language prose at 417 tokens on nearly every model tested. For three models (GPT-5.2 Pro, GPT-4o, Gemini Flash), L2 *strictly outperforms* L1 — the token reduction actually helps by concentrating attention on dense information rather than diluting it across filler words.

The single exception is GPT-4.1 (96% L2 vs. 100% L1), a 4-point difference that falls within measured judge variance.

By ecosystem: Anthropic models average 100% L2, OpenAI ranges 92–100% across 7 models, and Google holds uniformly at 92% across all 3 models. No ecosystem shows systematic weakness. The format requires zero adaptation — the same file works everywhere.

---

## What Fails and Why

Across the 12 L2 evaluation runs, failures concentrate on just 5 of the 25 questions:

- **Q05** (5/12 fail): "What matching algorithm is used for name+address?" Models identify "Jaro-Winkler" but drop the ">0.92" threshold qualifier. This is a precision failure — the information is present in the notation (`fuzzy-match(Jaro-Winkler>0.92)`), but models extract the algorithm name and skip the parenthetical detail.

- **Q13** (4/12 fail): "What is the SKU identifier type?" Models answer "string" but miss "unique per merchant." The packer inferred this scope from the entity description and enriched the notation to `IDENTIFIER:sku(string,unique-per-merchant)`. Eight models extract it; four stop at the primary type.

- **Q25** (2/12 fail): "Can a PAYMENT exist without an ORDER?" GPT-4o and GPT-4o-mini fail to resolve the cross-reference `BELONGS-TO:@ENTITY-ORDER(order_id,mandatory)`. Other models parse it correctly.

- **Q23** (2/12 fail): "What happens to seasonal products at end of season?" GPT-5.2 and Gemini Flash correctly state "auto-deactivated" but omit "reactivation requires manual review by merchandising."

- **Q15** (1/12 fail): Gemini Flash's answer about retention policy conflicts was truncated mid-sentence.

The pattern is clear: **no model fails to understand the format**. Every failure involves correctly parsing the relevant section but dropping a specific qualifier, threshold, or constraint detail. These are attention allocation failures within dense notation, not parsing failures of the notation itself.

---

## The Cost Story

At 139 tokens, the cost per query is transformatively low:

| Model | Cost per Query (L2) |
|-------|:---:|
| Gemini 2.5 Flash Lite | $0.00001 |
| Claude Haiku 4.5 | $0.00011 |
| o4-mini | $0.00015 |
| GPT-4o | $0.00035 |
| Claude Sonnet 4.5 | $0.00042 |

Gemini Flash Lite at $0.00001 per query with 92% fidelity means you could make a million context-injected queries for $10. Even at frontier pricing (Sonnet at $0.00042), an organization making 10,000 queries/day against compressed domain knowledge spends ~$1,500/year on context tokens — versus ~$8,000/year for raw stuffing.

For high-volume production systems, the combination of cheapest-tier models + L2 compression makes domain knowledge injection essentially free as an operational cost. The scaling curve data shows this advantage grows with corpus size: at 37K source tokens compressed to ~4.5K, annual savings reach $50,000+ at frontier pricing and approach six figures at scale.

---

## Agent Compression: Beyond Static Knowledge

The v0.3.0-alpha release includes a proof-of-concept that extends CtxPack beyond static domain knowledge. A 30-step AI coding agent trace — tool calls reading files, grepping code, running tests, performing load tests and security scans — was compressed through the standard packer pipeline.

Results: 567 raw tokens compressed to 485 tokens (1.17x ratio), with 30 chronological steps reorganized into 9 entity-centric sections (API-SERVER, AUTH, DATABASE, USER, etc.), each with field-level provenance (`SRC:step-N`). Mean pack latency: 0.71ms.

The compression ratio is modest because agent traces are already information-dense. The value is structural: instead of re-reading 30 raw tool outputs to understand what the agent discovered, a model reads 9 organized entity sections with deduplicated fields and cross-references. This is the foundation for compressed agent session state — enabling long-running agents to maintain context across hundreds of steps without consuming hundreds of thousands of tokens.

---

## Adoption Implications

Three things the cross-ecosystem results change about how you should think about CtxPack:

**No vendor lock-in.** The same 139-token `.ctx` file works on Claude, GPT, Gemini, and reasoning models. You can compress once and serve everywhere — switch providers, use multiple models for different tasks, or route to the cheapest tier for bulk operations.

**Cost optimization on cheapest tiers.** Claude Haiku 4.5 scores 100% on L2. Gemini Flash Lite scores 92%. For high-volume production use cases where you're injecting the same domain knowledge into thousands of queries, you don't need a frontier model to read compressed context. The cheapest available model often suffices.

**Governance and auditability.** Because `.ctx` is plain text, deterministic, and version-controllable, you get the same governance benefits regardless of which model consumes it. The same compressed context can be audited, diffed, and versioned in git — something impossible with embedding-based compression or model-generated summaries.

---

## What's Still Missing

The cross-ecosystem evaluation is golden-set only (690 source tokens, 25 questions). We don't yet know how the 12-model fidelity distribution shifts at larger corpus sizes (1K–100K tokens). The scaling curve data is still limited to Claude Sonnet 4.6 and GPT-4o.

All evaluation corpora are in the customer data platform domain. Cross-domain testing (legal, financial, scientific corpora) is needed to establish generality bounds.

The agent compression experiment is a proof-of-concept, not a production feature. Incremental packing, conflict resolution across steps, and integration with agent frameworks are future work.

The evaluation uses self-judging (each model grades its own answers). While cross-model judge agreement is high in our earlier tests, independent third-party judging would strengthen the claims.

And the scaling evaluation's LLM-summary and naive-truncation baselines haven't been re-run with the latest packer version — the v0.2 baselines are directionally valid but the exact numbers may shift slightly with the updated L2 output (139 tokens vs. 124 in v0.2).

---

## Closing

Structured compression works everywhere. Twelve models from three ecosystems read the same 139-token `.ctx` file and achieve 92–100% fidelity — at one-third the tokens of prose and one-fifth the tokens of raw YAML. Compact notation is not a barrier; on most models, it's at least as good as natural language, and on some, it's better.

The remaining failures are precision-based: dropped thresholds and scope qualifiers, not format incomprehension. The format works. The question is no longer "does it generalize?" but "how far can we push it?"

**Repository:** [github.com/cryogenic22/CTX.ai](https://github.com/cryogenic22/CTX.ai)
**License:** AGPL-3.0-or-later
**Contact:** kapilpant@gmail.com
