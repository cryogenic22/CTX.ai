# Spec v1.1 — The Fact Substrate (citation-grade memory contract)

**Status: FINAL for implementation, 2026-07-05.**
Scope discipline: v1.1 is the *substrate contract* — the fields and
schemas that make future learning possible. It deliberately does NOT
implement salience learning, DAG merges, typed edges beyond what exists,
or consolidation. Those consume this contract later; nothing in it
should need reopening when they land.

North star (agreed, senior-lead + team review):

> ctx does not become "smarter summaries." It becomes **immutable,
> cited facts plus deterministic event-sourced learning around those
> facts.** Content is never rewritten — only rank, status, and links
> move, and every move replays from logs.

## 1. Fact identity — `fact_id`

```
fact_id = sha1(scope || "\x1f" || kind || "\x1f" || key || "\x1f" || normalized_value)[:16]
```

- **scope** — reserved for cross-repo identity. Empty string for
  repo-local facts (a ledger lives inside its repo; collision across
  repos is impossible within one ledger). The future lesson-promotion
  layer supplies non-empty scopes; the API takes scope from day one so
  the contract never changes.
- **kind** — the fact class (DECISION, CONSTRAINT, LITERAL,
  FAILED-APPROACH, ERROR, INCIDENT, ...).
- **key** — the stable subject for keyed facts (a knob name, a literal
  kind); for unkeyed prose facts, empty (identity falls to the value).
- **normalized_value** — lowercased, whitespace-collapsed, punctuation-
  trimmed value text.

**Amendment to team review (load-bearing):** the extraction rule and
extractor version are **provenance, not identity**. Hashing them would
mint new fact_ids for identical facts on every parser release, silently
breaking cross-session dedup and supersession chains. They live in
`BASIS` / `EXTRACTOR` on the source record instead. Identity answers
"is this the same fact?"; provenance answers "why do we believe it and
who extracted it?" — different questions, different fields.

A *revised value is a new fact* (new fact_id); the key chains versions
together. This is what makes the supersession DAG possible later.

## 2. Provenance and basis

Every fact carries, per source:

- `SRC` — `session:<id>#turn<n>` or `file#Lx-Ly` (exists today)
- `BASIS` — how extraction happened, an **enum, never a float**:
  - `marker_stated` — explicit convention (`Decision:`, `Constraint:`,
    `ctx-incident:`)
  - `user_imperative` — user-turn constraint patterns
  - `literal_extractor` — verbatim identifier banking
  - `tool_observed` — derived from tool actions/results (reserved;
    no producer in v1.1)
  - `structural` — files, tasks, errors, tool runs
  - `inferred` — best-effort verb patterns (decision verbs); the only
    basis allowed to be wrong about *whether this is a fact at all*
- `EXTRACTOR` — parser version stamp for audit (e.g. `tp/1.1`)

Float confidence is **rejected permanently**. `ctxpack/core/confidence.py`
and `ctxpack/modules/dream.py` are prototype evidence that the instincts
existed; they are not revived — an unaccountable 0.87 damages trust,
an auditable basis enum earns it.

## 3. Status lifecycle

`STATUS: current | superseded | retracted | expired` on every fact.
v1.1 stamps `current` at extraction. Transitions:

- `superseded` — set by the supersession machinery (field-level
  SUPERSEDED-<KEY> chains today; fact-level with the DAG).
- `retracted` — explicit take-back (a fact was wrong, not just old).
  Retracted facts stay in the ledger with status — this repo's own
  history (retracted metric claims) is the design precedent.
- `expired` — `EXPIRES-AT` passed (as-of clock, never wall clock).

## 4. DAG-ready supersession (fields now, merge later)

Reserved fields, emitted where derivable, consumed by no v1.1 code:

- `PARENTS` — fact_ids of the immediately prior version(s)
- `SUPERSEDES` — fact_ids this fact replaces
- `BASE-SNAPSHOT` — the `ledger_sha256` of the checkpoint the revising
  session started from (already computed per checkpoint). This is what
  distinguishes a *branch conflict* (two revisions from the same base —
  concurrent agents) from an *ordinary later revision* (base includes
  the other's change). Without it the DAG cannot merge honestly.

Merge semantics are explicitly **out of scope** for v1.1.

## 5. The event log — `events.jsonl` (derived, replayable)

**Design rule (senior-lead addition): the transcript is the single
event source.** `events.jsonl` is a *materialized view* written at
checkpoint time by folding the transcript — never appended by live
reads. Live-read logging would be wall-clock-ordered and unreplayable;
the transcript already records every retrieval as tool_use entries
(the parser counts them today). Deleting events.jsonl and re-running
checkpoints over the same transcripts MUST reproduce it byte-for-byte.

One JSON object per line:

```json
{"schema": "ctx-events/v1", "session": "<sid>", "checkpoint": "<ledger_sha256[:12]>",
 "event": "<type>", "fact_id": "<id|null>", "turn": <n>, "detail": {...}}
```

Event types in v1.1: `fact_asserted`, `incident` (with type + resolved
fact_id when linkable), `supersession` (chain observed), `retrieval`
(ledger_reads / transcript_greps counts per session). Future types
(`rank_boost`, `promotion`, `expiry`) extend the enum without schema
change.

## 6. Rank policy versioning

Ranking is a deterministic fold: `rank = fold(events, policy)`. v1.1
ships `rank/v0-static-priors` (today's behavior: extraction-time
salience floats, no updates) and records the policy id in every
checkpoint journal row. Future policies (usage-weighted, decayed) are
new versioned folds A/B-testable offline against the same event log —
never in-place changes. Guard for later folds, agreed: retrieval boosts
are capped and constraints keep a rank floor (no rich-get-richer).

## 7. Explicit absence and known-unknowns

The read path must never render "no result" as an empty string. A miss
returns a structured absence assertion:

```json
{"found": false, "searched_entities": N, "as_of_turn": T,
 "note": "no banked fact matches — asserted absence, not an error"}
```

(v1.1 anchors absence to the latest packed turn; checkpoint-sha
anchoring arrives with the DAG's `BASE-SNAPSHOT`.)

An auditable negative ("searched 412 entities as of turn 730") is
a first-class answer — benchmark evidence across CompactBench and the
resume probes says abstention beats plausible-but-wrong every time.
Known-unknown *extraction* (questions asked but never answered,
deferred decisions) is deliberately deferred; the absence contract is
the v1.1 hook it will plug into.

## 8. Incidents tied to facts

`ctx-incident:` rows resolve their `fact="..."` payload against banked
facts by deterministic normalized matching. Unambiguous match → the
incident carries `FACT-ID`; ambiguous or unmatched → empty (never
guess). This joins the feedback loop to identity: a `stale` incident
that names a fact is a signed demotion signal for exactly that fact.

## 9. Deferred (consumes this contract, does not reopen it)

In agreed order: event-sourced salience fold (rank/v1) → DAG merge →
typed edges (`supersedes`/`contradicts` safe; evidence links start as
`candidate_evidence_for` — co-location is signal, not proof) →
consolidation pass → cross-repo lesson promotion (needs ≥2-repo
incident evidence + scope firewall).
