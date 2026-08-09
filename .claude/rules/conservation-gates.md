---
description: Conservation gates — the harness floor for CTX_mod
alwaysApply: true
---
# Conservation Gates & Operating Discipline

*Principle-transplant of the market_zero/setu conservation-gates
doctrine onto CTX_mod's native primitives — the same harness the
owner's other repos run. Nothing here is new policy: every gate below
already exists in CLAUDE.md, the coordination board protocol, or the
PF-11 threat model; this file is the one-page map.*

> **The one line:** never let "the suite is green" or "the ledger
> looks healthy" equal "the memory is trustworthy."

## The four principles, in this repo's terms

1. **Separation of authorship — you do not edit the bar to pass.**
   The success-definition surface here: preregistrations (amended only
   by commit BEFORE a scored run), frozen grader ids/hashes, committed
   eval results under `ctxpack/benchmarks/**/results/` (immutable),
   `CLAUDE.md` (owner-authored), the reviewer gate (notes-only; the
   owner applies fixes; approval comes from the reviewer, never
   self-declared).
2. **Conservation before correctness.** The deterministic spine is the
   write path: no LLM in it, no wall-clock, no unsorted walks. A
   change that moves a decision out of the deterministic fold into a
   model or a heuristic is a regression even if outputs look better.
   Absent-vs-zero is load-bearing everywhere: unmeasured is never
   reported as zero, and a missing receipt is never "no emission".
3. **No vacuous green.** Every guard ships a test that feeds a
   violation and requires rejection (`.claude/rules/`
   `test-requirements.md`). Fix-detecting tests are demonstrated RED
   on the parent commit; designed passes self-identify as regression
   pin or forward guard. Watch the repo's own recorded failure modes:
   the pairwise-fold property a wrong answer satisfied, the D×C+P
   arithmetic identity, the "fenced markers are excluded" claim that
   was never checked.
4. **Structural floor over discipline.** Honest accounting: this repo
   is mostly CEILING — the gates run when an agent runs them; there is
   no CI, no CODEOWNERS, no protected-surface enforcement. The floor
   that does exist: byte-determinism and negation gates in the suite,
   the claims gate script, hooks that checkpoint automatically.
   Say plainly when a guarantee is only ceiling (PF-11 B6 does exactly
   this for security claims: advisory mode — surface/flag/audit/
   degrade, never guarantee/prevent/block).

## The two lanes (never mix)

| Lane | Checks | Runs |
|---|---|---|
| **Deterministic** | full non-slow suite; determinism + negation gates; claims gate; capability registry; `scorecard --check` | every unit of work, before the board handoff |
| **Operational / paid** | live-API smokes, scored eval runs, CompactBench | ONLY under explicit authorization: reviewer approval + owner budget; results to immutable versioned files |

A missing API key or an unauthorized paid run must never block the
deterministic lane; a paid run without its authorization chain is a
protocol violation regardless of its result.

## Definition of Done (every unit)

1. A test fails without the change and passes with it (red on the
   parent commit, recorded).
2. The passing command and its output are in the board handoff —
   "committed" ≠ "done"; never claim results from memory.
3. Deterministic lane green; touched-area sweep first, full non-slow
   before the handoff.
4. The bar untouched: no prereg edited after a run, no result file
   overwritten, no assertion softened, no reviewer step skipped.
5. Decisions/constraints stated in the turn-final message
   (`Decision:` / `Constraint:` / `Supersedes:` — CLAUDE.md
   conventions), handoff appended to `AGENT_COORDINATION.md`.
6. An independent reviewer pass on the unit — the implementer never
   approves its own diff.

## Owner-level floor items (flagged, not built — owner's call)

- CI running the deterministic lane on push (the real floor; today it
  is discipline only).
- Branch protection / CODEOWNERS over the success-definition surface.
- These are recorded as gaps, not silently added — per the harness
  rule that enforcement changes route through the owner.
