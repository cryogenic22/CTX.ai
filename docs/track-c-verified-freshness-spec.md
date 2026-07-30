# Track C — Verified Freshness and Evidence Contracts

**Status:** Owner-ratified design, adopted with eight amendments
(below). Drafted 2026-07-25, committed 2026-07-30. Implementation gated
on E-6 (security/redaction) and a deterministic value spike.
**Supersedes** the planned filename
`docs/track-c-verifier-spec-draft.md` as the E-7 deliverable.
**No production code is authorized by this file.**

The proposal this adopts is sound: it answers the right question, it
respects the zero-dependency and determinism ground rules, it refuses
float confidence and LLM truth-scoring, and its non-goals list is the
part most designs omit. The amendments below change how evidence gets
attached, split one over-loaded record into two, remove one adapter that
would have generated guaranteed false positives, and correct which
adapter the spike must prove.

## 1. Objective

Prevent a banked fact from being presented as current when the
repository evidence supporting it has changed. CTX answers three
separate questions; today it answers only the first well:

| Question | Mechanism | Status today |
| --- | --- | --- |
| **Origin** — where did this come from? | `fact_id`, source session/turn, `BASIS`, verbatim span | Shipped (spec v1.1) |
| **Support** — what repository evidence backed it? | Evidence recipes, `FactBasis.TOOL_OBSERVED` | **Reserved, no producer** |
| **Freshness** — does that evidence still match? | Verification receipts + status overlay | **Absent** |

The motivating incident (OntoWiz field report, 2026-07-25): a banked
fact — *"the reseal test is a pre-existing red"* — was served
confidently after it had become false. The ledger preserved the claim
perfectly and had no way to know it had gone stale. The agent caught it
only by re-reading live code.

**The system never rewrites a fact.** It marks the claim stale, shows
why, and lets the agent explicitly supersede it.

## 2. Two axes, never conflated (owner ratification, 2026-07-25)

This is the correction that governs the whole design.

**The vocabulary is defined once, in code:** `ctxpack/core/states.py`
(`ctx-states/v1`), with property tests in `tests/test_state_algebra.py`.
This section describes that module and may not diverge from it; where
prose and enum disagree, the enum wins.

| Axis | Values | Derived from |
| --- | --- | --- |
| **Fact lifecycle** | `draft`, `banked`, `superseded`, `retracted` | Marker statements and the supersession DAG |
| **Evidence freshness** | `not_applicable`, `unanchored`, `not_checked`, `current`, `stale`, `invalid` | Verification against current repository state |
| **Delivery** (not a fact axis) | `attempted`, `injected`, `empty`, `failed` | What the SessionStart hook emitted |

A fact can be `banked` and `not_checked` at once — that is the normal
state of a decision whose supporting test hasn't been re-run.
Collapsing these into one status is how a memory system starts lying.

Two corrections against the vocabulary ratified on 2026-07-25, both
consequences of taking the two-axis split seriously:

- **`expired` is removed from lifecycle.** "The supporting evidence has
  aged out" is a statement about evidence, not about a fact's standing
  in the ledger. It was the two-axis confusion in miniature.
- **`prior_state` and `needs_revalidation` are removed from freshness.**
  `prior_state` describes what an observation record *is* (a historical
  reading), not how fresh it is; `needs_revalidation` was an action, and
  it collapses into `not_checked` (never evaluated at HEAD) or `stale`
  (evaluated and contradicted). Naming the same condition twice is how
  two renderers end up disagreeing about one fact.

**Delivery is a third axis and never evidence of use.** `injected`
means bytes were emitted at session start. It is not evidence that a
model read them or benefited from them. `states.describes_use()` returns
`False` for every delivery outcome, as an executable rule rather than a
comment.

### 2.1 Freshness eligibility is derived from kind and producer

**Not from literal presence.** The proposal did not specify derivation;
an earlier draft of mine proposed "contains a sha/path/version →
perishable" and it is unsafe: *"Never edit CLAUDE.md"* contains a path
and is durable, while *"the reseal test is already red"* contains no
literal and is perishable. The mapping is by fact kind and extraction
basis:

| Fact kind / basis | Default freshness class |
| --- | --- |
| `CONSTRAINT`, basis `user_imperative` | `not_applicable` — durable until superseded or retracted |
| `CONSTRAINT`, basis `marker_stated` | `not_applicable` |
| `DECISION` | lifecycle-governed; supporting evidence assessed separately |
| basis `tool_observed` (test/build results) | repository-state dependent — always eligible |
| `ERROR`, task status | historical — never re-asserted as current |
| `LITERAL` | identifiers, not truth claims — `not_applicable` |

## 3. Non-goals

Unchanged from the proposal, plus one addition:

No knowledge graph, no vector DB, no LLM truth-scoring in the runtime,
no arbitrary shell verification, no automatic fact rewriting, no
background daemon, no float confidence, no proximity-inferred semantic
edges, no cross-repo learning, no dashboard before the CLI and agent
behaviour prove useful.

**Added (query-surface freeze, ratified 2026-07-25):** no new MCP tools.
Freshness rides the surfaces that already exist — the SessionStart
injection, `resume`, `why` — plus a CLI verb. Two field reports measured
the pull path going uncalled; adding a tool nobody calls is how this
design fails silently. (Whether agents read what the push path emits is
unmeasured, so "the surfaces they consume" is not a claim this spec is
entitled to make.)

---

## Amendments to the proposal

### A-1 · Evidence attachment is DERIVED by default, declared only as override

**The proposal's weakest link.** It requires the agent to run an
`observe` command, then hand-place an opaque `Evidence: obs:7d42a8f993`
ID in a marker line. That is strictly more expensive than the
`ctx-incident:` convention — whose adoption outside this repo is
**zero**, despite being documented, cheap, and requested. It also
contradicts the standing owner constraint: *"ctx should work in the
background and an agent should not have to do anything different."*

**Adopted design.** The transcript already contains the observation. The
parser already walks `tool_use` / `tool_result` pairs — that is how
`files_changed`, `bash_commands` and `errors` are counted today. At
checkpoint, for each marker-stated fact at turn *N*, collect tool
observations from the same turn and attach them as
**`candidate_evidence_for`** — the conservative edge type already
ratified in the learning-layer design, which exists precisely for
"probably related, not asserted".

| Attachment | How | Can produce `stale`? |
| --- | --- | --- |
| Asserted | explicit `Evidence:` marker | **Yes** |
| Candidate | derived from same-turn tool observations | **No** — capped at `not_checked` |

This inverts the adoption problem: zero-cooperation works (tier T0),
the convention is an accelerant (T1). It also protects the false-stale
budget — auto-attachment is the noisiest source, and it is structurally
incapable of asserting `stale`.

`Evidence:` attaches only to the immediately preceding `Decision:`,
`Constraint:` or `Failed-Approach:` marker; ambiguous or dangling
references are rejected with a reason code, as proposed.

### A-2 · Split the certificate into extraction integrity and evidence binding

The proposed `ctx-certificate/v1` bundles two records with different
lifetimes, failure modes and consumers:

- **Extraction integrity** (source span hash, literal preservation,
  negation order) — verifiable at checkpoint time, deterministic,
  replayable, and **never goes stale**.
- **Evidence binding** (recipes, expected digests, baseline commit) — a
  live repository query whose answer changes constantly.

Bundling them means a rotated or unavailable transcript degrades the
freshness signal, and a changed config file muddies an extraction-audit
question. `source_unavailable` will be common in the field: Claude Code
rotates transcripts and other agents (Codex) have their own retention,
so the L0-is-forever assumption holds for *our* writes, not for the
files.

**Adopted:** `ctx-extraction/v1` (checkpoint-time, deterministic — may
live in the replayable event stream) and `ctx-evidence/v1` (recipes +
expected digests). The freshness fold consumes **only** `ctx-evidence`.

### A-3 · Remove `git-ref/v1` as a freshness anchor

`git-ref/v1` is marked "always selected", and HEAD changes on **every
commit**. Every fact anchored to a git ref would therefore go stale on
every commit. That blows the ≤2% false-stale gate on day one and trains
users to ignore the warnings — which is the proposal's own kill
condition (§13).

A commit sha is a **baseline coordinate, not a claim**. Adopted:
anchor freshness to content (file digests, config values, symbol
hashes); record the commit as receipt metadata. A ref-existence check
may return later if a real need appears.

### A-4 · The spike must prove the ratified pytest vertical

The proposed spike adapters — `toml-key`, `json-pointer`,
`python-symbol-ast` — omit the exact incident class that motivated the
entire track. The owner-ratified minimum trust slice is:

> Recognize a test execution with an explicit exit code. Bank it using
> the existing `tool_observed` basis. Preserve command digest, output
> digest, source turn and deterministic repository anchor. On the next
> session, derive whether the evidence still matches. Render it as
> *"Historical observation: test_reseal failed at revision A. Current
> state requires revalidation."* — never as *"test_reseal is failing."*
> Preserve the historical observation even after a newer passing result.

Config adapters are the *easy* case and prove the least. Adopted spike
set:

| Adapter | Why |
| --- | --- |
| `pytest-result/v1` | The motivating incident. Highest product value. |
| `toml-key/v1` | Cheapest, highest-precision config case. |
| `json-pointer/v1` | Same class, different serializer — proves canonicalization. |

`python-symbol-ast/v1` is **deferred past the spike**. It is the
best idea in the proposal's adapter list — `ast.dump(node,
include_attributes=False)` correctly ignores comments and formatting,
and `ast` is stdlib so the zero-dep rule holds — but it also carries the
most false-stale surface: renaming a local variable, adding a type
annotation or reordering a decorator all change the dump without
changing the claim. Two adapters are enough to exercise the fold; each
additional adapter adds false-stale risk against a 2% budget.

**`pytest-result/v1` fails safe by construction.** It is a historical
event, not a repository-state read, so it can never be `current` — at
best `not_checked`, and `stale` once HEAD contradicts it. It cannot
assert that a test
now passes. That property is why it is the right first adapter.

### A-5 · Receipts are observational and never inputs to packing

`verify --changed` reads the dirty working tree, so its result is not
reproducible from committed state: two runs at the same commit can
legitimately differ. That is correct for a live report and fatal inside
a byte-deterministic artifact.

Adopted, and stated explicitly because it is easy to violate later:
verification receipts follow the same rule as the injection log —
observational, never an input to packing, never folded into the
replayable event stream. `--fail-on-stale` in CI runs against
**committed state**; a dirty tree is disclosed in the receipt via
`workspace_fingerprint`, never silently mixed in.

### A-6 · Six internal states, three rendered

A six-state enum is well-formed and each state is genuinely distinct.
But six labels in an injected gist is noise, and the gist is the surface
agents actually read.

Adopted: agents see **VERIFIED / STALE / UNVERIFIED**, via
`states.render()`. The six-state precision is retained in `why`,
receipts and CI output where someone is actually debugging.

The canonical six are `not_applicable` / `unanchored` / `not_checked` /
`current` / `stale` / `invalid`. (The proposal's `verified`, `unknown`,
`unchecked` and `uncertified` are the same states under other names;
`ctx-states/v1` is the only spelling that ships.) `current` renders
VERIFIED, `stale` renders STALE, and the remaining four render
UNVERIFIED — they differ in cause, not in what the reader should do.
Absence of evidence never renders as verification: `not_applicable` is
UNVERIFIED, not VERIFIED.

### A-7 · The 30-point gate cannot be decided by the calibration

The proposal sets a "minimum directional product gate" of ≥30pp
absolute reduction in confident stale assertions, to be read off the
four-arm run. Four handoffs cannot resolve a 30pp effect; the
calibration protocol is explicitly labelled *calibration, not proof*.

Adopted with two corrections:

1. The 30pp threshold is recorded as the **cluster-level** decision
   gate, not the calibration's (it becomes pre-registered when
   `PREREGISTRATION-flatfile-arm.md` is committed). The calibration
   reports a direction and an effect size with its n stated.
2. The gate is **conditional on the baseline**: if `ctx-push`'s H-4
   stale-assertion rate is below 40pp there is no room for a 30pp
   absolute reduction, and the protocol re-scopes rather than reporting
   a failure. The recorded prediction is that `ctx-push` fails H-4
   badly — but *how* badly is unmeasured, and a gate calibrated against
   an unmeasured baseline is arithmetic, not evidence.

### A-8 · Track C's build gate moves from E-4 to (spike + calibration)

The ratified plan gates `G-8 Track C full build` on **E-4** (the powered
CompactBench run). The proposal's delivery sequence gates it on the
freshness spike plus the flat-file calibration instead. That is a
cheaper and more direct test of this specific bet, and it matches the
owner's 2026-07-25 sequencing.

Recorded as an explicit gate change: **G-8's gate becomes (deterministic
spike passes) AND (flat-file calibration run) AND (four-arm H-4 result)**.
E-4 remains required for CompactBench-class causal claims, which Track C
does not make.

---

## 4. Data contracts (as amended)

### 4.1 Extraction record — `ctx-extraction/v1`

Checkpoint-time, deterministic, replayable. Proves the fact is traceable
to a source span and that protected content survived extraction.

```json
{
  "schema": "ctx-extraction/v1",
  "fact_id": "a81f...",
  "source": {"session": "fb94cd9f...", "turn": 812,
             "message_sha256": "...", "span_utf8": [142, 211],
             "span_sha256": "..."},
  "extractor": "tp/1.1",
  "basis": "marker_stated",
  "checks": {"source_span_matches": true,
             "literal_preservation": true,
             "negation_order_preserved": true}
}
```

Missing transcript → `source_unavailable`. **Never a silent pass.**

### 4.2 Evidence record — `ctx-evidence/v1`

```json
{
  "schema": "ctx-evidence/v1",
  "fact_id": "a81f...",
  "attachment": "asserted",
  "recipe_id": "<sha256>",
  "adapter": "toml-key/v1",
  "target": "pyproject.toml",
  "selector": "project.requires-python",
  "expected_digest": "<sha256>",
  "baseline_commit": "<full git sha>"
}
```

`attachment` is `asserted` (explicit `Evidence:`) or `candidate`
(derived — cannot produce `stale`, per A-1).

**Recipe identity** (adopted verbatim from the proposal — this is one of
its best ideas):

```text
recipe_id = sha256(adapter_version || canonical_target || canonical_selector)
```

The expected value is deliberately **excluded**, so a subject keeps its
identity when its value changes while the superseding fact carries a new
digest. This mirrors the existing `fact_id` rule where extractor version
is provenance, not identity — same principle, same reason.

### 4.3 Verification receipt — `ctx-verification/v1`

Content-addressed files under `.claude/ctx/verifications/<sha256>.json`,
as proposed — correct, because concurrent CI and session verification
would corrupt an appended log.

A receipt records two different things and must not merge them into one
enum (the earlier draft's `eligible/attempted/verified/stale/unknown/
not_checked` did, which is why a fourth vocabulary appeared here):

- **Execution** — did the recipe run? `eligible`, `attempted`. A
  property of the verification pass.
- **Outcome** — what did it say? A `Freshness` value from
  `ctx-states/v1`, no other spelling.

Unexecuted recipes are reported as `not_checked`, **never** as
`current`. Persist only repo-relative paths, hashes, enums and redacted
values.

## 5. Status fold

Precedence is load-bearing. Adopted with the canonical names, and
implemented once as `states.worst()` so no renderer folds its own way:

```text
stale > invalid > not_checked > unanchored > current
```

`stale` outranks `invalid` because "the evidence contradicts this" is
both more certain and more actionable than "the evidence could not be
read" — both block assertion, only one tells the reader what to do.
`not_applicable` is reachable only when it is the sole input; a fact
whose kind carries no verifiable support has no other state to fold.

A later healthy observation must never conceal another stale dependency.
Freshness is **orthogonal to salience**: a stale fact is annotated, never
demoted by rank and never hidden. Lifecycle demotes (a superseded fact
ranks lower); freshness only annotates. A stale fact may not be rendered
under an unqualified "Current decisions" heading.

## 6. Security

E-6 is a hard prerequisite, unchanged. Resolve targets against the repo
root; reject absolute paths, parent traversal and symlink escape;
enforce size and count limits; never execute arbitrary commands; never
persist raw environment values or process output; redact secret-shaped
values before display or receipt; store reason codes, not exception
strings; treat malformed certificates and receipts as `invalid`, never
healthy; inject status and safe provenance only — never raw file
content — into agent context.

That last rule deserves emphasis: injecting repository file content into
the agent's startup context would turn the freshness feature into a
stored-prompt-injection vector, which is already a named threat in E-6's
threat model.

## 7. Spike gates (unchanged except the adapter set)

Five-to-seven days, offline, no LLM. ≥20 frozen mutations across
CTX_mod / KP_SDLC / setu / market_zero or synthetic snapshots.

| Gate | Threshold |
| --- | --- |
| False `current` (claimed verified when it is not) | **0** |
| Supported-class stale detection | ≥95% |
| False-stale rate | ≤2% |
| Secret or absolute-path leakage | **0** |
| Determinism | byte-identical manifests on permuted inputs |
| Median changed-target verification | <200 ms |
| Report explains the change without an LLM | yes |

Fail any of these and stop. Do not add adapters or reach for an LLM to
paper over weak deterministic coverage.

## 8. Delivery sequence (as amended)

1. **Trust-telemetry hardening** — shipped 2026-07-30 (`fc2489f`,
   `a815b78`, `4ea08d4`): state algebra, read-path classification with
   the delivery join, lint marginals, checkpoint receipts, injection
   log, H-4 oracle.
2. **E-6** — threat model + secret redaction. Blocks everything below.
3. **Flat-file calibration** — `ctx-push` / `flatfile` / `grep`, four
   frozen handoffs (`PREREGISTRATION-flatfile-arm.md`).
4. **Offline three-adapter spike** — `pytest-result/v1`,
   `toml-key/v1`, `json-pointer/v1`. Kill-or-continue review.
5. Certificates emitted at checkpoint with **no product behaviour
   change** (extraction records first — they need no repo access).
6. `verify --changed`, CLI only.
7. Freshness overlay on `why` and `resume`.
8. Bounded SessionStart verification — only after latency measurement.
9. Four-arm H-4 evaluation (`ctx-fresh` added).
10. Adapter expansion only from observed demand.

## 9. Kill conditions

Unchanged and binding: stop or narrow if valuable facts can't be linked
without guessed semantic edges; if teams ignore freshness warnings; if
false-stale noise exceeds 2%; if verification materially delays session
startup; if the enhanced arm doesn't reduce stale assertions; or if a
flat file plus a small verification script delivers equivalent outcomes
at equivalent maintenance cost.

In that case retain the standalone certificate/verifier as an audit
utility and stop expanding session-memory complexity.

## 10. Why this is additive rather than bloat

The no-feature-bloat constraint applies to this design too, so the case
has to be made explicitly:

- It fills a **reserved** slot rather than inventing a concept:
  `FactBasis.TOOL_OBSERVED` has existed since spec v1.1 marked
  *"reserved: no v1.1 producer"*.
- It is the only proposed capability a hand-maintained markdown file
  **cannot** reproduce at any budget. A flat file can be re-read; it
  cannot tell you it has gone out of date. Two field reports say the
  push path is the product, and the 70%-baseline claim is the standing
  threat to the moat — freshness is the differentiated remainder.
- It closes the last of the three self-report gaps. Capture coverage
  shipped `04e5bde`; trust telemetry shipped `a815b78`; **evidence
  freshness is the third and last**. All three are the same class:
  *the ledger does not self-report its own limits.*
- It is eval-gated at every step, with a pre-registered predicted
  failure (H-4) that makes any later improvement attributable rather
  than retrofitted — and, since `4ea08d4`, an oracle that can actually
  grade it.
