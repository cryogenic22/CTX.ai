# CTX_mod — CtxPack

Deterministic knowledge packer + progressive hydration, evolving into a
session-memory substrate for long-running agents ("CtxPack Checkpoint").
Current program: `paper/agentic-context-plan-v1.md`.

## Session memory (dogfood — this repo runs on its own ledger)

This repo has ctxpack hooks installed (`.claude/settings.json`): every
compaction and session end packs the transcript into `.claude/ctx/`, and
each session start re-injects `latest-gist.md`. The gist you may see at
the top of your context is the previous session's deterministic ledger —
trust its constraints and decisions; hydrate details via
`ctxpack hydrate .claude/ctx/session-<id>.ctx --sections <NAME>` or grep
the raw transcript.

**Decision convention (load-bearing):** when you make a nontrivial
decision (design choice, root cause, chosen fix, abandoned approach),
state it in your reply on its own sentence starting with `Decision:` —
e.g. `Decision: use exponential backoff with base 750ms because the
vendor limit is 40 req/min.` The transcript parser extracts these
deterministically; unmarked decisions in free prose are often missed.
Dead ends the same way: "The X approach didn't work because ...".

## Ground rules

- Zero runtime dependencies in `ctxpack/` core (stdlib only; tiktoken is
  optional, benchmarks-only).
- Never strip or reorder negations in any compression path
  (`tests/test_negation_preservation.py` gates this).
- Packing must stay byte-deterministic: no wall-clock dates outside
  `clock.as_of_date()`, no unsorted directory walks
  (`tests/test_p0_trust_repairs.py` gates this).
- Eval results are immutable: new runs write new versioned files under
  `ctxpack/benchmarks/**/results/`, never overwrite.
- Retracted metric claims (26x cost, 93% retention) must not reappear;
  current numbers live in `paper/status-and-value-v0.5.md`.

## Commands

- Tests: `python -m pytest tests/ -q` (full suite ~35 min; scope to the
  files you touched first)
- Pack: `ctxpack pack <corpus> --layers L2,L3 --as-of YYYY-MM-DD`
- Checkpoint (manual): `ctxpack checkpoint --transcript <session.jsonl>`
- Agentic benchmarks: `python run_agentic_niah.py --smoke`,
  `python run_graphwalks_eval.py --smoke` (live API; full runs cost ~$10)
