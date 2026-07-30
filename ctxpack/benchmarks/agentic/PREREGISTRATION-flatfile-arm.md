# FLATFILE arm — three-arm handoff calibration (pre-registration)

**Status: PRE-REGISTERED — committed 2026-07-30, before any scored run
of this protocol.** Drafted and owner-ratified 2026-07-25. This repo's
standing rule (`PREREGISTRATION-resume-probe.md`, opening paragraph) is
that a protocol counts as pre-registered only once it is committed
BEFORE the first scored run that uses it — the A1 incident exists
precisely because a claim was pre-registered in session notes instead of
the repo. It was cited as pre-registered for five days before that was
true; the retrospective note stays here rather than being tidied away.

**No scored run has occurred.** Nothing here may be edited after the
first scored run; amendments append below with their own date and take
effect only for later runs. Eval results are immutable — a new run
writes a new versioned file.

**Class: CALIBRATION, not proof.** Four handoffs cannot support a
published claim. This run exists to size an effect and to decide whether
the product keeps expanding or narrows — nothing in a result file from
this protocol may be quoted as evidence that CtxPack beats any baseline.

## Why this exists

Two independent field reports (setu 2026-07-21, OntoWiz 2026-07-25)
converged on the same two findings:

1. The query tools went uncalled — OntoWiz reported **zero**
   `ctx/session_*` calls across a full session — while the surface those
   agents *report* having benefited from is the **SessionStart
   injection**. The zero-call count is observed; the benefit is
   self-reported, and this protocol does not treat the two as the same
   evidence class.
2. A hook plus a hand-maintained markdown file was estimated by that
   agent to reproduce **~70% of the value it actually exercised**.

Finding 2 is an existential claim about the moat and it must be tested,
not argued with. The precedent is the GREP null baseline: the sentinel
run's honest grep arm (207/240) stopped a $60 six-arm purchase and
redirected the product toward literal exactness. A flat file is the same
kind of embarrassingly cheap control, and it has never been run.

## Arms (three, budget-parity, interleaved per handoff)

| Arm | Context supplied | Notes |
| --- | --- | --- |
| `ctx-push` | Only the SessionStart injection (`project-gist.md` + previous `session-gist.md` + any capture-gap warning) | **Push path only.** The read path is NOT exercised. |
| `flatfile` | Only a `MEMORY.md` maintained by an agent of the same class (below) | The baseline under test |
| `grep` | Raw-transcript keyword windows at the same BPE budget | Standing null hypothesis |

**Arm-labelling rule (binding, extends the A1 standing rule).** The
first arm is reported as `ctx-push` / "CtxPack startup injection only"
in every result file, table and summary. It must never be labelled
"ctx" or "CtxPack" unqualified. A1 was raised because an arm
*under-modelled* the documented read path; here the under-modelling is
deliberate and the label carries it. A result showing `flatfile ≈
ctx-push` is evidence about the injection surface and says nothing about
the query surface.

**Flat-file fairness (binding).** A human-perfect markdown file is an
unfair control in the flat file's favour, and a neglected one is unfair
against it. Therefore:

- The `MEMORY.md` is produced and updated by an agent of the same class
  and model as the session agent, from the same transcripts.
- Fixed budget per handoff: **one pass, ≤8,000 output tokens, no human
  edit, no retry.** Budget consumed is recorded whether or not it is
  spent.
- The file is **cumulative** across the four handoffs — handoff *n* sees
  the file as handoff *n−1* left it. Degradation at scale is part of
  what is being measured, so resetting it between handoffs is
  prohibited.
- The maintenance prompt is fixed before the run and stamped in the
  result file by hash.

## The four frozen handoffs

Frozen: exactly these four, in this order. Adding, dropping or
re-scoping one requires an amendment committed here **before** the run
that uses it. Each handoff is a fresh-context session that must recover
something from prior sessions of this repo.

| # | Handoff | What it tests | Maps to owner gate |
| --- | --- | --- | --- |
| H-1 | **Durable constraint survival.** A constraint banked many sessions earlier must be honoured against a proposal that violates it (e.g. the banked `Do not run the $60 full pass until cost reporting is fixed`, `s:bdfbd48b#turn445`). | Constraint retention + adherence across a context boundary | Fewer confident stale assertions; continuity |
| H-2 | **Decision supersession recovery.** A value revised at least twice across sessions; the agent must report the CURRENT value and that it was revised. | Proactive-interference resistance | Better recovery across decision supersession |
| H-3 | **Literal exactness at scale.** Exact identifiers (commit shas, artifact paths, flags) banked ≥3 sessions back, graded verbatim. | The axis where grep measurably failed (8-hex truncations of 12-hex shas in the sentinel run) | Better provenance |
| H-4 | **Stale-claim discipline.** A perishable claim banked as true whose underlying repository state has since changed. Graded on whether the arm asserts it flatly, or flags it as requiring revalidation. | The OntoWiz incident class | Fewer confident stale assertions |

**Pre-registered prediction, recorded before any run.** `ctx-push` is
predicted to **fail H-4**, roughly as badly as `flatfile`. CtxPack has
no freshness or invalidation machinery today: `FactBasis.TOOL_OBSERVED`
exists in `ctxpack/core/factid.py` marked *"reserved: no v1.1
producer"*, and there is no `expires_at` producer anywhere. H-4 is
therefore the **pre-slice baseline** for the post-E-6 stale-test trust
vertical, not a fair fight CtxPack is expected to win. Stating this in
advance is the point: if H-4 later improves, the prediction on record
makes the improvement attributable rather than retrofitted.

**Instantiation (deterministic).** H-1..H-3 probes are generated from
the ledger at a pinned repo commit with `--seed 42`, using the existing
resume-probe generator and the A2 `skip-ambiguous-same-turn/v1` rule.
The generated probe set's sha256 is stamped in the result file and
disclosed **before** grading. Values are not hand-picked into this
document: hand-picking the answers is how a calibration becomes a demo.

**H-4 is not generable by that path and needs its own oracle.** The
existing generator asks "what was banked?", which the ledger can answer
alone. H-4 asks "what was banked AND has since become false", which
requires a second source of truth — the repository at two revisions —
that the generator has never had. Claiming otherwise (an earlier draft
of this file did) would have put an ungradable handoff into a scored
run.

### H-4 oracle manifest — `h4-oracle/v1`

Immutable. Built and committed **before** the run, sha256 stamped in
the result file. Regenerating it after seeing results voids the
handoff.

Each item pins all six fields; a missing field is a hard error, never a
default:

| Field | Meaning |
| --- | --- |
| `item_id` | stable identifier, unique within the manifest |
| `banked_claim` | the exact banked text, verbatim |
| `fact_id` | its ledger fact_id |
| `observed_at` | the revision the claim was true at |
| `current_state` | the contradicting fact at HEAD, with the command that establishes it |
| `expected_verdict` | `stale` (claim no longer holds) or `control_current` (claim still holds) |

**Grading rule.** Per item, the arm's answer is scored into exactly one
of three classes, by deterministic string rules over the arm's output —
no LLM judge:

- `confident_stale` — asserts the banked claim in the present tense with
  no revalidation qualifier. **The failure being measured.**
- `qualified` — reports the claim as a historical observation, or flags
  it as needing revalidation, or abstains. Counts as a pass.
- `wrong` — contradicts both the banked claim and the current state.
  Scored separately; it is not a stale-assertion success.

`stale_assertion_rate` = `confident_stale` ÷ graded items. Ungraded
items are disclosed, never dropped silently.

**Controls (both mandatory).** A manifest of only-stale items cannot
distinguish an arm that tracks freshness from one that hedges
everything. So:

- **Positive controls** — `expected_verdict: stale`. An arm that never
  qualifies fails them.
- **Negative controls** — `expected_verdict: control_current`, claims
  that are still true at HEAD. An arm that hedges everything fails
  these, and its apparent H-4 win is exposed as blanket hedging.

A run reports both rates. A `stale_assertion_rate` improvement with a
degraded negative-control rate is **not** an improvement, and may not be
reported as one.

**Manifest completeness checks (hard failures, not warnings).** Before
any arm runs: every field present and non-empty; `item_id` unique;
every `fact_id` resolvable in the ledger; `banked_claim` matching the
ledger text byte-for-byte; at least one positive and one negative
control; and the exact expected row set — grading output whose item_id
set differs from the manifest's in **any** direction (missing,
duplicated, or unexpected) fails the run rather than scoring the
intersection. Silently scoring an intersection is how a truncated run
reports as a complete one.

**Mutation test (gate falsifiability).** The gate must be shown capable
of turning red before it is trusted to turn green: a fixture that
mutates one manifest item's `expected_verdict` must flip the run from
pass to fail. Implemented in `h4_oracle.py` with tests; a gate never
observed failing is not evidence.

## Metrics

**Outcome** (per arm, per handoff — per-kind accuracy is the
comparator, never pooled):

- `accuracy` per handoff kind, rule-graded against the ledger.
- `literal_exactness` — verbatim identifier match (H-3 headline).
- `stale_assertion_rate` — claims stated flatly whose repository state
  has changed (H-4 headline). **Lower is better; this is the only
  metric where a confident answer can score worse than an abstention.**
- `abstention_rate` — "not found in context", scored separately from
  wrong answers. An honest miss is not a hallucination.

**Maintenance cost** (the axis the outcome metrics hide):

- `maintenance_tokens` — output tokens spent maintaining the arm's
  memory artefact across the four handoffs. `ctx-push` and `grep` are
  ~0 by construction; that asymmetry IS the finding if outcomes tie.
- `maintenance_wall_ms`.
- `context_bpe` per handoff, for budget-parity audit.

## Decision gate (owner-ratified 2026-07-25)

Continue investing in session memory only if `ctx-push` demonstrates at
least **one** differentiated advantage over `flatfile`:

1. Fewer confident stale assertions.
2. Better provenance.
3. Lower maintenance burden at similar continuity.
4. Better recovery across decision supersession.
5. Independently verifiable checkpoints.

**If `ctx-push` only matches `flatfile` while costing more to operate:
narrow the product to a deterministic audit/checkpoint utility and stop
expanding memory features.** That outcome is a legitimate result of this
protocol, and this paragraph exists so it cannot later be reframed as a
measurement problem.

Gate 5 is satisfied outside this probe and is therefore **not a
continuation criterion for session memory**: checkpoint receipts (turns
covered, turns new, ledger and gist sha256, lint status) and the
injection log shipped in `a815b78`, and a flat file cannot produce a
receipt at all. A gate
that is already true before the experiment runs cannot be failed by the
experiment, so counting it would make the five-point gate unfalsifiable
— any result would clear it. Gate 5 is retained only for the narrower
deterministic audit/checkpoint product; the session-memory decision
rests on gates 1–4.

## Disclosure rules

- Every result file stamps: `arms`, `probe_set_sha256`, `seed`,
  `maintenance_prompt_sha256`, `flatfile_budget_tokens`, the repo commit
  the ledger was read at, and `measurement_class: "calibration"`.
- Any published summary states the arm labels in full (`ctx-push`, not
  `ctx`) and the n (four handoffs).
- A file lacking a field predates the rule that introduced it.

## Cost

Four handoffs × three arms, plus flat-file maintenance passes. Expected
well under the standing $2 ceiling. **This protocol carries no
authorization by itself** — it is the design only. A scored
run needs its own explicit budget authorization at the time it is run,
and it is unrelated to the parked A5 drift-fork work (no replication of
that is approved).

---

## Amendment F1 — the `ctx-fresh` fourth arm (pre-registered 2026-07-30)

Drafted 2026-07-25, committed with this file before any scored run of
this protocol, so the three-arm and four-arm variants are both on record
in advance.

**Arm.** `ctx-fresh` = `ctx-push` plus the Track C freshness overlay
(`docs/track-c-verified-freshness-spec.md`): stale and unverified facts
are labelled in the injection, and historical observations render as
*"…failed at revision A; current state requires revalidation"* rather
than as present-tense claims.

**Eligibility (binding).** `ctx-fresh` may only enter a run **after**
the deterministic spike passes every gate in that spec's §7 — in
particular zero false `verified` results and ≤2% false-stale. An arm
that mislabels is worse than no arm: it would move the H-4 number for
the wrong reason and contaminate the calibration.

**Primary outcome:** H-4 `stale_assertion_rate`, `ctx-fresh` vs
`ctx-push`.

**Gate (corrected — supersedes the "minimum directional gate" reading).**
The ≥30 percentage-point absolute reduction in confident stale
assertions is the **cluster-level** decision threshold, not this
protocol's. Four handoffs cannot resolve a 30pp effect, and this file's
standing class is calibration. Two binding consequences:

1. The four-arm run reports direction and effect size **with n stated**;
   it may not be described as passing or failing the 30pp gate.
2. The gate is conditional on the baseline: if `ctx-push`'s H-4
   stale-assertion rate comes in below 40pp, a 30pp absolute reduction
   is not available and the protocol re-scopes rather than recording a
   failure. Calibrating a threshold against an unmeasured baseline is
   arithmetic, not evidence.

**Also required, regardless of outcome:** no material regression on
H-1..H-3; zero cases where CTX labels a mismatched supported claim
`verified`; verification coverage and unverified-fact counts disclosed
in every result file.
