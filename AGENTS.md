# AGENTS.md — Codex working conventions for CTX_mod

## Coordinate through the board

Before touching code or starting a review, **read `AGENT_COORDINATION.md`** and
act on anything addressed to you. Before you stop, **append a Handoff** there.

- Answer Open Reviewer Questions under the question's `Reviewer:` line (or the
  **Reviewer Notes** section). **Do not edit the asker's note.**
- Tick a question's checkbox `[x]` only when resolved; link the resolving
  commit sha or `fact_id`.
- The board is append-only except resolved checkboxes and the Current Repo
  State block. Never rewrite another agent's entry.
- The board is the operating surface, **not memory**. `.claude/ctx/` is the
  deterministic receipt layer — reference `fact_id`s (`ctxpack session why
  "<value>"`), commit shas, and exact test commands rather than restating them.
- Do not make an irreversible or outward-facing decision from the board without
  human confirmation.
- One active owner at a time — do not run against this repo while a Claude Code
  session is active on it (concurrent edits have clobbered work here before).
- **You flag; the owner fixes.** As reviewer, leave findings and *proposed*
  fixes as review notes on the board — do **not** edit code or tests, apply
  fixes, or commit. The active owner (Claude Code) applies and commits every
  fix. This keeps ownership clean and edits non-concurrent.

## Load-bearing invariants (CLAUDE.md is authoritative)

`CLAUDE.md` holds the full project instructions and is **hand-authored by the
owner — do not edit it.** The invariants most likely to bite a reviewer/editor:

- Zero runtime dependencies in `ctxpack/` core (stdlib only; tiktoken is
  optional, benchmarks-only).
- Never strip or reorder negations in any compression path
  (`tests/test_negation_preservation.py` gates this).
- Packing stays byte-deterministic — no wall-clock dates outside
  `clock.as_of_date()`, no unsorted directory walks.
- Eval results are immutable: new runs write new versioned files under
  `ctxpack/benchmarks/**/results/`, never overwrite.
- Retracted metric claims (26x cost, 93% retention) must not reappear; current
  numbers live in `paper/status-and-value-v0.5.md`.

## Tests

`python -m pytest tests/ -q` (full suite is slow — scope to touched files
first). See `AGENT_COORDINATION.md` → Current Repo State for the last known
green command.
