# CtxPack v0.4.0 Backlog — Spec-Driven, Test-Driven Development

**Target**: Transform CtxPack from a compression tool into a knowledge serving protocol.
**Method**: Spec first → tests first → implementation → verification. Every feature has a formal interface spec, tests written before code, and acceptance criteria.

---

## Work Streams

| ID | Work Stream | Status | Depends On |
|----|-------------|--------|------------|
| WS1 | Variable Bitrate — BudgetAllocator | **DONE** (19 tests) | — |
| WS2 | Variable Bitrate — Compression Presets + CLI | **DONE** (15 tests) | WS1 |
| WS3 | Variable Bitrate — Must-Preserve Contracts | **DONE** (included in WS1) | WS1 |
| WS4 | Progressive Hydration — Section-Level ctx/hydrate | **DONE** (22 tests) | — |
| WS5 | Progressive Hydration — LLM-as-Router Protocol | **DONE** (15 tests) | WS4 |
| WS6 | Rate-Distortion Experiment | **DONE** (7 tests + live run) | WS1, WS2 |
| WS7 | Hydration Fidelity Experiment | **DONE** (9 tests + live run) | WS4, WS5 |
| WS8 | Paper v3 — Results + Red Team Responses | Not Started | WS6, WS7 |

---

## WS1: Variable Bitrate — BudgetAllocator

### Spec

**New file**: `ctxpack/core/packer/budget.py`

```python
@dataclass(frozen=True)
class CompressionPreset:
    """Named compression configuration."""
    name: str                          # "conservative", "balanced", "aggressive"
    max_ratio: float                   # 5.0, 10.0, 15.0
    min_tokens_per_entity: int         # 30, 15, 5
    drop_below_salience: float         # 0.0, 0.3, 0.6
    abbreviate_values: bool            # False, False, True

PRESETS: dict[str, CompressionPreset]  # Registry of named presets

@dataclass
class FieldBudget:
    """Per-field inclusion decision."""
    field: IRField
    action: str       # "include", "abbreviate", "drop"
    reason: str       # Why this decision was made (for auditability)

@dataclass
class EntityBudget:
    """Token allocation for one entity."""
    entity: IREntity
    token_budget: int
    field_decisions: list[FieldBudget]

def allocate(
    corpus: IRCorpus,
    *,
    preset: str = "balanced",
    total_budget: int = 0,     # 0 = auto from preset
    must_preserve: set[str] | None = None,  # Field keys that are never dropped
) -> list[EntityBudget]:
    """Distribute token budget across entities and decide per-field inclusion.

    Algorithm:
    1. Score entities by salience (existing)
    2. Allocate budget proportionally to salience
    3. For each entity, rank fields by salience
    4. Include must-preserve fields unconditionally
    5. Fill remaining budget in salience order
    6. Mark remaining fields as "abbreviate" or "drop" per preset

    Returns ordered list of EntityBudget (highest salience first).
    """
```

**Modified file**: `ctxpack/core/packer/compressor.py`
- `compress()` gains `preset: str = "balanced"` parameter
- Internally calls `allocate()` before building sections
- `_entity_to_section()` respects `FieldBudget.action`

**Modified file**: `ctxpack/core/packer/__init__.py`
- `pack()` gains `preset: str = "balanced"` parameter, forwards to `compress()`

**Modified file**: `ctxpack/cli/main.py`
- `pack` subcommand gains `--preset conservative|balanced|aggressive` flag

### Tests (write first)

**New file**: `tests/test_budget.py`

```
TestPresets:
  test_preset_registry_has_three_presets
  test_conservative_preset_values
  test_balanced_preset_values
  test_aggressive_preset_values
  test_unknown_preset_raises_value_error

TestAllocate:
  test_allocate_returns_entity_budgets_for_all_entities
  test_higher_salience_entity_gets_more_budget
  test_must_preserve_fields_always_included
  test_must_preserve_overrides_low_salience
  test_boolean_fields_never_dropped
  test_identifier_fields_never_dropped
  test_aggressive_preset_drops_low_salience_fields
  test_conservative_preset_keeps_all_fields
  test_balanced_preset_intermediate_behavior
  test_empty_corpus_returns_empty_list
  test_single_entity_gets_full_budget

TestFieldDecisions:
  test_field_budget_has_action_and_reason
  test_drop_reason_includes_salience_score
  test_abbreviate_action_for_aggressive_preset

TestCompressorIntegration:
  test_compress_with_preset_conservative
  test_compress_with_preset_aggressive_produces_fewer_tokens
  test_compress_preset_conservative_geq_balanced_geq_aggressive_tokens
  test_pack_with_preset_parameter_works
  test_cli_preset_flag_accepted
```

### Acceptance Criteria
- [ ] `allocate()` is pure function: same corpus + preset → same result
- [ ] Conservative produces >= balanced >= aggressive token count (monotonic)
- [ ] Must-preserve fields survive at every preset level
- [ ] All 461 existing tests still pass
- [ ] `ctxpack pack --preset aggressive corpus/` works from CLI

---

## WS2: Variable Bitrate — Compression Presets + CLI

### Spec

**Modified file**: `ctxpack/cli/main.py`
- Add `--preset` argument to `pack` subcommand
- Mutually exclusive with `--max-ratio` / `--min-tokens-per-entity` (preset overrides both)
- Default: `balanced` (preserves current behavior)

**Modified file**: `ctxpack/core/packer/compressor.py`
- `_entity_to_section()` accepts `field_decisions: list[FieldBudget]`
- Fields with action="drop" are skipped
- Fields with action="abbreviate" get value truncated to first clause

### Tests (write first)

```
TestPresetCLI:
  test_cli_pack_preset_conservative
  test_cli_pack_preset_balanced_is_default
  test_cli_pack_preset_aggressive
  test_cli_pack_preset_invalid_errors
  test_cli_preset_overrides_max_ratio

TestAbbreviation:
  test_abbreviate_truncates_to_first_clause
  test_abbreviate_preserves_key
  test_abbreviate_keeps_cross_references
```

### Acceptance Criteria
- [ ] CLI `--preset` flag works for all three presets
- [ ] `balanced` output matches current behavior (backward compatible)
- [ ] Abbreviated fields are syntactically valid .ctx

---

## WS3: Variable Bitrate — Must-Preserve Contracts

### Spec

**Modified file**: `ctxpack/core/packer/templates.py`
- `EntitySchema` gains `must_preserve_fields: list[str]`
- These fields are NEVER dropped regardless of preset

**Modified file**: `ctxpack/core/packer/budget.py`
- `allocate()` collects must-preserve from:
  1. Explicit `must_preserve` parameter
  2. Template's `must_preserve_fields`
  3. Built-in type rules: boolean-valued fields, IDENTIFIER, enum-valued fields

**Built-in must-preserve heuristic** (type-based, not salience-based):
```python
def _is_must_preserve(field: IRField) -> bool:
    """Type-based must-preserve: booleans, identifiers, enums never dropped."""
    if field.key == "IDENTIFIER":
        return True
    # Boolean patterns: true/false, yes/no, enabled/disabled
    if field.value.lower().strip() in ("true", "false", "yes", "no",
                                        "enabled", "disabled"):
        return True
    # Enum-like: short values that are single tokens
    if len(field.value.split()) == 1 and len(field.value) < 20:
        return True
    return False
```

### Tests (write first)

```
TestMustPreserve:
  test_boolean_field_never_dropped_at_aggressive
  test_identifier_never_dropped_at_aggressive
  test_enum_field_never_dropped_at_aggressive
  test_template_must_preserve_overrides_salience
  test_explicit_must_preserve_parameter
  test_deprecated_flag_preserved_at_all_levels  # Red team's exact example
  test_must_preserve_combined_with_template_required_fields

TestRedTeamScenario:
  test_openapi_deprecated_flag_survives_aggressive_compression
  test_compliance_boolean_survives_aggressive_compression
```

### Acceptance Criteria
- [ ] Red team's exact failure case passes: `deprecated: true` preserved at L2-64
- [ ] Boolean/enum/identifier fields survive at every preset
- [ ] Template must_preserve_fields respected
- [ ] Zero regression on existing tests

---

## WS4: Progressive Hydration — Section-Level ctx/hydrate

### Spec

**Modified file**: `ctxpack/integrations/mcp_server.py`
- `ctx/hydrate` tool gains `section` parameter for direct section-name lookup
- When `section` is provided, bypasses keyword matching entirely
- Returns serialized section at the configured bitrate

**New file**: `ctxpack/core/hydrator.py`
```python
@dataclass
class HydrationResult:
    """Result of hydrating sections from a .ctx document."""
    sections: list[Section]
    tokens_injected: int
    sections_available: int
    header_text: str       # Serialized header for context

def hydrate_by_name(
    doc: CTXDocument,
    section_names: list[str],
    *,
    include_header: bool = True,
) -> HydrationResult:
    """Return specific sections by name. O(1) lookup via index.

    This is the primary hydration path — the LLM decides what to fetch.
    """

def hydrate_by_query(
    doc: CTXDocument,
    query: str,
    *,
    max_sections: int = 5,
    include_header: bool = True,
) -> HydrationResult:
    """Keyword-based fallback for non-agentic (programmatic) use.

    Uses term overlap scoring. Not the primary path — LLM-as-router is preferred.
    """

def list_sections(doc: CTXDocument) -> list[dict[str, Any]]:
    """Return section names with token counts — the LLM reads this to decide."""
```

### Tests (write first)

**New file**: `tests/test_hydrator.py`

```
TestHydrateByName:
  test_hydrate_single_section_by_name
  test_hydrate_multiple_sections_by_name
  test_hydrate_nonexistent_section_returns_empty
  test_hydrate_case_insensitive_matching
  test_hydrate_includes_header_by_default
  test_hydrate_excludes_header_when_false
  test_hydrate_tokens_count_is_accurate

TestHydrateByQuery:
  test_hydrate_by_query_returns_relevant_sections
  test_hydrate_by_query_empty_returns_error
  test_hydrate_by_query_max_sections_respected
  test_hydrate_by_query_no_match_returns_empty

TestListSections:
  test_list_sections_returns_all_section_names
  test_list_sections_includes_token_counts
  test_list_sections_empty_document

TestMCPIntegration:
  test_mcp_hydrate_with_section_param
  test_mcp_hydrate_with_query_param
  test_mcp_hydrate_returns_valid_ctx_text
```

### Acceptance Criteria
- [ ] `hydrate_by_name()` returns correct section in <1ms
- [ ] `list_sections()` output is sufficient for LLM to decide what to hydrate
- [ ] MCP `ctx/hydrate` tool works with both `section` and `query` params
- [ ] Hydrated output round-trips through parser

---

## WS5: Progressive Hydration — LLM-as-Router Protocol

### Spec

**New file**: `ctxpack/core/hydration_protocol.py`
```python
def build_system_prompt(
    l3_doc: CTXDocument,
    manifest_doc: CTXDocument | None = None,
    *,
    hydration_instructions: bool = True,
) -> str:
    """Build a system prompt that includes L3 + hydration instructions.

    The LLM reads this, understands the domain structure,
    and calls ctx/hydrate(section="ENTITY-X") when it needs detail.

    Returns text like:
    ---
    You have access to a compressed domain knowledge base.
    The structural map is below. Use the ctx/hydrate tool to
    expand any section you need.

    Available sections: ENTITY-CUSTOMER (~120 tokens),
    ENTITY-ORDER (~95 tokens), RULES-DATA-QUALITY (~80 tokens)

    [L3 content here]
    ---
    """

def build_hydration_tool_schema() -> dict:
    """Return the MCP tool schema for ctx/hydrate in a format
    suitable for injection into system prompts or tool definitions."""
```

**Modified file**: `ctxpack/core/packer/__init__.py`
- `PackResult` gains `system_prompt: str = ""` field
- When `layers=["L2", "L3"]`, automatically builds the system prompt

### Tests (write first)

```
TestSystemPrompt:
  test_build_system_prompt_includes_l3_content
  test_build_system_prompt_lists_available_sections
  test_build_system_prompt_includes_token_counts
  test_build_system_prompt_includes_hydration_instructions
  test_build_system_prompt_without_instructions
  test_build_system_prompt_from_pack_result

TestHydrationToolSchema:
  test_schema_has_section_parameter
  test_schema_has_query_parameter
  test_schema_is_valid_json_schema
```

### Acceptance Criteria
- [ ] System prompt is <600 tokens for golden set
- [ ] System prompt includes all section names with token counts
- [ ] A human reading the prompt can understand how to use ctx/hydrate
- [ ] `PackResult.system_prompt` is populated when L3 is requested

---

## WS6: Rate-Distortion Experiment

### Spec

**New file**: `ctxpack/benchmarks/rate_distortion.py`
```python
@dataclass
class RDPoint:
    """One point on the rate-distortion curve."""
    preset: str
    compression_ratio: float
    bpe_tokens: int
    word_tokens: int
    fidelity_rule: float     # Rule-based fidelity (0-100)
    fidelity_judge: float    # LLM-as-judge fidelity (0-100)
    cost_per_query: float

def run_rate_distortion(
    corpus_dir: str,
    *,
    presets: list[str] = ["conservative", "balanced", "aggressive"],
    models: list[str] | None = None,  # Default: all available
    questions_path: str | None = None,
) -> list[RDPoint]:
    """Run the rate-distortion experiment.

    For each preset × model:
    1. Pack corpus at preset
    2. Run all eval questions
    3. Measure fidelity, compression, cost

    Returns data points for plotting the Pareto frontier.
    """
```

### Tests (write first)

```
TestRateDistortion:
  test_rd_returns_points_for_each_preset
  test_rd_conservative_has_highest_fidelity
  test_rd_aggressive_has_highest_compression
  test_rd_monotonic_compression_across_presets
  test_rd_output_has_all_required_fields

TestRDOffline (no API keys):
  test_rd_compression_ratios_without_fidelity
  test_rd_bpe_token_counts_without_fidelity
```

### Acceptance Criteria
- [ ] Produces a plottable rate-distortion dataset
- [ ] Conservative fidelity >= balanced fidelity >= aggressive fidelity (monotonic)
- [ ] At least compression and token counts work offline (no API keys)
- [ ] Results saved to `ctxpack/benchmarks/results/rate_distortion.json`

---

## WS7: Hydration Fidelity Experiment

### Spec

**New file**: `ctxpack/benchmarks/hydration_eval.py`
```python
@dataclass
class HydrationEvalResult:
    """Result of evaluating hydration vs full injection."""
    question_id: str
    tokens_full_l2: int
    tokens_hydrated: int
    sections_hydrated: list[str]
    fidelity_full: float
    fidelity_hydrated: float
    token_savings_pct: float

def run_hydration_eval(
    corpus_dir: str,
    *,
    questions_path: str | None = None,
    model: str | None = None,
) -> list[HydrationEvalResult]:
    """Compare full L2 injection vs section-level hydration.

    For each question:
    1. Determine which sections a human would hydrate (ground truth)
    2. Hydrate those sections
    3. Run eval question with hydrated context
    4. Compare fidelity against full L2 injection

    Hypothesis: >95% fidelity at <50% token count.
    """
```

### Tests (write first)

```
TestHydrationEval:
  test_eval_returns_results_for_all_questions
  test_hydrated_tokens_less_than_full_l2
  test_eval_result_has_all_required_fields

TestHydrationEvalOffline:
  test_section_selection_logic_without_api
  test_token_counting_without_api
```

### Acceptance Criteria
- [ ] Produces per-question comparison dataset
- [ ] Token savings measurable offline
- [ ] Fidelity comparison requires API keys (skippable)

---

## WS8: Paper v3 — Results + Red Team Responses

### Spec

**Modified file**: `paper/ctxpack-whitepaper-v2.md`
→ Becomes `paper/ctxpack-whitepaper-v3.md`

New sections:
1. **Section 6: Rate-Distortion Analysis** — Pareto frontier plot, preset comparison, must-preserve rules
2. **Section 7: Progressive Hydration** — LLM-as-router protocol, token savings, fidelity results
3. **Section 8: Honest Limitations** — Red team findings (static salience fallacy, understanding vs execution), mitigations
4. **Updated Section 5.12**: Corrected narrative — CtxPack is cost/latency optimizer, not window-size fix
5. **Updated Abstract**: Add rate-distortion and hydration results

### Acceptance Criteria
- [ ] Rate-distortion figure included
- [ ] Red team's "static salience fallacy" acknowledged explicitly
- [ ] "Understanding vs execution" distinction documented
- [ ] Corrected context-window narrative (cost/latency, not size)

---

## Implementation Order

```
Phase 1 (parallel):
  WS1: BudgetAllocator       ← spec + tests + impl
  WS4: Hydrator              ← spec + tests + impl

Phase 2 (parallel, after Phase 1):
  WS2: Presets + CLI          ← depends on WS1
  WS3: Must-Preserve          ← depends on WS1
  WS5: LLM-as-Router Protocol ← depends on WS4

Phase 3 (parallel, after Phase 2):
  WS6: Rate-Distortion Exp    ← depends on WS1+WS2
  WS7: Hydration Fidelity Exp ← depends on WS4+WS5

Phase 4:
  WS8: Paper v3               ← depends on WS6+WS7
```

---

## Quality Gates

Every work stream must pass before merge:

1. **Spec review**: Interface documented with types and docstrings
2. **Tests written first**: All test stubs exist and fail before implementation
3. **Implementation**: Minimal code to make tests pass
4. **461+ existing tests pass**: Zero regression
5. **New tests pass**: All acceptance criteria met
6. **Round-trip verification**: Any new .ctx output parses back correctly
7. **No new dependencies**: `ctxpack/core/` remains zero-dep
