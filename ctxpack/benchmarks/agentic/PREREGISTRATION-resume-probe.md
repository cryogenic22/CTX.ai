# Resume-Probe (L2) — Pre-registered Amendment Log

**Status: this file is the pinned home for resume-probe design
amendments.** An amendment counts as pre-registered only if it is
committed here BEFORE the first scored run that uses it. Eval results
are immutable — no amendment ever regrades a prior result file; the
expected effect of a rule change is stated prospectively and read off
future runs only.

Why this file exists: amendment A1 was pre-registered on 2026-07-05 in
session working notes rather than in the repo, so the pre-registration
claim was only auditable through auto-memory (recorded as a
`ctx-incident: native-better`). The repo is the audit surface; session
notes are not.

Standing decision rules (unchanged by any amendment below):

- Per-kind accuracy is the cross-run comparator — probe universes are
  regenerated from the grown ledger each run, so per-probe pairing
  across runs is meaningless.
- Historical comparisons are labeled with their date and arm version
  ("07-05 ctx baseline"); the v2+ ctx arm is described as "ctx with the
  documented read path", never "startup gist alone".
- Result files self-describe (`ctx_arm`, `literal_disambiguation`);
  absence of a field means the file predates the rule.

## A1 — ctx arm v2 "session-literals"

- **Pre-registered:** 2026-07-05 (session notes — see incident above;
  recorded here retroactively for the audit trail). **Applied:**
  3b25fbf. **First scored use:** 2026-07-06 runs.
- The baseline arm under-modeled the documented read path: a resuming
  agent is told to use `ctxpack session literals`, but the arm offered
  only startup gists + keyword hydration (KP_SDLC literals 1/7 at
  baseline). v2 appends the source session's banked-literals block;
  grep budget parity tracks the larger context by construction.

## A2 — literal-probe disambiguation: `skip-ambiguous-same-turn/v1`

- **Pre-registered:** 2026-07-06 (this commit, before any run using
  it). **Applies to:** every future probe generation, all arms
  symmetrically.

**Observation** (immutable record
`resume-probe-KP_SDLC-recall-full-20260706T000816+0000.json`): both
remaining ctx literal misses came from turns 514 and 555, each of which
banks 3 distinct paths. The question "the exact path around turn N"
admits any of them; the model returned a valid same-turn path that was
not the sampled one. That is question degeneracy — the probe grades
which value the sampler drew, not whether the arm can address banked
facts.

**Rule (pinned):** at candidate generation, group literal probes by
(source session, banked turn, literal kind). If a group contains more
than one DISTINCT verbatim value, skip every probe in the group.
Identical duplicate values at the same turn are not ambiguous and are
kept (one value = one right answer).

**Why skip rather than hint:** literal probes are exact-graded, so any
hint that uniquely identifies the target (prefix, substring, containing
directory) leaks part of the graded value; an ordinal hint ("the second
path banked at turn N") depends on banking order, which only the ctx
arm can observe — arm-asymmetric by construction.

**Scope (pinned):** only exact banked-turn collisions are filtered.
Known and accepted residual ambiguity: (a) adjacent-turn same-kind
literals — the question says "around turn N"; (b) a value banked
first-wins at an earlier turn that also recurs at the probed turn.
Neither has been observed as a miss. Widening the rule requires a new
amendment committed here before the run that uses it.

**Disclosure:** the result config stamps
`literal_disambiguation: "skip-ambiguous-same-turn/v1"` and
`ambiguous_literals_skipped` (count of dropped candidates, disclosed
even when 0). Files without the field predate the rule.

**No regrades; expected effect:** the 2026-07-06 KP_SDLC ctx 0.90
stands as graded. Prospectively, the rule removes false misses from
future universes for every arm symmetrically; it is expected to raise
literal accuracy for arms that hold verbatim banked values (ctx) more
than for arms that reconstruct them (grep), because the surviving
probes isolate addressability rather than sampling luck.
