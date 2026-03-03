# ctxpack v0.3.0-beta — Phase B Engineering Report

**Date:** 2026-02-23
**Author:** Kapil Pant / SynaptyX
**Scope:** Deep Engineering — Performance + Richness + Design
**Baseline:** v0.3.0-alpha (Phase A: Trust Layer, 220 tests)
**Result:** 318 tests passing, zero regressions

---

## Executive Summary

Phase B addresses three categories of engineering debt that blocked production-grade adoption:

1. **Performance** — Hot paths were O(n²); now O(n) with precompiled regex and AST-walking token counter
2. **Output richness** — Relationships, conflict detection, topology intelligence, and query-adaptive indexing are now functional (were stubs/no-ops)
3. **Design quality** — Streaming serializer enables MCP integration; diff engine enables CI workflows

**7 workstreams delivered. 98 new tests. 12 files modified, 1 new file created.**

---

## Workstream Detail

### WS1. Performance Hot Path Optimization

**Problem:** At 100K-token corpora, three hot paths dominated pack time:
- O(n²) string concatenation for cross-reference counting
- Regex recompilation ~5000x per YAML corpus
- Full-text materialization just to count tokens

**Changes:**

| Before | After | Impact |
|--------|-------|--------|
| `all_text += f" {f.value}"` then `.count()` per entity | Single-pass `ref_counts: dict[str, int]` via precompiled `_CROSSREF_RE` regex | O(n²) → O(n) |
| `re.match(r"^(\s*)([^#:]+?)...", line)` on every YAML line | Module-level `_MAPPING_RE = re.compile(...)` | Eliminates ~5000 recompilations per corpus |
| `_estimate_body_text()` builds string then `.split()` | `count_tokens()` walks AST summing `len(x.split())` per node | Zero string concatenation; reusable by L3 and manifest |
| Two-pass golden-source scan (sort all, then re-scan for golden) | Single-pass partition: extract golden first, sort remainder | Eliminates redundant scan |
| `_split_flow` char-by-char with `list.append` + `"".join` | Index-tracking with `text[start:i]` slicing | Fewer allocations |

**Files:** `compressor.py`, `yaml_parser.py`, `l3_generator.py`
**Tests:** 17 new (cross-ref index, token counting, regex, flow-split, golden partition)

---

### WS2. Relationship Modeling

**Problem:** The packer only emitted `BELONGS-TO:@ENTITY-X(field)`. Missing: cardinality (1:N, M:N), bidirectional tracking, cascade semantics. The spec defines `~>` and `>>` operators but the packer never used them.

**What's new:**

- **`IRRelationship` dataclass** — `source_entity`, `target_entity`, `rel_type`, `via_field`, `cardinality` (1:1/1:N/M:N), `cascade`, `required`, `certainty`
- **5 new relationship keys** parsed: `has_many`, `has_one`, `references`, `depends_on` (+ existing `belongs_to`)
- **Extended entity detection** — `id`, `uuid`, `primary_key`, `has_many`, `has_one`, `references`, `depends_on` now trigger entity heuristic
- **Bidirectional inference** — `BELONGS-TO` on A→B auto-creates `HAS-MANY` on B→A with `certainty=INFERRED` (and vice versa)
- **Spec operator emission** — `>>cascade-delete`, cardinality in `@ENTITY-X(field,1:N)` format
- **Salience boost** — Relationship keys get 1.2x multiplier

**Files:** `ir.py`, `yaml_parser.py`, `entity_resolver.py`, `compressor.py`, `json_parser.py`
**Tests:** 18 new (parse all rel types, cascade, bidirectional inference, no duplicates, entity detection, salience boost)

---

### WS3. Conflict Detection + Provenance Source Union

**Problem:** Two correctness bugs in the Trust Layer:
1. `_check_null_conflicts`, `_check_type_conflicts`, `_check_pii_conflicts` were all no-ops (returned `[]` or had `pass`)
2. `entity_resolver.py` silently dropped the second source during field dedup

**What's fixed:**

| Detector | Logic |
|----------|-------|
| **Null conflicts** | Cross-checks `IDENTIFIER(required)` against `NULL-POLICY(nullable)` on same field. Also detects `never-null` + `nullable` contradiction within a single policy. |
| **Type conflicts** | Compares identifier types across entities (e.g., `order_id` as `UUID` in one entity, `int` in another). Also checks FK references against target identifier types. |
| **PII conflicts** | Parses `field→LEVEL` patterns from `PII-CLASSIFICATION`. Flags same field with different levels across entities (e.g., `email→RESTRICTED` vs `email→CONFIDENTIAL`). |
| **Source union** | `IRField.additional_sources: list[IRSource]` accumulates all sources during dedup. Provenance generator emits `IDENTIFIER → customer.yaml#L5-L9 + customer-v2.yaml#L3-L7`. |

**Files:** `conflict.py` (rewritten), `ir.py`, `entity_resolver.py`, `prov_generator.py`
**Tests:** 15 new (null/type/PII detection, no false positives, source union, multi-source provenance)

---

### WS4. Enhanced L3 Generation (Cross-Entity Intelligence)

**Problem:** L3 only extracted entity-local features. No cross-entity patterns, no graph topology, no query routing hints.

**What's new:**

| Section | Content |
|---------|---------|
| **±ENTITIES** | Entity names + role tags: `CUSTOMER(hub)`, `PRODUCT(leaf)`, `ORDER(bridge)` |
| **±TOPOLOGY** (new) | `HUBS:CUSTOMER`, `LEAVES:PRODUCT`, `BRIDGES:ORDER+MERCHANT`, `GRAPH:5-entities,4-edges` |
| **±PATTERNS** | Existing status/match/retention + new `ID-PATTERN:4/5→UUID` aggregation |
| **±CONSTRAINTS** | Severity-sorted: PII (0) > IMMUTABLE (1) > ★ (2) > ⚠ (3). New `DENSITY:high(12-constraints/5-entities)` line |
| **Token budget** | If L3 exceeds 500 tokens, drops lowest-priority lines from PATTERNS/CONSTRAINTS |

Classification rules: `hub` = 3+ inbound `@ENTITY-X` refs, `leaf` = 0 refs, `bridge` = 1-2 refs.

**Files:** `l3_generator.py` (rewritten)
**Tests:** 12 new (topology detection, hub/leaf/bridge, entity roles, severity ranking, ID-pattern, budget trimming)

---

### WS5. Manifest V2 (Query-Adaptive Index)

**Problem:** Manifest was a flat layer listing. MCP hydration couldn't decide token budgets without reading full L2.

**What's new:**

| Section | Purpose |
|---------|---------|
| **±SECTION-INDEX** | `ENTITY-CUSTOMER:~45tok keys:[IDENTIFIER,PII,STATUS-MACHINE,RETENTION,IMMUTABLE-AFTER]` |
| **±ENTITY-INDEX** | `CUSTOMER:±ENTITY-CUSTOMER ~45tok` — O(1) entity lookup for hydration |
| **±KEYWORD-INDEX** | `ENTITY-ORDER:belongs-to,customer,identifier,match-rules,order,status-machine` — keyword-to-section routing |
| **Budget metadata** | Header fields: `TOTAL_L2_TOKENS:~200`, `TOTAL_L3_TOKENS:~85`, `AVG_SECTION_TOKENS:~40` |

**Files:** `manifest.py` (rewritten)
**Tests:** 11 new (section/entity/keyword indexes, budget metadata, round-trip, empty doc)

---

### WS6. Streaming Serializer

**Problem:** `serialize()` did `"\n".join(lines)` — materialized entire document. Blocks streaming for MCP server integration.

**What's new:**

| API | Signature | Use Case |
|-----|-----------|----------|
| `serialize_iter()` | `(doc, *, canonical, ascii_mode) -> Iterator[str]` | Streaming line-by-line output |
| `serialize_section()` | `(section, *, ascii_mode) -> Iterator[str]` | MCP per-section hydration |
| `serialize()` | Refactored to call `serialize_iter()` internally | Zero regression risk |

All internal `_serialize_*` functions converted to `_serialize_*_iter` yield-based versions.

**Files:** `serializer.py` (rewritten)
**Tests:** 12 new (byte-identical output, line count, section-level, ASCII/canonical modes, edge cases)

---

### WS7. `ctxpack diff` + Test Coverage

**Problem:** No way to compare two `.ctx` outputs. Missing unit tests for discovery, conflict, and salience scoring.

**What's new:**

- **`ctxpack/core/diff.py`** (new file) — AST diff engine:
  - `diff_documents(old, new) -> DiffResult` — walks two CTXDocuments in parallel
  - `DiffEntry` with `kind` (added/removed/changed), `path`, `old_value`, `new_value`
  - `format_diff()` — .ctx-flavored output: `+ ±ENTITY-NEW`, `- ±ENTITY-OLD`, `~ HEADER/CTX_TOKENS:~200 → ~250`
- **`ctxpack diff <file1> <file2>`** CLI command (exit 0 = identical, exit 1 = differences)

**Files:** `diff.py` (new), `cli/main.py`
**Tests:** 13 new (identical docs, added/removed/changed sections+headers, format output, CLI integration)

---

## Test Summary

| File | Tests | Covers |
|------|-------|--------|
| `test_phase_b_perf.py` | 29 | WS1 (performance) + WS6 (streaming) |
| `test_phase_b_relationships.py` | 18 | WS2 (relationship modeling) |
| `test_phase_b_conflict.py` | 15 | WS3 (conflict detection + provenance) |
| `test_phase_b_l3_manifest.py` | 23 | WS4 (L3 cross-entity) + WS5 (manifest V2) |
| `test_phase_b_diff.py` | 13 | WS7 (diff engine + CLI) |
| **New total** | **98** | |
| **Previous (Phase A)** | **220** | |
| **Grand total** | **318** | **zero regressions** |

---

## Files Changed

| File | Lines | Change Type |
|------|-------|-------------|
| `ctxpack/core/packer/ir.py` | 108 | Added `IRRelationship`, `additional_sources` on `IRField`, `relationships` on `IREntity` |
| `ctxpack/core/packer/compressor.py` | 277 | Cross-ref index, `count_tokens()`, relationship salience boost |
| `ctxpack/core/packer/yaml_parser.py` | 860 | Precompiled regex, 5 relationship keys, `_compress_relationship_extended`, `_build_relationships`, extended entity detection |
| `ctxpack/core/packer/conflict.py` | 321 | Rewrote null/type/PII conflict detectors (were no-ops) |
| `ctxpack/core/packer/entity_resolver.py` | 197 | Source union in dedup, bidirectional relationship inference |
| `ctxpack/core/packer/l3_generator.py` | 363 | Topology extraction, entity roles, ID-pattern, severity ranking, token budget trim |
| `ctxpack/core/packer/manifest.py` | 192 | Section/entity/keyword indexes, budget metadata |
| `ctxpack/core/packer/prov_generator.py` | 83 | Multi-source provenance output |
| `ctxpack/core/packer/json_parser.py` | 379 | Extended entity detection keys |
| `ctxpack/core/serializer.py` | 228 | `serialize_iter()`, `serialize_section()`, yield-based internals |
| `ctxpack/core/diff.py` | 188 | **New file** — AST diff engine |
| `ctxpack/cli/main.py` | 371 | Added `ctxpack diff` subcommand |

---

## Verification Checklist

| # | Check | Status |
|---|-------|--------|
| 1 | All 220 existing tests pass after each workstream | PASS |
| 2 | Cross-ref index produces identical salience scores to previous implementation | PASS (tested) |
| 3 | Bidirectional inference creates HAS-MANY with `certainty=INFERRED` | PASS |
| 4 | `_check_null_conflicts`, `_check_type_conflicts`, `_check_pii_conflicts` produce warnings on planted contradictions | PASS |
| 5 | Multi-source fields show both sources in `.ctx.prov` output | PASS |
| 6 | L3 `±TOPOLOGY` classifies hub/leaf entities correctly | PASS |
| 7 | L3 stays <500 tokens even with topology + severity ranking | PASS |
| 8 | Manifest `±SECTION-INDEX` token counts match serialized section lengths | PASS |
| 9 | `serialize_iter` output joined == `serialize` output (byte-identical) | PASS |
| 10 | `ctxpack diff` shows correct added/removed/changed | PASS |

---

## What This Unblocks

- **100K-token scaling experiments** — O(n) hot paths eliminate the performance bottleneck
- **MCP server integration** — Streaming serializer + manifest entity/keyword indexes enable query-adaptive hydration with token budgets
- **Trust layer credibility** — Conflict detectors actually detect conflicts; provenance tracks all sources
- **Whitepaper differentiation** — L3 topology + ID-pattern aggregation provide cross-entity intelligence that LLM summaries cannot match
- **CI/CD workflows** — `ctxpack diff` enables automated .ctx regression detection

---

## Addendum: Lead Review Response (2026-02-23)

### Issues raised and resolution

| Concern | Resolution | Evidence |
|---------|-----------|----------|
| **Bidirectional inference has no `--strict` equivalent** | Already covered. `--strict` suppresses all `certainty=INFERRED` fields, including inferred HAS-MANY/BELONGS-TO. | `TestStrictSuppressesInferredRelationships` (3 tests) |
| **Topology thresholds arbitrary (3+ = hub)** | `hub_threshold` parameter added to `generate_l3()`. Defaults to 3, configurable per-call. Pharma model can pass `hub_threshold=2` for PATIENT. | `TestConfigurableTopologyThreshold` (3 tests) |
| **L3 trim could drop PII constraints** | Confirmed safe. PII has severity score 0 (list start); `pop()` removes from end (⚠ items first). PII is the *last* thing trimmed. | Code audit of `_extract_constraints` sort order |
| **Keyword index too shallow** | Added `_SEMANTIC_RE` pattern extracting domain terms from values: retention, churn, pii, pci-dss, gdpr, immutable, encrypted, confidential, restricted, etc. Cap raised 10→15 keywords. | `TestSemanticKeywordExtraction` (3 tests) |
| **No benchmark numbers** | Added timing test: 50-entity vs 200-entity compress. Ratio must be <10x (linear=4x, quadratic=16x). Currently passes at ~4-5x. | `TestBenchmarkTiming` (2 tests) |
| **No query routing test** | Added `TestManifestQueryRouting` simulating keyword-to-section matching. Validates retention→CUSTOMER, confidential→CUSTOMER (not PRODUCT), customer→both referencing sections. | `TestManifestQueryRouting` (3 tests) |
| **Unknown relationship keys silently dropped** | Confirmed not dropped. `linked_to` → generic `LINKED-TO` field with `certainty=EXPLICIT`. No IRRelationship created (correct — can't infer graph structure from unknown semantics). | `TestUnrecognizedRelationshipKeys` (3 tests) |
| **No integration test against real corpora** | Acknowledged. Deferred to scaling experiment phase where golden set corpus provides real-world validation. |
| **Richness without measured fidelity** | Acknowledged. Relationship and topology features will be evaluated against fidelity scores in scaling experiment before inclusion in whitepaper claims. |

**Test count: 318 → 335** (17 review-response tests added in `test_phase_b_review_fixes.py`)

---

## Next Steps (v0.3.0 Release)

1. Run scaling curve experiment (1K→100K tokens) with new performance baseline
2. Validate relationship/topology features improve fidelity scores (not just richness)
3. Tag v0.3.0 after scaling results confirm claims
4. Begin MCP server integration using `serialize_section()` + manifest indexes
5. Pharma/healthcare template as first sector-specific pack config (with `hub_threshold=2`)
