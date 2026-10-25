---
description: Review the current diff against CTX's conservation gates. Mark every flag PASS / N/A / FIXED / JUSTIFIED.
---

Review the current diff against the flags below. Default scope is `git diff HEAD`
(staged + unstaged); use a different scope if one is given.

For each flag mark exactly one:

- **PASS** — does not apply
- **N/A** — structurally irrelevant to this change
- **FIXED** — applied; you fixed it during this review
- **JUSTIFIED** — applies, but the choice is deliberate; one line of why

### Conservation (the four principles)

1. **Bar edited to pass** — does this touch anything in
   `harness/structural-floor/protected-surface.txt`? A preregistration after a
   scored run, a committed eval result, a frozen grader id, `CLAUDE.md`, a gate
   script, a CI workflow?
2. **Decision left the deterministic fold** — is a decision now made by a model
   or a heuristic that a deterministic path used to make? That is a regression
   even when the output looks better.
3. **Absent reported as zero** — is anything unmeasured, missing or skipped
   being counted as 0, "none", or "no emission"?
4. **Vacuous green** — does every guard here ship a test that feeds a violation
   and requires rejection? Was each fix-detecting test demonstrated **red on the
   parent commit**?

### Evidence

5. **Claimed from memory** — is any result stated without its command output?
6. **Reported ≠ verified** — is an agent's or tool's summary trusted where the
   artifact itself could have been checked?
7. **Shared-bug agreement** — does a check agree with the thing it checks
   because they share code? (A producer and its own replay are not independent.)
8. **Denominator moved** — can a missing, duplicated or failed record silently
   change an N, a rate or an interval?
9. **Ceiling or floor unstated** — is a metric near saturation, or is the
   effective N a cluster count rather than a row count?

### CTX invariants

10. **Negation** — anything that could strip or reorder a negation?
11. **Determinism** — wall-clock outside `clock.as_of_date()`, unsorted walk,
    or any other source of byte non-determinism?
12. **Zero-dep core** — a new import in `ctxpack/` that is not stdlib?
13. **Write path** — an LLM, a network call or a nondeterministic input in the
    authoritative write path?
14. **Advisory framed as guarantee** — does any new text say prevent, block or
    guarantee where the mechanism only surfaces, flags, audits or degrades?

### Craft

15. **Reuse missed** — does `.claude/rules/anti-slop.md` already list a utility
    for this? Was a second matcher/parser/helper written?
16. **Silent failure** — an exception swallowed without log or re-raise?
17. **Untested path** — a branch no test exercises?
18. **Off-task change** — a line that does not trace to the request?
19. **Vague name** — `data`, `info`, `manager`, `helper`, `util`, `process`?
20. **Assertion softened** — a test deleted, skipped, xfailed or weakened to
    get green?

End with:

- Totals: X PASS · Y N/A · Z FIXED · W JUSTIFIED
- Every FIXED item, with the file and what changed
- Every JUSTIFIED item, with its one-line reason
- Whether the change is ready for an independent reviewer — you do not approve
  your own diff
