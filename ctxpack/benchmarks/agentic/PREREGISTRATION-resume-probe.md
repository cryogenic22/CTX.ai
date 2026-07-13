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

### A5 harness notes (2026-07-12 — pre-approval, part of the reviewable package)

Written while implementing the harness (`fork_cluster.py`,
`run_resume_probe.py --probe-set drift-fork-v2`), BEFORE reviewer
approval and before any paid call. These resolve ambiguities in the A5
text; the reviewer approves text + harness + these notes together.

1. **Cost-table correction (arm count).** The Arms section pins FOUR
   contexts for fork probes — `ctx-nowarn` (additive-overhead
   secondary), `ctx-nowarn-padded`, `ctx-warn`, `grep` — but the Cost
   arithmetic above says "3 arms". The harness implements the Arms
   section: 8 × (2×4 + 1×2 + 1×2) = **96 completions ≈ $1.1–1.5**,
   still under the $2 ceiling (which is unchanged and still aborts the
   run if exceeded). If the reviewer prefers the 80-completion budget,
   dropping the unpadded `ctx-nowarn` secondary arm is a one-line
   change and the additive-overhead secondary becomes BPE-only.
2. **False-alarm arms coincide by construction.** On the no-fork
   variant's clean linear ledger the product warning is EMPTY (the
   build aborts if it ever is not), so `ctx-warn` and
   `ctx-nowarn-padded` are the identical context there (pad delta 0).
   The control therefore measures fork-vs-linear discrimination and
   the specificity of the inverted A4 grade — a model that reads a
   linear SUPERSEDED chain as a conflict false-alarms here.
3. **False-alarm flag anchors (pinned).** Inverted-A4 pass = a pinned
   conflict token PLUS an exact anchor never shown in the proposal:
   a prior chain value verbatim (vB or v0), or both chain session ids.
4. **Padding mechanics (pinned).** The neutral filler is appended as a
   tail block — the same position the warn block occupies. Per-probe
   `pad_delta` is stamped; |delta| > 3 BPE aborts the run; the filler's
   sha256 is stamped in every result file. The filler is validated at
   build time against conflict-token vocabulary and every cluster key
   and value.
5. **Live-run interlock.** The runner refuses any non-dry-run
   `drift-fork-v2` invocation without `--authorized-run`, whose help
   text names both gates (reviewer approval of A5 text + harness; the
   owner's explicit ≤$2 authorization). `--clusters` overrides are
   dry-run only; live runs require the pinned 8.

### A5 harness notes v2 (2026-07-12 — consolidated-review remediation, pre-approval, before any paid call)

Written in response to the reviewer's consolidated re-check (nine
blockers + direct answers a/b/c, recorded on the coordination board
2026-07-12), BEFORE approval and before any paid call. Where these
conflict with harness notes v1, **v2 supersedes v1**. All of the
following is implemented in `fork_cluster.py` /
`run_resume_probe.py --probe-set drift-fork-v2` and pinned here:

1. **The treatment is the product warning (supersedes v1 note 4's
   tail-append).** The warn arm's context is built through the real
   read path on the updated parked branch: the product renderer places
   the fork block at the top of the gist, and the context is used AS
   BUILT. The padded-nowarn arm removes exactly that span
   (`split_product_warning`, keyed on the product `FORK_GIST_HEADER`)
   and grows the pinned neutral filler IN ITS PLACE to exact BPE
   parity (`placebo_context`). The unpadded `ctx-nowarn` secondary is
   the clean removal. On a branch without the product renderer the
   harness ABORTS — it never simulates the treatment (the F2
   no-simulated-fallback semantics). Scored runs therefore execute
   from `feat/fork-surfacing-parked` only.
2. **Completions: 88 (supersedes v1 note 1's 96 and the A5 cost
   table's 80).** 8 clusters × (2 fork probes × 4 arms + 1
   displacement × 2 arms + 1 false-alarm × **1** arm) = 88. The
   duplicate identical false-alarm call is removed (answers a/b): the
   clean no-fork context is called ONCE (`ctx-clean`), and the
   detector's own output is captured as a separate receipt
   (`nofork_detector_receipt`: product warning absent, fold conflicts
   zero, no candidates file). An EMPTY product warning is itself a
   valid detector receipt. The plan aborts unless the enumeration is
   exactly 11 × n_clusters.
3. **Cluster variation is pre-committed (blocker 2).** The pinned
   `_VARIATIONS` table varies, per cluster: head checkpoint order
   (b→c vs c→b), fork revision depth (depth 2 = the heads supersede a
   pinned linear revision, `_REVISION_VALUES`; the fold roots the
   conflict at the chain origin), unrelated-history load (0–8 pinned
   value-free distractor decisions banked in the base session),
   transcript timestamp bases, decision phrasing templates, and probe
   question phrasing variants. All pinned inputs are hashed into
   `cluster_manifest_sha256`, stamped in every artifact.
4. **Grade amendment A4.1 — polarity (blocker 3, answer c).** A pinned
   conflict token counts only OUTSIDE a negation scope (the token's
   own clause; negator within the 4 preceding words). "There is no
   conflict; vB was superseded" is a dismissal, not a false alarm;
   "not a conflict; v2 is old" is a miss, not a pass. Applied
   arm-symmetrically to the fork grade and the inverted false-alarm
   grade (`resume_probe.conflict_flag_positive`; grade id
   `drift-fork-grade/v2.1`). Disclosed limitation: an enumerated
   negation spanning clause punctuation ("not a conflict, fork, or
   divergence") is outside the window and grades positive —
   symmetric across arms. Adversarial cases are pinned as tests.
5. **Errors invalidate the run (blocker 4).** Retry policy
   (pre-registered): per-call transient-HTTP retry (max 5,
   exponential 2s–32s) inside the API helper; a call that still fails
   ABORTS the scored run — no grading of error rows, no cluster
   analysis, no unlock, artifact tagged `aborted`.
6. **The $2 ceiling is enforced, not procedural (blocker 5).** The
   model is pinned (`claude-sonnet-4-6`; live runs refuse any other),
   worst-case preflight cost is computed from the pinned prices
   ($3/$15 per MTok in/out, 512 max output tokens) and aborts if over
   ceiling; every call's actual usage is read from the API response
   (`ask_anthropic_usage`), priced, and appended IMMEDIATELY to a
   durable `invocations.jsonl`; a running guard aborts BEFORE any
   call whose worst case would cross the ceiling.
7. **Exact tokenizer required and stamped (blocker 6).** v2 refuses
   to run (including dry runs) unless tiktoken is importable
   (`require_exact_tokenizer`); the chars//4 fallback is forbidden.
   Artifacts stamp: tokenizer + version, harness commit, cluster
   manifest sha256, pad-filler sha256, per-row final-context sha256,
   and (padded rows) the actually-inserted filler's sha256 + length.
8. **Any failed receipt aborts (blocker 7, supersedes the one-probe
   exclusion).** Preflight is deterministic, so `build_plan` raises on
   the FIRST failed receipt of any kind (fork presence receipts on
   both primary arms, displacement expected-present, false-alarm
   detector receipts). Unlock additionally requires completeness:
   exactly 8 clusters, each contributing exactly 2 paired fork probes
   in both primary arms.
9. **Negative controls are hard gates (blocker 8).** False-alarm
   gate: **0/8** flagged clusters (was ≤1/8). Displacement
   non-inferiority gate: at most **1** harmful-discordant cluster
   (warn wrong AND padded right); both gates block the unlock.
10. **Deterministic counterbalancing (blocker 9).** Fork-arm and
    displacement-arm call order rotate by cluster index
    (`arm_order` / `displacement_arm_order`), pre-committed; the plan
    enumerates rows in execution order.

### A5 harness notes v3 (2026-07-12 — recheck-residual remediation, pre-approval, before any paid call)

Written in response to the reviewer's 2026-07-12 recheck (relayed as
headlines: exact-manifest gate, retry-level budget enforcement, A4.2
grading, empty-response abort, E-6A privacy cleanup), BEFORE approval
and before any paid call. Where these conflict with v1/v2 notes, **v3
supersedes**. No scored run exists; every grade/gate change below is
prospective — no regrades.

1. **Grade amendment A4.2 — enumerated negation (supersedes the A4.1
   disclosed limitation; grade id `drift-fork-grade/v2.2`).** The
   negation scope extends across comma-separated ENUMERATION
   CONTINUATIONS of a negated segment: a bare fragment (≤3 words) or a
   segment opening with a coordinating connective (or/and/nor, ≤4
   words) inherits the preceding segment's negation — "not a conflict,
   fork, or divergence" neutralizes all three tokens. Longer segments
   are fresh clauses and A4.1 applies unchanged ("no objection at
   first glance, but this fork is real" still flags); hard clause
   punctuation (.;:!?— and newline) always resets the scope. Applied
   arm-symmetrically to the fork grade and the inverted false-alarm
   grade. Disclosed limitation (pinned as a test): a genuine flag
   phrased as a bare ≤3-word fragment straight after a negated comma
   segment ("no delays, fork detected") reads as an enumeration and is
   neutralized — symmetric across arms. Adversarial cases in both
   directions are pinned as tests.
2. **Retry-level budget enforcement (supersedes v2 note 6's row-level
   guard).** The v2 running guard was per PLAN ROW while the API
   helper retried up to 5× internally — retries were neither
   individually ceiling-guarded nor ledgered, and the invocation row
   was written only after a call returned. v3 moves the attempt loop
   into the harness (`fork_cluster.call_with_budget`, single-attempt
   API helper `fidelity.anthropic_attempt`): EVERY attempt — initial
   or retry — is ceiling-guarded BEFORE issue and appended to the
   durable `invocations.jsonl` immediately before (`issued`) and after
   (`result`) the call, so a crash mid-call still leaves the issued
   record. Cost accounting pinned: an ok attempt adds its actual
   priced usage (worst case when usage is missing); a transient HTTP
   rejection was not billed (no usage block) and adds $0; an
   unknown-billing outcome (timeout, reset, non-retriable HTTP)
   reserves the full worst case. Retry counts and backoff are
   unchanged from v2 (max 5, exponential 2s–32s); a call that still
   fails invalidates the scored run (v2 blocker-4 semantics
   unchanged).
3. **Empty-response abort.** An HTTP-200 completion with empty (or
   whitespace-only) text is not a valid measurement: it cannot be
   told apart from API degeneracy, and grading it banks a false miss
   (the v2 loop graded it — `grade()` returns False on empty). v3
   aborts the scored run (`aborted.reason = "empty-response"`), with
   NO silent retry — at temperature 0 a retry is a hidden regrade
   opportunity. The call's cost is charged (it was billed) and the
   attempt is ledgered with status `empty`.
4. **Exact-manifest gate (supersedes v2 note 7's stamp-only
   semantics).** `cluster_manifest_sha256` was stamped into artifacts
   but never verified — drifted run inputs would execute and merely
   record a different hash. v3 pins the reviewed manifest as
   `PINNED_CLUSTER_MANIFEST_SHA256`; every run — dry or live — aborts
   unless the computed manifest matches (`require_pinned_manifest`),
   so a deliberate change to any pinned input (cluster table,
   variations, revisions, templates, questions, distractors, filler,
   arms) requires a conscious re-pin in the same reviewable diff.
   Artifacts stamp the verified sha plus the gate marker.

### A5 harness notes v4 (2026-07-12 — substantive re-review remediation, pre-approval, before any paid call)

Written in response to the reviewer's substantive re-review of main
`f43978a` + parked `caa45b8` (four blocking findings, full text on the
coordination board), BEFORE approval and before any paid call. Where
these conflict with earlier notes, **v4 supersedes**. No scored run
exists; every change is prospective — no regrades.

1. **Result-set manifest gate (finding 1; the v3 input-table pin
   addressed the wrong manifest and REMAINS in force alongside
   this).** Before any analysis, the completed result set must be
   EXACTLY the enumerated plan: unique (cluster, ptype, probe_id,
   arm) keys, 88 rows, no duplicates, no unexpected rows
   (`validate_result_manifest`; the runner passes the plan's key set
   and any deviation aborts with `aborted.reason =
   "result-manifest"`). Additionally the gates themselves are
   vacuity-proof: the false-alarm gate requires one OBSERVED control
   per pinned cluster (absent rows fail it) and the displacement gate
   requires a complete observed pair in every pinned cluster.
   Deletion, duplication, and unexpected-arm cases are pinned as
   tests.
2. **Grade amendment A4.3 — polarity tracks the negated conflict
   (finding 2; supersedes A4.1's four-word window and A4.2's
   bare-fragment rule; grade id `drift-fork-grade/v2.3`).** Once a
   pinned negator appears, the negation scope extends through the
   REST of the hard clause unless a pinned CONTRAST MARKER (but/
   however/yet/though/although/nevertheless/nonetheless/still/
   instead/rather/except) intervenes and restores positive polarity.
   Comma segments break the scope — "no delays, fork detected" now
   FLAGS — except enumeration continuations (a segment opening with
   or/and/nor, or a bare ≤3-word fragment followed by one), which
   inherit it, so "not a conflict, fork, or divergence" stays
   negated. All three reviewer cases are pinned as tests before any
   scoring: "I do not believe this represents an unresolved
   conflict" → negative; "there is no evidence of any unresolved
   conflict" → negative; "no delays, fork detected" → positive.
   Deterministic blinded adjudication remains unused. Disclosed
   limitation (pinned as a test): a flag phrased under a negated
   attention verb ("we cannot ignore the unresolved fork") is
   neutralized — the clause-wide scope has no verb model; mitigation:
   the fork grade still requires an exact anchor to PASS, and the
   false-alarm direction needs a POSITIVE flag to fire, so this
   limitation cannot create false alarms.
3. **Full-request worst case with tokenizer headroom (finding 3;
   supersedes the context+question bound).** The per-call worst case
   now prices the ENTIRE request — `_build_prompt`'s wrapper and the
   system prompt included — then applies pinned headroom
   (`TOKENIZER_HEADROOM = 1.25`, because cl100k only approximates
   Claude's billing tokenizer) plus `REQUEST_OVERHEAD_TOKENS = 64`
   for role/message framing. The SAME bound
   (`fork_cluster.request_worst_case_usd`) backs the preflight total
   and every per-attempt guard, so no attempt can be issued whose
   true cost could cross the $2 cap. The invocation ledger is fsynced
   after every append — "durable" is now literal.

### A5 harness notes v5 (2026-07-13 — artifact-review remediation; the first scored run's artifact stands immutable)

Status: the 2026-07-13 scored run (artifact
`resume-probe-fork-fixture-v2-drift-fork-v2-full-20260713T124646+0000.json`,
sha256 `304da6c795e26e51…`, parked commit `3e1aaee`) is NOT
re-graded, altered, or overwritten. Its artifact review found the
primary result robust (verified padded miss ≥14/16 vs warn 0/16, all
eight clusters warn-better even treating truncated rows as unknown)
but CHANGES REQUESTED on evidence and hygiene grounds; the two rules
below fix the harness prospectively. The owner verified before any fix
that the original full responses exist in no retained log — therefore,
per the reviewer's instruction, any future scored run of this probe
set is a CLEARLY LABELLED REPLICATION and requires fresh reviewer
approval AND fresh budget authorization first.

1. **Verbatim-evidence rule (artifact-review blocker 1; supersedes the
   `answer[:500]` storage).** Grade evidence is the COMPLETE verbatim
   completion. Result rows store the full answer plus
   `answer_sha256`; the fsync'd invocation ledger's ok/empty result
   rows store the same verbatim answer plus sha — the durable ledger
   is the immutable retained log, written before grading can proceed.
   A report whose graded rows lack a complete answer, whose answer
   fails its own sha, or whose sha disagrees with the ledgered row is
   refused by `validate_report_evidence()` and never written — the
   hard false-alarm gate (and every other grade) must be
   independently reproducible from the artifact alone.
2. **Artifact-hygiene rule (artifact-review blocker 2).** Scored and
   dry-run artifacts reference their invocation ledger as a committed
   SIBLING file — relative filename plus SHA-256 — never a
   machine-local absolute path (dry runs stamp null). The same
   pre-write audit refuses any report string containing machine-local
   paths or the owner identity (forbidden set mirrors the E-6A
   fixture-privacy gate, fictional-user allowlist honored). Historical
   dry-run receipts that stamped absolute temp paths remain immutable
   in git history; the gate prevents recurrence.

### A5 harness notes v6 (2026-07-13 — fix-re-review residuals; supersedes v5's audit description where they differ)

1. **Byte-level evidence verification (residual P1; supersedes the
   declared-sha comparison in notes v5).** The pre-write audit no
   longer trusts any DECLARED hash: every ledgered ok/empty row's
   answer must recompute to its own sha256; every graded artifact row
   must be byte-identical to its ledgered ok-row answer; and the
   sibling ledger file's actual bytes must hash to the stamped
   `invocation_ledger_sha256` AND parse to exactly the report's
   embedded invocation rows. Corrupted or diverging ledger content —
   even with self-consistent stamps — refuses the artifact.
2. **Strict absolute-path rule (residual P2; supersedes v5's
   home/AppData-only matcher).** The artifact surface allows NO
   absolute filesystem path of any form: drive-letter (`C:\tmp`,
   `D:\scratch`, `e:/x`), msys-munged (`/c/...`), UNC
   (`\host\share`), POSIX system roots (`/tmp`, `/var`, `/scratch`,
   `/opt`, `/srv`, `/private`, `/home`, `/users`, `/mnt`, `/media`,
   `/root`), or any home-directory segment inside a longer path.
   There is no fictional-path allowance on artifacts (that allowance
   is fixture-gate-only): the synthetic fork fixtures emit no
   absolute paths, verified against both committed artifacts.

Standing state unchanged: no replication is reviewer-approved; no new
$2 authorization exists; the `3e1aaee` scored artifact remains
immutable (the strict matcher correctly flags its known, disclosed
ledger-path leak — it is evidence of the old defect, not a new one);
the parked branch remains do-not-merge; the separate parked-code
review remains outstanding.

### A5 harness notes v7 (2026-07-13 — round-3 re-review residuals; supersedes v6's audit description where they differ)

1. **Absent-key sibling bypass closed (round-3 residual P1;
   supersedes v6's sibling-requirement description).** A report that
   carries invocations MUST declare a sibling ledger: a null
   `invocation_ledger` and an entirely ABSENT key both refuse the
   artifact — deleting the key is not an escape hatch. The accepted
   test fixtures now declare their sibling and supply its bytes, so
   the test suite itself can no longer exercise the bypass; an
   explicit deleted-key regression test is pinned.
2. **Denylist-free path rule (round-3 residual P2; supersedes v6's
   root-allowlist matcher).** "No absolute path" is now enforced
   literally: ANY token-leading POSIX absolute path is rejected
   (`/etc/passwd`, `/usr/local/bin`, `/workspace/run`, and
   innocuous-looking ones like `/guides/x` alike — no root
   allowlist), plus drive-letter, backslash AND forward-slash UNC
   (`//server/share`), and `file://` URIs. The single documented
   exclusion: http(s) URL spans are masked out before the path scan,
   so a URL whose path contains `/home/` or `/tmp/` does not trip the
   gate (regression-tested); owner-identity substrings are still
   checked on the raw string, URLs included. Both committed post-fix
   dry-run receipts pass the tightened gate; `3e1aaee` still fails on
   its known, disclosed leak.

Standing state unchanged: no replication is reviewer-approved; no new
$2 authorization exists; `3e1aaee` remains immutable; the parked
branch remains do-not-merge; the separate parked-code review remains
outstanding.
