# CtxPack Integration Guide — For the Analytics Teams (SynSight)

CtxPack now compiles analytics domain packs into a unified, deduplicated knowledge base with cross-domain entity resolution. Tested against Bright_Light's actual 17 domain packs.

---

## What's Available

### Domain Pack Compiler

Compiles your YAML domain packs into a structured, queryable knowledge base:

```python
from ctxpack.modules.analytics import compile_domain_packs, build_analytics_l3

# Compile all 17 domain packs
corpus = compile_domain_packs("path/to/packs/")
```

**What it produces from your packs:**

| What | Count | What It Contains |
|---|---|---|
| Domain entities | 17 | Fingerprints, value enums, table structures, guardrails, KBQs per domain |
| Metric entities | 194 | Definition, formula, grain, owner, tags per metric |
| Dimension entities | 96 | Hierarchy levels, keys, attributes per dimension |
| Cross-domain dedup | 300 fingerprints | `customer_id` in 15 packs → stored once with provenance from all 15 |
| Conflicts detected | 6 | Metrics with same name but different formulas across domains |

### L3 Directory Index (for system prompts)

```python
l3 = build_analytics_l3(corpus)
```

Produces:
```
ANALYTICS DOMAIN DIRECTORY
Domains: 17 packs
---
AIRLINES: 14 fingerprints, 7 metrics, 4 dimensions
CONSULTING: 17 fingerprints, 9 metrics, 6 dimensions
ENERGY: 25 fingerprints, 16 metrics, 6 dimensions
RETAIL: 17 fingerprints, 14 metrics, 6 dimensions
SOFTWARE: 35 fingerprints, 18 metrics, 9 dimensions
TELECOM: 27 fingerprints, 19 metrics, 10 dimensions
...
---
Total: 300 fingerprints, 194 metrics, 96 dimensions
Warnings: 6 conflicts
```

This goes in the system prompt. The LLM sees "which domains exist, how rich each is" without loading all 8,037 lines.

---

## Integration Patterns

### Pattern 1: Domain-Aware NL2SQL (Bright_Light / Aura)

**Current flow**: Query → Supervisor → Planner calls `CatalogMetadataService.select_candidates()` → SQL generation

**Enhanced flow with CtxPack**:

```python
from ctxpack.modules.analytics import compile_domain_packs, build_analytics_l3
from ctxpack.modules.keywords import KeywordIndex
from ctxpack.modules.grounding import build_grounded_prompt
from ctxpack.core.packer import pack
from ctxpack.core.hydrator import hydrate_by_name

# At startup: compile packs + build indexes
corpus = compile_domain_packs("packs/")
l3 = build_analytics_l3(corpus)
pack_result = pack("packs/")  # For hydration

# Build keyword index from metrics + fingerprints
kw_index = KeywordIndex(word_boundary=True)
for entity in corpus.entities:
    if entity.name.startswith("METRIC-"):
        # "retail.metrics.gross_sales" → keywords: "gross", "sales", "retail"
        for word in entity.name.replace("-", " ").lower().split():
            if len(word) >= 4:
                kw_index.add(word, entity.name)

# Per query: resolve domain + hydrate relevant metrics
def handle_query(user_query: str) -> str:
    # Step 1: Detect if catalog-wide query
    from ctxpack.modules.catalog_queries import is_catalog_query
    if is_catalog_query(user_query, entity_type="metrics"):
        return build_analytics_l3(corpus)  # Return full directory

    # Step 2: Keyword match → find relevant metrics/domains
    matched_entities = kw_index.match(user_query)

    # Step 3: Hydrate matched metric definitions
    hydrated = hydrate_by_name(pack_result.document, matched_entities[:5])

    # Step 4: Build grounded prompt for SQL generation
    from ctxpack.core.serializer import serialize_section
    sections_text = "\n".join(
        line for s in hydrated.sections
        for line in serialize_section(s, natural_language=True)
    )

    prompt = build_grounded_prompt(
        catalog=l3,
        hydrated=sections_text,
        persona="You are an analytics SQL assistant. Generate accurate SQL using only the metrics and columns defined in the context.",
        grounding_rules=[
            "Only reference column names that appear in the fingerprints above",
            "Only use metric formulas exactly as defined — do not improvise calculations",
            "If a metric or column is not in the context, say 'not available in this domain'",
        ],
        sandwich=True,
    )

    return prompt  # → feed to your SQL generation LLM
```

**Value for Aura's planner**: Instead of `CatalogMetadataService` querying Postgres for candidates, the planner queries CtxPack's compiled corpus — deterministic, versioned, with conflict detection. The L3 index replaces the supervisor's schema overview.

### Pattern 2: Prompt Compression (SynSight / Fleet360)

**Current state**: 83KB `prompt.yml` stuffed into context on every query.

**Enhanced flow**:

```python
from ctxpack.core.packer import pack
from ctxpack.core.hydrator import hydrate_by_name, list_sections
from ctxpack.core.hydration_protocol import build_system_prompt
from ctxpack.modules.grounding import build_grounded_prompt

# Pack the prompt library (one-time at deploy)
result = pack("prompt_library/")

# L3 index: what's in the prompt library (~2K tokens vs 83K)
l3 = build_system_prompt(result.document)
sections = list_sections(result.document)

# Per query: hydrate only the relevant prompt sections
def get_prompt_for_query(query_type: str) -> str:
    # Map query type to sections
    section_map = {
        "analytical": ["SUPERVISOR-SYSTEM-PROMPT", "DETERMINISTIC-FLOW"],
        "chitchat": ["SUPERVISOR-SYSTEM-PROMPT", "CHITCHAT-HANDLER"],
        "dynamic": ["SUPERVISOR-SYSTEM-PROMPT", "DYNAMIC-FLOW"],
    }
    sections_needed = section_map.get(query_type, ["SUPERVISOR-SYSTEM-PROMPT"])
    hydrated = hydrate_by_name(result.document, sections_needed)

    # Build grounded prompt with only the relevant flow
    from ctxpack.core.serializer import serialize_section
    sections_text = "\n".join(
        line for s in hydrated.sections
        for line in serialize_section(s, natural_language=True)
    )

    return build_grounded_prompt(
        catalog=l3,
        hydrated=sections_text,
        sandwich=True,
    )
```

**Expected savings**: 83KB → ~5-10K tokens per query (selective hydration of relevant prompt sections only). At SynSight's scale, this is significant cost reduction.

### Pattern 3: Cross-Domain Deduplication (multi-tenant Aura)

When a customer connects a retail + ecommerce dataset:

```python
# Compile only the relevant packs
corpus = compile_domain_packs("packs/", include=["retail", "retail_ecommerce"])

# Cross-domain dedup automatically resolves:
# - "customer_id" defined in both → stored once, provenance from both
# - "Gross Sales" metric in both → conflict detected if formulas differ

# Warnings tell you what to resolve
for w in corpus.warnings:
    print(f"CONFLICT: {w.message}")
    # → "Metric gross_sales has different formulas in retail vs retail_ecommerce"
```

**Value**: When the planner sees `gross_sales`, it knows there are two definitions and can ask the user "Retail gross sales or ecommerce gross sales?" instead of silently picking one.

---

## What Each Module Does for Analytics

| Module | Analytics Use Case |
|---|---|
| **analytics.py** | Parse domain packs → unified IR with cross-domain dedup |
| **grounding.py** | SQL generation prompt with column-name guardrails |
| **keywords.py** | Metric/dimension name matching with word boundaries |
| **guard.py** | Detect hallucinated column names in generated SQL |
| **catalog_queries.py** | "What metrics are available?" → domain directory |

---

## Specific Value by Team

### Bright_Light (Aura)

| Current | With CtxPack | Benefit |
|---|---|---|
| 17 YAML packs loaded independently | Unified corpus with cross-domain dedup | Single source of truth |
| Manual metric conflict resolution | Automatic conflict detection (6 found) | Catches inconsistencies at pack time |
| Pack fingerprints pre-loaded (1,205 entries) | 300 after dedup (cross-domain identical fingerprints merged) | Cleaner data, less redundancy |
| `CatalogMetadataService` queries Postgres | CtxPack hydration queries compiled corpus | Deterministic, versionable, no DB dependency |
| No cross-domain synonym resolution | "Shopper" = "Customer" = "Passenger" resolved automatically | Consistent entity naming across domains |

### SynSight (Fleet360)

| Current | With CtxPack | Benefit |
|---|---|---|
| 83KB prompt library per query | ~5-10K tokens via selective hydration | ~90% token reduction |
| Static OpenSearch metric routing | CtxPack keyword index + L3 directory | Deterministic, no pre-indexing needed |
| Prompt rules hardcoded in YAML | Grounding wrapper with sandwich technique | Reduces hallucination, less boilerplate |
| No metric lineage | CtxPack provenance tracking | Field-level source attribution |

---

## Getting Started

```bash
pip install -e path/to/CTX_mod

# Quick test: compile your domain packs
python -c "
from ctxpack.modules.analytics import compile_domain_packs, build_analytics_l3

corpus = compile_domain_packs('path/to/your/packs/')
print(f'Entities: {len(corpus.entities)}')
print(f'Warnings: {len(corpus.warnings)}')
print()
print(build_analytics_l3(corpus))
"
```

If you see your domains, metrics, and dimensions in the output — it's working. The 6 cross-domain conflicts it detects are real inconsistencies in your pack definitions worth reviewing.

---

## What We'd Love Back

1. **Does the L3 directory index give your planner enough context to route queries?** Or does it need more detail per domain?

2. **Are the 6 detected conflicts real?** We found metrics with same short name but different formulas across domains. If these are intentional (domain-specific calculation), we need to distinguish "expected variation" from "actual conflict."

3. **Telemetry**: CtxPack logs every hydration call. If you pipe this into your observability stack, we can see which domains/metrics get queried most and optimize the L3 index accordingly.

4. **Your CatalogMetadataService interface**: If you share the `select_candidates()` API contract, we can build a CtxPack adapter that drops in as a replacement — same interface, backed by compiled corpus instead of Postgres.
