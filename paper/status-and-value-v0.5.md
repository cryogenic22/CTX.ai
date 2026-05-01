---
title: CtxPack — current capabilities and AI-app value (audited)
date: 2026-05-01
audience: engineering leads, AI product owners
length: 1-page status with claim grades
---

# CtxPack — Where We Are, What It Gives, What We Actually Know

> An earlier version of this doc oversold a few things. This version walks
> every claim against the code and the eval, grades it, and rewrites the
> overstated parts. The grading legend is at the top so the reader can
> trust the qualifier on each line:
>
> * ✅ **measured** — verified by the v3 eval or the test suite
> * ⚙️ **shipped** — code does this; behavioural impact in real deployments not yet measured
> * 📐 **theoretical** — based on cited research, not directly measured by us
> * ⚠️ **caveated** — claim depends on conditions worth surfacing

---

## Code state (as of 2026-05-01)

| Layer | Status | Where |
|---|---|---|
| **v0.5.0 release** | shipped | `main`, tagged |
| **Whitepaper v3 eval** | ✅ measured on a synthetic corpus | `paper/ctxpack-whitepaper-v3.md` |
| **Phase 1 — Four-Layer typing** | shipped (`151956a`) | `ctxpack/core/layers.py`, `ir.py`, `model.py` |
| **Phase 2 — Layer-aware consumers** | shipped (`246f435`) | `compressor.py`, `hydrator.py`, `modules/grounding.py` |
| **Phase 3a/b/c — Producers** | shipped (`6cd44b6`) | `core/confidence.py`, `core/incremental.py`, `modules/dream.py`, `modules/elicit.py` |
| Real-world dream pass on Market Zero / Intelligent Enterprise telemetry | not yet run | (code ready, awaiting telemetry export) |
| AMBIENT producer that actually pulls live state | foundation only (file-hash cache) | `core/incremental.py` |

943 tests collected. 753 fast-suite tests pass post-Phase-3. Zero-dep packing. Apache-2.0.

---

## What CtxPack gives an AI application

### 1. Cost & latency
- ✅ **24× per-query cost reduction** vs. raw context stuffing on a 92K-BPE synthetic corpus (Claude Opus 4.6: $0.058 vs $1.39). 30 questions, ±18pp margin of error at 95% CI.
- ✅ **Hydrated fidelity 86.7% — beats raw stuffing (83.3%) by 3.4pp** on Opus, ties embedding-RAG. ⚠️ On Claude Haiku 4.5 raw stuffing wins by 6.7pp; below Haiku-class models, routing degrades catastrophically (GPT-4o-mini hydrated fidelity was 20%).
- ✅ Deterministic — same input produces byte-identical output. No embedding service, no vector DB.
- ⚠️ The 24× number is the per-query cost ratio at this corpus shape. Smaller corpora compress less; the value scales with corpus size and query volume.

### 2. Hallucination guardrails
- ⚙️ **`build_grounded_prompt`** — sandwich prompt with rules at top, catalog in the middle, verification checklist at the bottom. 19 unit tests cover the structure. ⚠️ The "replaces 100+ lines of boilerplate" claim is anecdotal — we have not surveyed real teams.
- ⚙️ **`ContextGuard`** — substring matching against 5 default hallucination signals + regex check for unknown `ENTITY-XXX` names; emits `warn` / `retry` / `new_session`. 24 unit tests. ⚠️ False-positive rate and real-world catch rate **not measured**.
- ✅ **Catalog-query intent detection** — `is_catalog_query` recognises "how many?" / "list all"; this fixed an actual production bug where partial-section answers under-counted entities. 26 unit tests.

### 3. Domain-knowledge correctness
- ⚙️ **Entity resolution** with alias maps and one-to-many keyword indexing.
- ⚙️ **Conflict detection** before hydration. ✅ Tested against 17 real domain packs (analytics fixtures): 307 entities, 6 conflicts surfaced. ⚠️ Whether all 6 were "real" semantic conflicts vs. spurious overlaps not separately validated by a domain expert.
- ⚙️ **Provenance preserved through compression** (file path + line range survive packing).

### 4. Codebase context for coding agents
- ⚙️ **`ctxpack codebase harness .`** auto-generates `.claude/rules/` (anti-slop, test-requirements, commit-conventions, quality-check hook).
- ⚙️ Supplementary `.claude/codebase-map.md` exporter — never overwrites existing CLAUDE.md.
- ⚠️ The behavioural claim — "agents drift less" — is **not measured**. The harness exists; whether it actually reduces duplication, late-session quality drop, or PR revision cycles needs a controlled trial. The integration guide (`paper/scriptiva-team-harness-guide.md`) recommends measuring this once a team adopts it.

### 5. Four-layer trust model
- ✅ Every fact carries `layer` ∈ {RULES, INFERRED, ELICITED, AMBIENT}, `confidence` ∈ [0, 1], `observation_count`, optional `expires_at`. 24 typing tests + 17 consumer tests.
- ✅ `hydrate_by_name(layers={ContextLayer.RULES}, min_confidence=0.8)` filters retrieval to authoritative-only.
- ⚙️ **Trust legend** rendered into grounded prompts (4-line block after the catalog). ⚠️ Whether LLMs actually weight INFERRED facts differently from RULES facts when shown the legend is **not measured** — that's the next eval to design.

### 6. Producers (Phase 3)
- ⚙️ **ConfidenceTracker** — Bayesian-style observe/decay/prune, atomic JSON persistence. 26 tests.
- ⚙️ **Dream pipeline** — `consolidate(telemetry_log)` mines co-occurrence patterns above a threshold and produces INFERRED `IREntity` plus a gap queue. 18 tests. ⚠️ Algorithm is sound; **the first real-world dream pass on production telemetry has not been run**, so we have no evidence yet that mined patterns are useful in practice.
- ⚙️ **Elicit store** — single expert at 0.7, two-expert agreement at 0.95, challenge halves. 16 tests. ⚠️ No team has used it on real tribal knowledge yet.
- ⚙️ **IncrementalPacker** — SHA-256 + mtime change-set classifier. 15 tests. ⚠️ This is the *foundation* for AMBIENT, not a live-state producer. The compile-side merge that would actually skip work on unchanged files is intentionally deferred.

### 7. Telemetry & integrations
- ⚙️ Privacy-preserving `HydrationEvent` log (SHA-256 question hash, no raw text).
- ⚙️ MCP server (5 tools, prose-default hydration after a real production hallucination incident in the pharma deployment).
- ⚙️ CLI: `pack`, `hydrate`, `harness`, `telemetry`, `dream`, `elicit`.

---

## What an AI app misses without CtxPack — graded

| Missing capability | Symptom in production | Grade |
|---|---|---|
| Cost-aware retrieval | $1.39/query on Opus where $0.058 would do, ~$40K/month at 1K queries/day. | ✅ Measured (this corpus). ⚠️ Apps using competent RAG won't see the full 24× delta. |
| Interference reduction | Wang & Sun, *Unable to Forget: Proactive Interference* (ICML 2025 **Workshop**) show retrieval accuracy degrades log-linearly as competing context accumulates; window size is not significant (p=0.886). Reducing concurrent information should help. | 📐 Theoretical — we cite the result; we did not isolate interference vs. fidelity in our own eval. |
| Conflict detection | Two source files disagree silently; agents narrate around the contradiction. | ⚙️ Capability shipped; symptom narrative is plausible, not measured. |
| Boilerplate grounding rules | Each team writes their own grounding prompt and drifts. | ⚠️ Anecdotal. We have not surveyed real teams. |
| Post-response verification | LLM emits a fabricated entity name, no callback. | ⚠️ Plausible without the guard; real-world rate not measured. |
| Catalog-query intent | "How many flywheels do we have?" returns 3 instead of 37. | ✅ Real production bug; CtxPack fixes via `is_catalog_query`. |
| Coding-agent drift control | After a long session, the agent re-implements a utility that already exists. | ⚠️ Real phenomenon; harness fix not yet measured against a baseline. |
| Trust labelling | Pattern observed twice last week is treated like signed policy. | ⚠️ Mechanism shipped; behavioural effect on the LLM not measured. |
| Provenance on cited facts | Compliance officer asks where a rule came from; the agent guesses. | ⚙️ Mechanically true. |
| Live-state separation | A feature-flag value from yesterday gets cited as today's policy. | ⚠️ AMBIENT *typing* shipped; producer that pulls live state is **not built yet**. |
| Reproducibility | Same query, different answer across runs. | ⚙️ True — pack pipeline is deterministic. |

---

## Honesty notes — what changed from the prior version of this doc

| Prior claim | What we said | What's actually true |
|---|---|---|
| "26× cost reduction" | Implied a general result | 24× cost reduction on the synthetic 92K-BPE corpus on Opus 4.6. The "26" came from a stale v0.4.0 memory entry (compression ratio, not cost ratio). |
| "~93% fidelity retention" | Implied hydration loses ~7pp vs raw | Wrong direction. v3 eval: hydrated 86.7%, raw 83.3% on Opus → hydration **wins** by 3.4pp. The "93%" came from a v0.4.0 measurement that has since been corrected. |
| "Production-validated" | Implied real deployment metrics | The eval is on a synthetic enterprise corpus, 30 questions, ±18pp margin at 95% CI. The whitepaper itself says: "directionally reliable but should be validated on real enterprise data." Pharma deployment exposed a real bug (hallucination on .ctx notation), now fixed — that is a real-world signal but not a fidelity validation. |
| "Wang & Sun (ICML 2025)" | Implied main-conference paper | It's an ICML 2025 *Workshop* paper. Same authors, same finding, lower venue — worth being precise about. |
| "Trust legend so the LLM weights observed patterns differently" | Implied measured behavioural effect | The legend is rendered in the prompt (tested). Whether the LLM actually shifts behaviour given the legend is not yet measured. |
| "Phase 2 / Phase 3 — designed, not started" | Stale | Both committed (`246f435`, `6cd44b6`). |

---

## What we still need to measure

These are the unmeasured claims above, ranked by how cheaply they could be validated:

1. **Trust-legend behavioural effect (1–2 days).** Rerun the v3 eval with INFERRED/RULES tags on a subset of facts; check whether the LLM cites them differently or hedges on INFERRED ones. Easy because the v3 eval harness already exists.
2. **ContextGuard precision/recall (3–5 days).** Run guard against a labeled set of known-good and known-hallucinated answers. Need labels.
3. **Codebase harness drift impact (1–2 weeks of usage).** Run a multi-session coding agent with and without the harness on the same task list; measure utility duplication and PR revision cycles.
4. **First real-world dream pass (1 day, gated on telemetry export).** Run `ctxpack dream consolidate` on Market Zero / Intelligent Enterprise telemetry; have humans review the mined INFERRED patterns and gap queue for usefulness.
5. **AMBIENT producer (1 week of build, not measurement).** Wire IncrementalPacker into the compressor's merge step so unchanged files actually skip re-parse, then measure pack-time savings on a corpus that updates frequently.
6. **Real-corpus fidelity (gated on a real corpus).** Re-run the eval on actual enterprise documentation rather than the synthetic 92K corpus.

The whitepaper section "Limitations" is candid about most of this — that section is a better source of truth than any one-pager, including the prior version of *this* page.

---

## Quick architecture reminder (unchanged)

```
Domain files  ──▶  pack  ──▶  L2 .ctx (full)  ──▶  L3 index (~1.8K BPE)
                                                         │
                                                         ▼
                                          Agent reads L3, picks sections,
                                          calls ctx/hydrate("ENTITY-X")
                                                         │
                                                         ▼
                                          Sandwich prompt: rules + catalog +
                                          hydrated detail + verification +
                                          (Phase 2) layer trust legend
                                                         │
                                                         ▼
                                          ContextGuard checks the answer,
                                          recommends warn / retry / new_session
                                                         │
                                                         ▼
                                          TelemetryLog records SHA-256 hash,
                                          sections matched, latency
                                                         │
                                          (Phase 3) ▼
                                          Inline observe-hook updates
                                          ConfidenceTracker; periodic
                                          `ctxpack dream consolidate`
                                          mines INFERRED patterns and
                                          a gap queue for ELICITED prompts.
```
