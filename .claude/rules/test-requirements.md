---
description: Testing doctrine — every change needs a can-fail test
alwaysApply: false
globs:
  - "**"
---
# Test Requirements — every change needs a can-fail test

*Hand-authored doctrine (not regenerated), transplanted from the
setu/market_zero harness onto this repo's native primitives. The
"no vacuous green" rule lives here.*

## Run
- `python -m pytest tests/ -q -m "not slow"` (full non-slow, ~60s)
- Scope to touched files first; the bare full suite walks an external
  repo via a `slow`-marked test — use `-m "not slow"`.

## The non-negotiable properties (this repo's invariants)
1. **Packing is byte-deterministic** — same input + version ⇒ same
   bytes (`tests/test_p0_trust_repairs.py` gates it). No wall-clock
   outside `clock.as_of_date()`, no unsorted walks.
2. **Negations are never stripped or reordered**
   (`tests/test_negation_preservation.py` gates it).
3. **Eval results are immutable** — new runs write new versioned
   files; preregistrations amend only by commit BEFORE a scored run.
4. **A guard that cannot fail is not a guard** — every boundary check
   ships a test that feeds a violation and requires rejection.

## What needs a test
| Change | Test |
|---|---|
| Security boundary (redaction, journals, receipts) | a can-fail case per threat, from the PF-11 TC list |
| Parser/extractor change | adversarial case incl. the failure it fixes; determinism gate green |
| Telemetry/accounting change | absent-vs-zero distinction pinned; malformed input counted not crashed |
| Bug fix | a regression test that fails without the fix (demonstrate red on the parent commit; record the red count in the handoff) |
| Grader/eval change | frozen adversarial cases; grader id/hash restamped |

## Hard rules
- Never delete, skip, `xfail`, or soften an assertion to get green.
- Never add a silent `except: pass` around a checked path.
- Tests that legitimately pass on the parent commit must say which
  kind they are in their docstring: a *regression pin* (freezing
  existing behavior) or a *forward guard* (bounding new behavior).
- Verify with the real runner and paste the output into the board
  handoff; never claim a result from memory. "Committed" ≠ "Done".
- A flaky test is disclosed, never rerun-to-green and dropped.
