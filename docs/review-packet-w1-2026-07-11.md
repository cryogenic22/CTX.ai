# Review Packet — Week-1 Execution Plan (2026-07-11)

**Range:** `1c49271..6ae57e3` (7 commits, 22 files, +1205/−25).
**Headless review:** `codex exec review --base 1c49271` (read-only).
**Protocol:** reviewer scope is notes-only — findings go to
`AGENT_COORDINATION.md` → *Reviewer Notes* (or under **Q2** in Open
Reviewer Questions); the active owner applies every fix. Do not edit
code/tests or commit.

Plan context: `docs/execution-plan-2026-07.md` (task cards W1-1..W1-6);
ratification + statistical amendments: end of `docs/notes.md`.

## Verify locally (all should be green)

```bash
python scripts/check_capability_registry.py       # W1-1 gate
python scripts/check_claims.py                    # W1-2 gate (2 WARNs expected, 0 FAILs)
python -m pytest tests/test_capability_registry.py tests/test_claims_gate.py \
  tests/test_token_accounting.py tests/test_mcp_tool_budget.py \
  tests/test_compactbench_driver.py tests/test_hydrator.py \
  tests/test_telemetry.py tests/test_session_reader.py \
  tests/test_negation_preservation.py tests/test_p0_trust_repairs.py -q
# 135 passed at commit time
python run_compactbench.py --dry-run --seeds 0 --k 1 --arms ctx   # rollup smoke
```

## Review units

### `07b740b` — docs: ratified plan + board (no code)
`docs/execution-plan-2026-07.md` (+319), `AGENT_COORDINATION.md`.
*Check:* do the task cards faithfully encode the ratified decisions
(cluster-level stats, 4 co-primary endpoints, conditional powered run,
Track C spec-spike-only)?

### `007a775` — W1-1 capability registry + gate
`docs/capability-registry.md`, `scripts/check_capability_registry.py`
(+109), `tests/test_capability_registry.py`, `README.md`.
*Design calls to scrutinize:* (a) 4 classes instead of the directive's 3
(`eval` added — benchmarks aren't product); (b) rows are exact-file or
dir-prefix, most-specific wins; (c) README aka-label scan is
line-scoped. **Q-a:** any module misclassified? (`modules/codebase.py`
CLI-exposed → experimental; `agent/session.py`/`state_parser.py` →
legacy despite `agent/__init__.py` exporting `parse_steps`.)

### `5041ae0` — W1-2 claims ledger + gate
`docs/claims-ledger.md` (C1-C8/E1-E4/R1-R3),
`scripts/check_claims.py` (+143), `tests/test_claims_gate.py`.
*Design calls:* README-only line-gating in fail mode (papers only get
the retracted-signature scan) — precision-first per the conflict-lint
lesson; retraction-context skip-words (`retract/corrected/wrong
direction/...`); numeric patterns = %, pp, Nx, F1. **Q-b:** can a real
claim shape slip the patterns (e.g. "9 out of 10", "p=0.25", plain
ratios)? `p=0.25` is ledgered (C8) but the *pattern* wouldn't catch an
unledgered one — worth a finding if you think it's exploitable drift.

### `860d1a8` — W1-3 labelled token estimator (core behavior change)
`ctxpack/core/tokens.py` (new, +53), `hydrator.py`, `telemetry.py`,
`mcp_server.py`, `session_reader.py`, `cli/main.py`,
`tests/test_token_accounting.py` (+96), `tests/test_hydrator.py`.
*The riskiest unit.* Measured basis: whitespace = −49%..−78% vs cl100k;
ctx kind = chars/3 (all 5 committed .ctx artifacts land −9%..+5%);
prose = chars/4 (±0%). **Q-c:** `tokens_injected` semantics changed
(numbers roughly 2–4x larger than before) — any consumer that treats it
as a budget/threshold rather than a display value? I found none, but a
second pass on `dashboard.py`/`scorecard.py` would be welcome.
**Q-d:** MCP pack metrics renamed (`source_words`,
`ctx_token_estimate`, `token_estimator`, `compression_ratio_words`);
old keys (`ctx_tokens`, `source_tokens`, `compression_ratio`) removed —
loud break preferred over silent lie. Any consumer I missed?
**Q-e:** calibration test reads git-tracked but *working-tree* files
(incl. two `.claude/ctx/session-*.ctx` that churn with dogfooding) —
acceptable, or should it pin `git show`-content?

### `d8b4bb0` — W1-4 tool surface + budget gate
`tests/test_mcp_tool_budget.py`, `README.md`, onboarding doc.
*Design call:* budget = 4,500 chars total descriptions (measured
3,900). **Q-f:** is the docs lead-order check (`text.index`) too
brittle / too weak?

### `9336af0` — W1-5 CompactBench cost rollup
`run_compactbench.py` (+42), `tests/test_compactbench_driver.py` (+35).
*Design calls:* `usage_breakdown` sums top-level numeric usage fields
(nudge_usage on cycle rows, usage elsewhere); `cost_per_seed_usd`
excludes `cell_error` seeds from the denominator; top-level
`run_cost_usd`/`run_usage`/`cost_model`. Additive schema — committed
result files untouched. **Q-g:** partial cells (some probes done, then
error) currently COUNT toward n_seeds because rows exist alongside the
cell_error row — is that the right call, or should any cell_error
exclude the seed entirely? This affects the E-3 budget freeze math.

### `a3242ed` — W1-6 pilot brief · `6ae57e3` — board handoff
`docs/pilot-brief.md`. *Check:* any claim in the brief that outruns the
claims ledger; tone vs the honest-status bar.

## Self-declared concerns (please poke here)

1. Claims-gate pattern completeness (Q-b) vs its precision-first kill
   condition (>3 false positives week-1 → narrow before re-enabling).
2. The chars/3 divisor is calibrated on 5 artifacts from ONE repo's
   ledgers — cohort repos' .ctx may differ; cheap follow-up: run the
   calibration snippet on a cohort ledger.
3. `n_seeds` semantics in W1-5 (Q-g) — the one place a wrong call
   silently skews a budget decision.

## Out of scope for this review

Untracked working files (`docs/notes.md`, `docs/ctx-investor-brief.html`)
and the concurrent-session edit to
`ctxpack/benchmarks/agentic/PREREGISTRATION-resume-probe.md` — owner
decisions, not part of the range.
