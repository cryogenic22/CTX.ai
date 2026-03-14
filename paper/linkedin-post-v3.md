# Update: What happened when I pressure-tested my own claims

A few months ago I shared a post about CtxPack — a tool I built to compress domain knowledge for LLMs. The response was generous. People reached out, asked smart questions, and pointed me toward research I hadn't seen. Some of the feedback was "this is interesting, but your numbers look too good."

They were right to be skeptical. And this post is about what happened when I took that seriously.

---

## The thread that pulled everything loose

After publishing the original results — 5.6x compression, 98% fidelity — I kept running evaluations across different models and corpus sizes. The compression numbers were remarkably consistent. A little too consistent. And the cost-per-query numbers looked almost unreasonably cheap across every model I tested.

That nagging feeling is what led me to look more carefully at how I was counting tokens.

The evaluation framework I'd built measured compression using word count — `len(text.split())`. This is how most people eyeball token counts and it's a reasonable approximation for normal English prose. But CtxPack's compression format does something subtle: it joins multi-word descriptions with hyphens. "Source location reference with file path" becomes `Source-location-reference-with-file-path`. Five words become one.

Word count said that was great compression. But LLM APIs don't bill by words. They bill by BPE tokens — the subword units their tokenizers actually produce. And BPE tokenizers handle hyphens poorly. That "one word" was actually 5-8 BPE tokens.

My 5.6x compression ratio was measured in words. In BPE tokens — what actually gets billed — it was closer to 1.2x.

The metric was being gamed by its own encoding. Not intentionally. But the effect was the same: every claim built on top of it was overstated.

---

## What I did about it

The first instinct was to feel terrible about it. The second, better instinct was to treat it as an engineering problem.

I wrote a test — seven lines of code — that checks whether the BPE-to-word ratio is within a sane range. If I'd written that test on day one, it would have caught the problem immediately. That test is now one of seven CI-gated "metric sanity checks" that run on every evaluation. They exist specifically to catch the case where my measurements are lying to me.

Then I rebuilt the evaluation pipeline from scratch. BPE tokens as the primary metric everywhere. Cross-model judging — GPT-4o grades Claude's answers, eliminating the self-judging bias that had silently corrupted an earlier run through rate-limit failures I hadn't detected. Retry logic with exponential backoff so API errors don't get silently counted as wrong answers. Error detection so a failed judge call gets flagged, not scored.

The pipeline isn't just more accurate now. It's designed to tell me when it's broken.

---

## Rethinking the architecture

With honest metrics in hand, I had to ask a harder question: if CtxPack doesn't actually compress files much in BPE terms, where is the value?

The answer came from looking at how the tool was actually being used. Nobody stuffs a compressed file into a prompt and calls it a day. The real workflow is: you have 37 entity definitions, 11 runbooks, and 5 governance documents. A user asks a question about one entity. You need to give the LLM enough context to answer, without drowning it in 92,000 tokens of everything else.

This reframing shifted the architecture from "make the file smaller" to "serve the right section per query." I call it progressive hydration:

**Step 1.** The packer compiles your domain knowledge into a structured, indexed knowledge base — resolving entities across files, deduplicating fields, flagging contradictions, tracking provenance. This is the hard, valuable work. It's deterministic, costs nothing to run, and produces the same output every time.

**Step 2.** A lightweight directory index (~1,800 tokens) goes in the system prompt. It lists every entity with its identifier — nothing more. The LLM reads this index like a table of contents.

**Step 3.** When a question arrives, the LLM decides which 1-3 sections to retrieve. No embedding model. No vector database. The LLM's own comprehension of the directory serves as the query router. The relevant sections are injected as focused context — typically 3,000-4,000 tokens instead of 92,000.

This is more like streaming than compression. You don't download the entire album to listen to one track. You stream the track you need. The full corpus never enters the context window.

---

## The science that made it click

While rethinking the architecture, someone pointed me to a paper that had just been accepted at an ICML 2025 workshop: "Unable to Forget: Proactive Interference Reveals Working Memory Limits in LLMs Beyond Context Length" by Wang and Sun.

Their finding is striking: LLM retrieval accuracy degrades log-linearly as competing information accumulates in context. And critically, making the context window bigger doesn't help — the degradation is tied to model parameter count, not window size. Prompt engineering doesn't fix it either. Chain-of-thought doesn't fix it. It's a fundamental property of how transformers handle interference between competing values.

This gave me the scientific language for what progressive hydration actually does. When you stuff 37 entity definitions into a prompt, many of them share similar field names — `retention_period`, `status`, `pii_classification` appear across dozens of entities. The model has to disambiguate between all of them simultaneously. That's exactly the interference condition the paper shows causes retrieval degradation.

When you hydrate just the one or two entities relevant to the current question, you eliminate that interference. The model is looking at 3,000 tokens of focused, unambiguous context instead of 92,000 tokens of competing definitions.

And CtxPack's entity resolution — where three different files that all define "Customer retention policy" get merged into one canonical definition with provenance — is literally interference reduction at the source level. You're removing the conflicting prior values before they ever enter the context window.

---

## What the clean numbers actually show

I ran the full evaluation on a realistic enterprise corpus: 37 entity definitions, 11 operational runbooks, 5 governance rule files — 92,000 BPE tokens total, modeled on the kind of domain knowledge a real e-commerce data platform team maintains.

Thirty evaluation questions across five categories: straightforward factual lookups, cross-entity reasoning, negation questions, multi-hop queries that span several entities, and adversarial hallucination traps.

Cross-model GPT-4o judge for every response. Zero judge failures across 60 graded answers. Every claim below comes from this clean pipeline.

**The headline: 26x per-query cost reduction with a stable 7 percentage point fidelity tradeoff.**

On Claude Opus, raw context stuffing scores 87% fidelity at $1.39 per query. CtxPack hydration scores 80% at $0.05 per query. For a team running a thousand domain knowledge queries a day, that's the difference between $42,000 a month and $1,600 a month.

On easy and medium questions — "What is the Customer identifier?", "What are the allowed order statuses?", "What happens to inventory when a shipment is created?" — the fidelity is effectively identical. The 7-point gap comes almost entirely from multi-hop questions that need information scattered across four or more entities, where the 1-3 section retrieval limit prevents complete coverage.

I also ran the same evaluation on Claude Haiku and GPT-4o-mini to test how the architecture performs across model sizes.

Haiku showed the same pattern: raw stuffing at 77%, hydration at 70%, same 7-point gap. The interference effect from the Wang and Sun paper is visible — Haiku's raw fidelity is 10 points lower than Opus, consistent with their finding that smaller models have less interference resistance.

GPT-4o-mini broke the pattern entirely. Raw stuffing scored 57%, but hydration collapsed to 20%. The model simply wasn't capable enough to do the routing task — reading a directory index and selecting relevant sections requires a minimum level of comprehension that GPT-4o-mini doesn't have for structured domain content. This establishes a practical minimum model threshold: the LLM-as-router architecture needs at least Haiku-class capability to function.

---

## What I got wrong, and what matters about that

The original compression numbers were wrong. Not by a little — by a factor of 4-5x. I was measuring in words when the world bills in BPE tokens, and my encoding was systematically inflating the word-based metric.

But I want to be precise about what that error was and wasn't.

The pack pipeline — entity resolution, deduplication, conflict detection, salience scoring, provenance tracking — was always sound engineering. When three files define the same entity differently, the packer merges them, flags contradictions, and tracks which source contributed each field. That work has value regardless of how you count the output tokens.

What was wrong was the claim about what the output looked like in token terms. And the evaluation pipeline had bugs that I only found by red-teaming my own results: rate-limited API calls that silently scored as failures, a judge model that was grading its own answers under the same rate limits as the answerer, and a system prompt that was larger than the document it was supposed to summarize.

Each of these was a straightforward engineering mistake. And each one made the numbers look better than reality. Not intentionally, but that's the insidious part — measurement errors that flatter your hypothesis don't feel like errors. They feel like validation.

The most important thing I built in v0.4.0 isn't a feature. It's seven tests that check whether my metrics are self-consistent. BPE-to-word ratio can't exceed 5x. Compression ratio in words can't diverge more than 3x from compression ratio in BPE. The L3 index can't be larger than 10% of the corpus. The judge failure rate can't exceed 10%. If any of these trip, the evaluation stops and tells you the measurement system is broken.

The tests that verify your features are important. The tests that verify your measurement system are more important.

---

## The MP3 analogy, revisited

In the original post, I said CtxPack was like "MP3 for LLM context." That analogy was overstated when it was about file-level compression. 1.2x BPE compression isn't MP3. It's barely a rounding error.

But the analogy holds at a different level, and I think more accurately.

MP3 didn't just make files smaller. It made music streamable. The compression mattered, but what changed the world was the ability to hear one track without loading the whole album. You send what the listener needs, when they need it.

That's what progressive hydration does. The packer is the encoder — it does the hard analytical work of structuring domain knowledge into retrievable units. The L3 directory is the index. And hydration is the streaming protocol — you serve the section the LLM needs for this specific question, not the entire knowledge base.

The Wang and Sun paper provides the equivalent of MP3's psychoacoustic model. MP3 removes frequencies the human ear can't perceive. CtxPack removes entities the transformer can't reliably retrieve under interference. The science is different but the principle is the same: understand the perceptual limits of the consumer and optimize the delivery format accordingly.

I think the honest framing is: CtxPack is at the stage MP3 was before the psychoacoustic model was fully understood. We have a codec that works, we have empirical evidence for when and why it helps, and we have a theoretical framework (proactive interference) that explains the mechanism. The full perceptual model — understanding exactly how each transformer architecture handles information density at different scales — is the deeper research problem this work points toward.

---

## What's next

The pack pipeline is solid. Entity resolution, deduplication, conflict detection, provenance tracking — these are the capabilities that no RAG chunker or LLM summarizer provides, and they're the reason CtxPack exists as a distinct tool rather than a wrapper around existing approaches.

The evaluation framework is now honest and self-verifying. Cross-model judging, retry logic, BPE-primary metrics, automated red-team checks. I trust the numbers because the system is designed to tell me when I shouldn't.

The open questions are the interesting ones:

Can we close the 7-point fidelity gap on multi-hop questions by allowing re-hydration — a second pass where the LLM says "I need more context" and requests additional sections? How does the architecture perform on real enterprise data rather than synthetic corpora? What happens at 500K tokens, where even frontier models should start showing the interference degradation the Wang and Sun paper predicts? Can the routing quality be improved with richer section summaries in the L3 index without blowing up the token budget?

These are the questions worth spending time on now. And they're only worth asking because the measurement foundation is trustworthy.

---

CtxPack v0.4.0, the complete evaluation data, the enterprise corpus, and the whitepaper with all results are at **github.com/cryogenic22/CTX.ai** under Apache 2.0.

If you work with domain knowledge at scale — RAG pipelines, context engineering, LLM infrastructure, data platform documentation — I'd welcome your perspective. The hardest problems left are the ones I probably can't see from inside the project.
