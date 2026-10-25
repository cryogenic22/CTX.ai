# CTX Legions: operating instructions

## Vision

Long-running agents fail in predictable ways: context rots, decisions get lost, the spec drifts without
anyone saying so, work is redone, and a fresh session resumes badly. CTX is the state core that removes
those failures. The harness owns state, the model only reasons, and compaction is a commit, not a loss.
CTX records state deterministically from what agents say and commit, and hands each new session a bounded
briefing it can trust.

CTX Legions is a team of agents that improves the CTX engine in this repo through pull requests.
The CTX Harness Lead (GitHub: @cryogenic22) writes the backlog, reviews every PR and merges.
Everything happens on GitHub: issues, PR descriptions, PR comments and reviews. Nothing else.

## Product context

The backlog serves one product: a harness for long-running coding work.

- The harness owns state. CTX is its state engine: decisions, constraints, dead ends, plan, progress.
- Grok is the reasoner. It never writes memory directly.
- Cursor cloud agents are the environment. Claude Code and Codex must work too.
- The agent loop is thin: launch a fresh session, hand it a briefing, let it work, capture what it decided.
- Runs last up to 8 hours as a chain of fresh sessions. Compaction is a commit, not a loss: a new session
  must resume from git plus the ledger alone.

What we learned from the harness study that motivates the backlog: capture of explicit markers works;
the briefing was the weak part (silent truncation, no dead ends, no progress, superseded choices kept,
harness text fed back in as decisions); and large hook injections were silently dropped by the platform,
so delivery must go through the launch prompt, with a way to prove receipt.

## Principles

1. **Determinism.** No model writes memory. Same inputs give byte-identical ledgers and briefings.
2. **Structure first.** Structural records and graphs (facts, supersession edges, entity graph, plan) are
   core. Any semantic map is read-only and advisory; it never decides what is stored or dropped.
3. **Simplicity bias.** The smallest change that satisfies the spec. Every artifact (file, field, flag,
   record kind) must be read by something, or it is deleted.
4. **Bounded output.** Every briefing or report takes a budget and states what it dropped. No silent
   truncation. No token bloat.
5. **Compatibility.** The ledger format stays backwards compatible, or the PR ships an explicit, tested
   migration. Old ledgers must still load.
6. **Honest measurement.** Numbers come from a script in the repo. Delivery is not use (see
   `ctxpack/core/states.py`). Do not tune anything to the study's recall probes.

## The repo rules you inherit

Read `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` and `.github/workflows/ci.yml` before your first PR.
The ones that bite most often:

- `ctxpack/` core stays stdlib only. Optional extras stay optional.
- Never strip or reorder negations in any compression path (`tests/test_negation_preservation.py`).
- Packing stays byte-deterministic (`tests/test_p0_trust_repairs.py`).
- Every new `ctxpack/**/*.py` file needs a row in `docs/capability-registry.md` (CI gate).
- Numeric claims in `README.md` need a row in `docs/claims-ledger.md` (CI gate). Prefer not to add any.
- Do not edit `CLAUDE.md`, `AGENT_COORDINATION.md`, `.claude/ctx/` or anything under
  `ctxpack/benchmarks/**/results/`.

## Workflow for each item

The benchmark item (the first in the tracker) is the acceptance test for the rest. Every later PR reports
its benchmark numbers on `main` and on the PR head under Verification.

Every issue states its problem, what must be true, and its acceptance tests. Your spec refines those;
it does not drop them without my agreement.

1. **Pick** the highest-priority open `ctx-legions` issue whose dependencies are merged.
   Comment `Claiming this.` on the issue. One claimant per issue.
2. **Branch** in your fork: `legions/<issue-number>-<short-name>`, from the current `main`.
3. **Spec first.** Open a DRAFT PR whose description is the spec, using the template below. Code may be
   absent at this stage. Comment `@cryogenic22 spec ready for review`.
4. **Wait** for a comment from @cryogenic22 that says `Spec approved`. Do not implement before it.
5. **Implement** on the same PR. Keep the spec in the description current; note any change from the
   approved spec under a `Spec changes` heading.
6. **Mark ready** only when CI is green, then comment `@cryogenic22 ready for code review`.
7. @cryogenic22 squash-merges. You never merge, never push to `main`, never force-push a branch you did
   not create.

### PR description template (the spec)

```
Closes #<issue>

## Summary
## Problem and evidence
(what is wrong today, with numbers from a script or test, and file:function pointers)
## What must be true
(acceptance criteria, each one testable)
## Design
## Rejected alternatives
## Assumptions
## Non-goals
## Compatibility and migration
## Risk
## Verification
(test plan; commands run and their results; a test that fails on main and passes here)
## Self-review
```

The Summary, Assumptions, Non-goals, Verification and Self-review headings match the PR template gate
proposed in PR #3, so your PRs pass it if it merges. Do not use unsupported quality words such as
"robust" or "comprehensive"; state what was checked.

## Quality bar

A PR is mergeable only when all of these hold:

- **Determinism.** No model writes memory. Running the same inputs twice gives byte-identical ledger,
  briefing and report output, and a test proves it for anything you add.
- **Behaviour tests.** A test for every behaviour change, written against what a caller observes (CLI
  output, files written, function results), not internals. At least one test fails on `main` and passes
  on your head.
- **Simplicity.** The smallest change that meets the spec. No speculative options. Every new file, field,
  flag or record kind is read by something, or it is removed.
- **No needless dependencies.** `ctxpack/` core stays stdlib only. Any new optional dependency is justified
  in the spec.
- **Backwards-compatible ledger.** Existing `.ctx`, `events.jsonl` and `checkpoints.jsonl` files still load
  and give the same results, or the PR ships a tested migration.
- **Bounded output.** Anything that emits context takes a budget and states what it dropped.
- **Measured.** Once the replay benchmark (L1) is merged, the PR shows its numbers before and after.
- CI green on every lane in `ci.yml`, including the gates job. Type hints and docstrings on public
  functions. Docs updated where behaviour changes, and a line under `## [Unreleased]` in `CHANGELOG.md`.
- Small PRs: aim under about 400 changed lines, tests included. One issue per PR.
- Before asking for review, run the touched tests, then
  `python -m pytest tests/ -q -m "not slow" --ignore=tests/code`, then the scripts in the gates job.

## Review rules

- At most two review rounds per PR. Anything left after round two becomes a follow-up issue that I file.
- Answer every review comment, either with a commit or a reason.
- If you disagree with a review, say so on the PR with evidence. I decide.

## The cap: 15 PRs

- The team may open at most 15 PRs in total. Draft PRs count. PRs closed without merging count.
- The tracker issue "CTX Legions: tracker (15 PR cap)" (#22) holds the counter. When you open a PR, comment
  there with the PR link; I update the counter.
- The backlog has 15 items, one PR each, so there is no spare slot. Ask on the issue before
  splitting an item; I decide which lower-priority item gives up its slot.
- This file's own PR is the Lead's and does not count.

## Boundaries

- Work only in this repo, from your fork. Do not touch any other repository, including the harness
  study repo. Study data reaches this repo only through a PR from the Lead.
- Do not tune anything to the study's recall probes or their answers. The benchmark measures capture,
  supersession and briefing coverage, not probe scores.
- The study pins its own CTX version. Merges here never change a running study.
- No external services, no paid API calls, no network in tests.

## Working with me

- Mention @cryogenic22 on the issue or PR for anything you need. Expect a review within a few hours.
- Ask on the issue when a spec question would change the design. Decide yourself when it would not,
  and record the choice under Assumptions.
- If you find a gap the backlog misses, open an issue labelled `ctx-legions` with evidence. Do not
  start it until I add it to the tracker.
