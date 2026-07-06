# Consolidation / Dream-Fold — ratified direction (v0)

**Status: ratified direction (Kapil, 2026-07-06). NOT scheduled — sits
at the tail of the existing build order (cohort read-path report →
DAG merge → typed edges → consolidation). Eval-first gate below must
pass before any implementation. This document sharpens what
"consolidation" means; it does not reorder anything.**

## Ratified decisions (2026-07-06)

1. **Image-context is rejected as a memory transport.** Rendering
   ledger content as images to exploit image-token pricing weakens
   exactly what ctx is trusted for: exact identifiers, negations,
   citations, diffability, deterministic rebuilds, fact IDs and
   supersession chains. The cost gain is a provider-specific pricing
   arbitrage, not an architecture. It never enters the core read path.
2. **Deterministic visual maps are allowed as optional orientation
   artifacts.** A memory map — architecture graph, decision topology,
   domain entities, open risks, conflict hotspots, salience heatmap —
   may be rendered *from* the ledger to help a human or agent orient.
   The source of truth stays structured text/events. An agent that
   needs to act hydrates the cited fact; it never OCRs a rendering.
3. **Consolidation is the dream-fold**: deterministic, event-sourced,
   candidate-only, citation-backed. Learning without confabulation.

## Cognitive architecture mapping (design compass)

Johns Hopkins' account of memory — connection formation between
neurons, strengthened or weakened by exposure — implies durable atoms
plus changing connection weights, which is the substrate ctx already
has. The long-term architecture, in those terms:

| Memory system | ctx mechanism | status |
|---|---|---|
| Episodic | session ledgers, turns, verbatim facts | shipped |
| Semantic | domain contracts, stable project rules, metric definitions | ratified (build-order item 3, domain-contract recipe) |
| Synaptic strength | rank/salience fold from reads, re-assertions, incidents | shipped (rank/v1) |
| Executive control | conflict lint, protected subjects, `Supersedes:` | shipped |
| Sleep / dream | offline consolidation proposing candidates | **this module (future)** |
| Recall | gist + targeted hydration + citations at decision time | shipped |

## Dream-fold contract

- Runs **offline** at checkpoint/consolidation time as a deterministic
  fold over `events.jsonl` + the fact substrate. No LLM, no wall
  clock, byte-replayable — the same replay discipline as rank/v1.
- **Emits candidates only, never mutates facts.** Candidate event
  types: `candidate_edge`, `candidate_lesson`, `possible_conflict`,
  `co_revision`, `candidate_evidence_for` (the reserved spec v1.1 edge;
  confirmation promotes it to `evidence_for`).
- Every candidate carries provenance: source fact_ids, sessions, and
  the fold-rule id that produced it; `basis: inferred`, never anything
  stronger.
- **Promotion requires confirmation** by an agent or human — a
  confirmation event with its own provenance. Unconfirmed candidates
  never outrank real facts and decay under budget pressure.
- Cross-repo LESSON promotion keeps the ratified rule: ≥2-repo
  incident evidence + scope firewall.
- Hard guardrail: the module must not rewrite memory. LLM-rewrite
  memory collapses (ACE, 18,282→122 tokens), and the orphaned
  `dream.py` / `ConfidenceTracker` prototypes remain evidence only —
  never revived as-is. The working biological analogy is hippocampal
  replay (re-run, strengthen, connect), not re-narration.

## Eval-first gate (must precede any code)

A pre-registered, measurable claim on the live cohort, in the spirit
of the resume-probe/CompactBench discipline. Sketch (to be pinned at
pre-registration time):

- On the 6-repo cohort ledgers, the fold proposes candidates of which
  a blinded human-endorsed sample judges ≥X% useful (X pinned before
  the run);
- `possible_conflict` candidates satisfy the lint's precision-first
  standard — silent unless exact; a candidate class that cries wolf is
  cut, not tuned.

## Visualization layer (decision 2, minimal contract)

Optional artifact generation (e.g. DOT/Mermaid/PNG) derived
deterministically from the ledger — versioned outputs, regenerate on
checkpoint, never a read-path dependency, never an input to any fold.
Orientation for humans and agents; action always goes through
hydration of cited facts.
