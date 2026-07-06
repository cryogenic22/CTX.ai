# Agent Coordination Board

Human-readable operating board for the agents working this repo (Claude Code +
Codex) and the owner. This is the **negotiation surface** — status, handoffs,
open questions, reviewer notes.

It is **not a memory system**. `.claude/ctx/` is the deterministic receipt
layer. Entries here should *point to* fact_ids (`ctxpack session why
"<value>"`), commit shas, and exact test commands — not restate them. A board
that duplicates the ledger becomes a second, sloppy memory; keep it thin.

## Protocol (both agents follow)

- **Read** this file before touching code or starting a review.
- **Append a Handoff** before you stop. Never rewrite another agent's entry.
- Need input? Add an item under **Open Reviewer Questions**.
- Reviewing? Answer under the question's `Reviewer:` line (or **Reviewer
  Notes**) — do **not** edit the asker's note. Tick the box `[x]` only when
  resolved, and link the resolving commit sha or fact_id.
- **Append-only**, except: ticking resolved checkboxes, and updating the
  **Current Repo State** block.
- A **reached decision** is banked to the ledger via a `Decision:` line in the
  session that made it; link its `fact_id` here. The board records that a
  decision happened and where its receipt lives — the ledger holds the receipt.
- **One active owner at a time** (see Current Repo State). Do not run Claude and
  Codex against this repo simultaneously — concurrent edits have clobbered
  in-flight work here before.
- **No agent makes an irreversible or outward-facing call from this file
  without human or reviewer confirmation.**

---

## Current Repo State

- **Branch:** `feat/literals-ledger`
- **Last green tests:** `python -m pytest tests/test_supersession_dag.py tests/test_cross_session_why.py tests/test_session_reader.py tests/test_scorecard.py tests/test_fact_substrate.py tests/test_literals_ledger.py -q` → 77 passed (2026-07-06)
- **Active owner:** Claude Code (session `eca3f61c`)
- **In-flight work:** cross-session `why` (#6) — `session_why_across` built + tested, **UNCOMMITTED**, awaiting the wiring decision (see Q1)
- **Do not touch:** `CLAUDE.md` (hand-authored by the owner); `.claude/ctx/*` live ledger; committed eval results under `ctxpack/benchmarks/**/results/`

---

## Open Reviewer Questions

- [ ] **Q1 — Cross-session `why` (#6): wire `session_why_across` as the CLI/MCP default, or behind an opt-in `--all-sessions` flag?**
  - Asked by: Claude Code (session `eca3f61c`), 2026-07-06
  - Context: `session_why` searches one session's doc; `session_why_across` folds the whole ledger. Live-verified on the real ledger — recovered the `$60 full pass` constraint from session `bdfbd48b` (turn 445, 6 sessions back) that single-session `why` on the latest session missed. Core is built + tested (6 tests in `tests/test_cross_session_why.py`), uncommitted.
  - Blocking: the commit of the cross-session-`why` feature.
  - Suggested options: **(a)** default cross-session; `--session <id>` still scopes to one — *Claude's rec: "the thing agents actually call"*. **(b)** opt-in `--all-sessions` flag; zero behavior change to existing callers/tests.
  - Reviewer (Codex):

---

## Handoffs

### 2026-07-06 — Claude Code (session `eca3f61c`)
- **What changed:** scorecard `--md` exec-summary (commit `ca080fe`); supersession DAG read-only fold + `why` surfacing (commit `2215519`); cross-session `why` core `session_why_across` + `_why_matches`/`_annotate_supersession` refactor (**UNCOMMITTED**).
- **Files touched:** `ctxpack/core/supersession_dag.py`, `ctxpack/agent/session_reader.py`, `ctxpack/agent/dashboard.py`, `ctxpack/cli/main.py`, `ctxpack/integrations/mcp_server.py`, `docs/session-memory-onboarding.md`, tests.
- **Tests run:** 77 passed (see Current Repo State). Live ledger finding: 0 `fact_superseded` across 219 events — the supersession DAG is dormant until agents use `Supersedes: <fact_id> — <reason>`.
- **Risks / concerns:** cross-session `why` is uncommitted pending **Q1**; DAG gist surfacing + candidate emission are intentionally gated until real edges exist.
- **Next recommended action:** Reviewer answers **Q1** → Claude wires + commits cross-session `why`.

---

## Reviewer Notes

_Reviewer (Codex) appends findings here: `### <date> — Codex` with Finding /
Severity / Suggested fix / Status. Do not edit an implementer's Handoff._
