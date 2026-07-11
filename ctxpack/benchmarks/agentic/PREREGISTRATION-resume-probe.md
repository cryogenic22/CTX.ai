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

## A3 — unresolved-fork drift probe: `drift-fork/v1` (the DAG-Slice-2b + dream-fold `possible_conflict` unlock)

- **Pre-registered:** 2026-07-11 (this commit, before any probe code
  or scored run using it). No probe code, no gist-surfacing feature,
  and no `possible_conflict` emission ships before this section lands
  in the repo. **Applies to:** the first scored run of the
  `drift-fork` kind, all arms symmetrically.

**Why this probe exists (the gate it discharges).** Two banked
constraints gate the *proactive* surfacing of supersession conflicts:
`ENTITY-CONSTRAINT-48494AF6` (turn 690) — *"gist surfacing and
supersession-candidate emission stay gated — build them only after
real ledgers produce `fact_superseded` edges, or a drift probe shows
an agent missing a supersession without a top-level warning"* — and
`ENTITY-CONSTRAINT-92315F0E` (turn 691, *"Do not build more DAG"*).
The live ledger has **0 `fact_superseded` edges across 379 events**
(recounted at commit, 2026-07-11), so
the "real edges" arm is not met; this probe is the *other* named unlock.
It is the single eval that gates **both** remaining features, because
the checkpoint's `possible_conflict` candidate (dream-fold candidate
type, `consolidation-dream-fold-v0.md`) *is* the machine-emitted form
of the gist conflict warning — same signal, gist-side vs event-side.

**What is already shipped (not under test here).** The fold
(`supersession_dag.py`) and *on-demand* surfacing through `session why`
(`test_why_surfaces_fork_end_to_end`) are done: an agent that **asks**
already sees the fork. This probe measures only whether an agent that
does **not** proactively get warned *misses* the fork — i.e. whether the
warning earns its build, or is bloat because the read path already
suffices.

**Fixture (pinned; synthetic by necessity).** No real fork exists in
any cohort ledger, so the fork is planted the way
`test_why_surfaces_fork_end_to_end` does — a base fact F superseded
**independently** by two heads H1 (value `v1`) and H2 (value `v2`) in
two different sessions, neither referencing the other. Both heads
declared `Supersedes: F` — so the **conflict lint is satisfied** and
cannot catch it; only the DAG fork detection can. Disclosed limitation:
the fixture is synthetic (like CompactBench), stamped
`fork_source: "synthetic-fixture"`; a real cohort fork, once one
exists, supersedes the fixture as the preferred source.

**Probe (pinned).** A teammate proposal that treats **one** competing
head as settled: *"Proceeding with {base_key} = {v1} as the current
value — drafting the next step on that basis. OK?"* (`v1` drawn
deterministically as the lower-sorted head so the arm cannot infer the
draw). The proposal never shows `v2`.

**Grade (precision-first, consistent with the drift harness).** Pass =
the answer surfaces the *other* competing value `v2` verbatim **or**
explicitly flags that `{base_key}` has ≥2 unreconciled current values
(fork not resolved) — parroting `v1` cannot false-pass, and a paraphrased
flag grades as a miss (disclosed under-count, symmetric across arms,
favors verbatim-holding arms — the same exactness axis as the sentinel).
The stronger behavior-grade (does the agent *abstain from acting* / attempt
a `session why` before proceeding) is the CompactBench fork-probe
counterpart (`probes.py`), cross-referenced but **not** graded in this
single-completion harness (per the resume_probe.py:239 boundary).

**Arms (pinned — the "without a top-level warning" comparison is the
whole point).**
- `ctx-nowarn` — the **shipped** state: gist + read path available, but
  the gist does **not** proactively surface the `possible_conflict`.
  This is the "without a top-level warning" arm the gate names.
- `ctx-warn` — the **candidate feature**: the resume gist proactively
  lists the unresolved fork (base, both heads, both sessions).
- `grep` — transcript grep, budget-parity per the standing grep rule.

**Pinned unlock claim (the go/no-go, stated before the run).** The
features (gist surfacing + `possible_conflict` emission) are built
**iff** `ctx-nowarn` misses (commits to `v1` without surfacing the fork)
on **≥ 40%** of fork probes **and** `ctx-warn` cuts that to **≤ 10%**
(McNemar on the paired nowarn→warn flip, one-sided, α=0.05). If
`ctx-nowarn` already catches forks below 40%, the read path suffices and
the proactive warning is **cut as bloat** — the eval saved the build.
Thresholds are pinned here and read off future runs only; no regrades.

**Cost & escalation.** Runs on the existing `run_resume_probe.py`
harness (single-completion; a `--smoke`/dry-run is free-ish, a scored
run is the same per-cell cost as the drift runs already committed).
Escalation to the CompactBench behavior-grade fork probe is a separate,
later decision and requires its own pre-registered claim.

## A4 — fork-grade tightening: `drift-fork-grade/v2` (linear-narrative false-pass)

- **Pre-registered:** 2026-07-11 (this commit, before any scored run of
  the `drift-fork` kind). **Applies to:** every future `drift-fork`
  run, all arms symmetrically. Result files stamp
  `fork_grade: "drift-fork-grade/v2"`; files without the field predate
  the rule (the 2026-07-11 dry-run and smoke).

**Observation** (immutable record
`resume-probe-fork-fixture-drift-fork-smoke-20260711T191221+0000.json`):
all 3 `ctx-nowarn` smoke passes were FALSE passes. In each, the model
resolved the fork by RECENCY into a linear supersession narrative — two
answers endorsed proceeding with `v1` and mentioned `v2` only to
dismiss it ("that supersedes the earlier values"), one asserted `v2` is
current because its session checkpointed later. None detected that two
sessions independently superseded the same base. The A3 grade's
v2-containment disjunct cannot distinguish dismissal from flagging —
mentioning the other head inside a linear story is the vocabulary of
the MISS, not of fork detection. (The 3 `ctx-warn` answers all
genuinely flagged: named the fork, both heads, both sessions, advised
holding — the discriminating signal exists; only the grade leaked.)

**Rule (pinned):** fork-mode pass now requires an explicit conflict
token in BOTH disjuncts: (`v2` verbatim AND a conflict token) OR (both
head session ids AND a conflict token). The token list is pinned:
`conflict`, `unreconciled`, `unresolved`, `fork`, `diverg`,
`competing`, `contradict` (substring match on the normalized answer).
`superseded`/`supersedes` is deliberately NOT a token — it is the
linear narrative's own vocabulary. Known and accepted under-count: a
genuine flag phrased entirely without any pinned token grades as a
miss (arm-symmetric; the same disclosed direction as every drift
grade). Known residual false-pass: an answer that names the fork with
a token and both anchors yet still recommends proceeding — accepted,
because SURFACING is the graded behavior in this single-completion
harness; abstention behavior is the CompactBench boundary already
pinned in A3.

**No regrades; expected effect:** the smoke stands as graded (3/3/3 at
n=3 under the A3 grade). Prospectively, `ctx-nowarn` accuracy is
expected to DROP sharply (its passes were linear-narrative false
passes) and `ctx-warn` to hold (its flags carry tokens and anchors
naturally), widening the very gap the unlock claim measures — stated
here BEFORE the scored run so the direction is on record. The A3
unlock thresholds (≥40% / ≤10%, McNemar α=0.05) are unchanged.

## A5 — drift-fork/v2: independent clusters, fixed-budget arms, negative controls

- **Status: DESIGN — reviewer approval required before any paid call.**
  Pre-registered 2026-07-11 (this commit). The scored run this section
  governs is additionally gated on (i) reviewer (Codex) approval of
  this text AND the harness implementing it, then (ii) owner
  authorization up to **$2** (Q3 ruling, 2026-07-11). **Supersedes the
  A3 run design** for every future scored `drift-fork` run — the A3
  fixture mechanics and the A4 grade carry over; the sampling unit,
  arms, endpoints, and analysis below replace A3's. The 2026-07-11 run
  (`0ee35c8`) stands as graded: confirmatory for A3's narrow
  within-fixture claim only; per the Q3 ruling it does not authorize
  the production build (parked at `cf2753c`).

**Claim under test (scoped).** *The gist fork warning causes a resuming
agent to SURFACE unresolved supersession forks it otherwise misses.*
Surfacing only — any "prevents wrong action" claim requires a behavior
endpoint (tool-attempt grading), which belongs to the CompactBench
fork probe and its own pre-registration.

**Sampling unit (pinned): the cluster.** ≥8 INDEPENDENT clusters — not
8 keys inside one fixture. Each cluster is its own fixture instance:
distinct ledger directory, distinct session-id pair, and a distinct
key/value family with **no value or key shared across clusters** (the
A3 non-substring validation applies across the whole run). Per
cluster: 2 fork probes (2 planted forks) + 1 displacement-control
probe + 1 no-fork false-alarm probe (see controls). All probe-level
results are reported, but **every inferential statistic is computed at
cluster level**; probe-level p-values never appear in headline claims.

**Arms (pinned).**
- Primary comparison — **fixed total context budget**: `ctx-warn` (the
  product gist warning, present naturally) vs `ctx-nowarn-padded`
  (warning stripped, then padded to the SAME BPE as that probe's warn
  context with a deterministic, value-free neutral filler block; the
  filler is pinned in the harness and contains no fork content, no
  cluster values, and no conflict-token vocabulary). Any pass/miss
  difference is then attributable to the warning's content, not its
  size.
- Secondary (disclosed, not inferential) — **additive overhead**: the
  A3-style unpadded `ctx-nowarn` vs `ctx-warn`, measuring the real
  deployment delta including the extra tokens, plus the warning's BPE
  cost per probe.
- `grep` runs on fork probes only, budget-parity at the warn size, as
  the standing over-powered null (disclosed as such; not part of the
  unlock decision).

**Negative controls (pinned).**
- *False alarms*: each cluster also builds a NO-FORK variant (same
  keys, linear supersession only). The same teammate proposal (using
  the true current value) runs in both ctx arms. An answer that flags
  a conflict (A4 grade inverted: conflict token + exact anchors) is a
  FALSE ALARM. Gate: false-alarm rate must be ≤ 1/8 clusters, else the
  run fails regardless of the primary endpoint (a warning that cries
  wolf is cut — the lint's precision-first standard).
- *Attention displacement*: inside each fork cluster, one probe asks
  about a NON-fork, linearly-superseded key (correct answer = its
  current value, exact-graded) while the warning about OTHER keys is
  present (warn arm) or absent (padded-nowarn arm). Reported as a
  secondary: a warn-arm accuracy drop on displacement probes is
  disclosed with its cluster-level interval.

**Presence receipts (pinned).** The result file stamps, per probe and
per arm: `v1_present`, `v2_present`, `base_present` (normalized
containment in that arm's final context), and
`supersession_edges_present` (both `fact_superseded` edges visible to
the fold). A fork probe missing any receipt in the arm under test is
EXCLUDED and disclosed (`receipts_failed` count); a run with >1
excluded probe aborts — the eval measures noticing, never absence.

**Analysis (pinned).** Per cluster and arm: miss-fraction over its 2
fork probes. Primary test: one-sided exact sign test at cluster level
on paired (padded-nowarn, warn) miss-fractions, α=0.05. Interval
reporting: Wilson 95% intervals over clusters (n≥8) for (a) proportion
of clusters where padded-nowarn missed ≥1 fork probe, (b) proportion
where warn missed ≥1. **Unlock (merge eligibility) iff ALL of:**
sign-test p < 0.05; cluster-mean miss (padded-nowarn) ≥ 0.40;
cluster-mean miss (warn) ≤ 0.10; false-alarm gate passed. Merge of the
parked implementation additionally requires the separate code review
of `cf2753c` (Q3 ruling). Thresholds read off the scored run only; no
regrades of any prior file.

**Cost (pinned ceiling).** 8 clusters × (2 fork probes × 3 arms + 1
displacement × 2 arms + 1 false-alarm × 2 arms) = 80 completions ≈
$0.9–1.2 on the default model — within the authorized $2. If the
harness or model changes push past $2, the run does not start.
