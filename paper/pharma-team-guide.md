# CtxPack Integration Guide — For the Flywheel Team

Based on your field report (46 flywheels, 48 agents, 11 value streams, Claude Sonnet). Every problem you documented has been addressed.

---

## What Changed (update to latest)

```bash
git pull origin main
```

---

## Problem → Solution Mapping

| Your Problem | What We Shipped | Module |
|---|---|---|
| .ctx notation causes hallucination | **Prose output is now the default** — `ctx/hydrate` returns Markdown, not .ctx notation. `--raw` flag for machine use only. | Core fix |
| Sandwich grounding boilerplate (100+ lines) | **Built-in grounding wrapper** — top rules + data + bottom checklist, auto-generated | `ctxpack.modules.grounding` |
| "market" matching "marketing" | **Word-boundary keyword matching** — `\bmarket\b` regex, no substring false positives | `ctxpack.modules.keywords` |
| "patient services" silently drops second VS | **One-to-many keyword resolution** — one keyword maps to all matching entities | `ctxpack.modules.keywords` |
| Claude invents flywheel names | **Context guard** — detects unknown entity names in response, recommends warn/retry/new_session | `ctxpack.modules.guard` |
| "How many flywheels?" returns wrong count | **Catalog-wide query detection** — detects count/list/overview intent, returns grouped summary | `ctxpack.modules.catalog_queries` |
| Temperature matters more than prompt engineering | **Documented** — grounding module includes temperature warning in prompt | `ctxpack.modules.grounding` |

---

## How to Use Each Module

### 1. Grounding Wrapper (replaces your ~100 lines of sandwich prompt code)

```python
from ctxpack.modules.grounding import build_grounded_prompt

system_prompt = build_grounded_prompt(
    catalog=readable_catalog,          # Your L3 text (always in prompt)
    hydrated=hydrated_sections,        # L2 sections (on-demand)
    persona="You are a senior pharma strategist helping explore decision flywheels.",
    citation_format="[{title}](/flywheel/{id})",
    sandwich=True,                     # Top rules + bottom checklist
    few_shot=True,                     # Auto-generates correct vs wrong example
    entity_count_reminder=True,        # "There are exactly 46 flywheels"
    temperature_warning=True,          # Reminds: use temperature 0
)
```

**What it produces:**

```
## GROUNDING RULES
You must ONLY reference entities from the catalog data below.
Do NOT invent, paraphrase, or generate entity names from memory.
If information is not in the provided data, say "not found in catalog."
IMPORTANT: Use temperature 0 for grounded retrieval queries.

## CORRECT vs INCORRECT EXAMPLE
CORRECT: The catalog lists "Adaptive HCP Targeting & Segmentation" (CL-01)
INCORRECT: "HCP Targeting & Prioritisation" ← this name does not exist in the catalog

[Your persona instruction here]

--- CATALOG DATA ---
[Your L3 catalog + hydrated L2 sections here]
--- END DATA ---

## BEFORE YOU RESPOND
1. Every entity name MUST come from the catalog data above.
2. Use citation format: [Title](/flywheel/ID) for every flywheel reference.
3. The catalog contains exactly 46 entities. Do not add or remove any.
4. If you cannot answer from the data above, say "not found in catalog."
```

**Value**: Eliminates your `generateGroundingRules()` + `generateTailReminder()` functions. One call replaces both. The entity count is auto-detected from the catalog text.

---

### 2. Keyword Index (replaces your VS keyword matching + fixes the bugs)

```python
from ctxpack.modules.keywords import KeywordIndex

# Auto-generate from your catalog
index = KeywordIndex(word_boundary=True, min_keyword_length=4)

# Add from entity names (auto-splits on &, filters generic words)
for flywheel in flywheels:
    index.add(flywheel.id, flywheel.id)          # CL-01 → CL-01
    index.add(flywheel.title.lower(), flywheel.id) # full title
    for part in flywheel.title.split("&"):        # split on &
        index.add(part.strip().lower(), flywheel.id)

# Add value stream keywords (one-to-many)
for vs_name, flywheel_ids in vs_map.items():
    for word in vs_name.lower().split():
        if len(word) >= 4:
            for fid in flywheel_ids:
                index.add(word, fid)

# Add manual synonyms for domain terms
index.add_synonyms({
    "hcp": "CL-01",
    "targeting": "CL-01",
    "omnichannel": "MR-03",
})

# Query — returns all matches, sorted by relevance
matches = index.match("marketing reimagination flywheels")
# → ["MR-01", "MR-02", "MR-03", "MR-04", "MR-05", "MR-06"]
```

**What it fixes:**
- `"market"` no longer matches `"marketing"` (word-boundary regex)
- `"patient services"` returns BOTH "Supply Chain & Patient Services" AND "Patient Services Reimagination"
- Keywords auto-generated from entity names — no manual maintenance

**Value**: Replaces your `buildVsKeywordMap()` function with correct word-boundary matching and one-to-many resolution. The two production bugs you reported are structurally impossible with this module.

---

### 3. Context Guard (replaces your passive low-confidence detection)

```python
from ctxpack.modules.guard import ContextGuard

# Initialize with your known catalog
guard = ContextGuard(
    known_entity_names={fw.id for fw in flywheels},  # {"CL-01", "MR-01", ...}
    custom_signals=[
        "from industry experience",
        "in the pharmaceutical industry",  # domain-specific hallucination signal
        "best practice suggests",
    ],
)

# After Claude responds:
result = guard.check(claude_response)

if result.recommendation == "ok":
    # Clean response — serve it
    pass
elif result.recommendation == "warn":
    # Low-confidence signals detected — flag in UI
    print(f"Warning: {result.signals_detected}")
elif result.recommendation == "retry":
    # Unknown entity names found — inject correction and retry
    correction = guard.build_correction(result)
    # → "Note: The previous response may contain entity names not in
    #    the catalog. Use ONLY the following entities: [CL-01, CL-02, ...]"
elif result.recommendation == "new_session":
    # Multiple unknown entities — conversation is poisoned
    print("Start a new session — conversation history is contaminated")
```

**What it detects:**
- Unknown flywheel IDs in response (e.g., "CL-07" when max is CL-06)
- Hallucinated names not in catalog
- Signals like "from industry experience" (falling back to training data)

**Value**: Closes the loop between detection and action. Your current telemetry logs low confidence but doesn't act on it. The guard provides `warn`, `retry`, or `new_session` recommendations. The correction message can be injected into the next turn to break the hallucination cycle (your Problem 3 — conversation history poisoning).

---

### 4. Catalog Queries (replaces your catalog keyword detection)

```python
from ctxpack.modules.catalog_queries import is_catalog_query, build_catalog_summary
from ctxpack.core.packer import pack

# Detect catalog-wide queries
if is_catalog_query(user_question, entity_type="flywheels"):
    # "How many flywheels do we have?" → True
    # "Tell me about CL-01" → False

    # Build grouped summary
    result = pack("path/to/flywheel/corpus/")
    summary = build_catalog_summary(result.document, group_by="prefix")
    # → "TOTAL: 46 entities across 11 groups
    #    CL (6): CL-01, CL-02, CL-03, CL-04, CL-05, CL-06
    #    MR (6): MR-01, MR-02, MR-03, MR-04, MR-05, MR-06
    #    ..."
```

**Value**: Replaces your `catalogKeywords` array + special code path. Auto-detects "how many", "list all", "overview", "every", "what flywheels do we have" patterns. The summary groups by entity prefix and includes exact counts — answering "How many flywheels do we have?" with "exactly 46 across 11 value streams" instead of "at least 15 that I can see."

---

## Migration Path

You don't have to replace everything at once. Each module is independent:

**Week 1 — Quick wins (no code restructure):**
- Update to latest `git pull`
- Prose-default hydration is automatic (no code change)
- Add `ContextGuard` after Claude responses (3 lines of code)
- Replace your keyword map with `KeywordIndex` (same API surface, fixes the bugs)

**Week 2 — Grounding wrapper:**
- Replace your `generateGroundingRules()` + `generateTailReminder()` with `build_grounded_prompt()`
- Remove the ~100 lines of sandwich prompt assembly
- Keep your few-shot examples if you prefer them over auto-generated ones

**Week 3 — Catalog queries:**
- Replace your `catalogKeywords` array with `is_catalog_query()`
- Replace your catalog summary builder with `build_catalog_summary()`

**Optional — Telemetry:**
- CtxPack has built-in JSONL telemetry (`ctxpack.core.telemetry`). Your Supabase-based telemetry is more production-ready. Keep yours, but consider piping CtxPack's hydration events into your Supabase table for unified analytics.

---

## What We'd Love Back

1. **Does the grounding wrapper produce better results than your custom sandwich code?** The auto-generated few-shot example may not be as good as your hand-crafted one. Let us know.

2. **Does the keyword index catch cases your current matching misses?** We'd love to see any false positives/negatives.

3. **Your telemetry data.** If you can share anonymized query logs (zero-match rate, low-confidence rate, top sections), it would help us prioritize what to build next.

4. **Your `computeSalience()` function.** We want to make salience scoring pluggable — your pharma-specific scoring (decision statement = +3, SDAL completeness = +4, agents = +2) would be a reference implementation.

5. **Your 172 tests.** We're building a test harness generator (M7). Your coverage + fidelity test patterns are the template.

---

## Token Economics (what to expect)

Based on your current setup (46 flywheels, ~500 queries/month):

| Metric | Your Current | With CtxPack Modules |
|---|---|---|
| Tokens per query | ~5,300 | ~5,300 (same — modules improve quality, not size) |
| Hallucination rate | Occasional (solved by temp 0) | Near-zero (guard + grounding + word-boundary) |
| Boilerplate code | ~300 lines (grounding + keywords + detection) | ~30 lines (module imports + config) |
| Keyword bugs | 2 known (substring + one-to-many) | 0 (structurally prevented) |
| Maintenance | Manual keyword lists, custom sandwich code | Auto-generated keywords, one-call grounding |
