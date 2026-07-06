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
- **Reviewer scope is notes-only.** A reviewer writes to the board (answers
  questions, leaves review notes with *proposed* fixes) but does **not** edit
  code or tests, apply fixes, or commit — the active owner applies every fix.
  This is the one board exception to the single-owner rule; it keeps ownership
  clean and edits non-concurrent while still unblocking review.
- **No agent makes an irreversible or outward-facing call from this file
  without human or reviewer confirmation.**

---

## Current Repo State

- **Branch:** `feat/literals-ledger`
- **Last green tests:** `python -m pytest tests/test_literals_ledger.py tests/test_session_reader.py tests/test_cross_session_why.py tests/test_supersession_dag.py tests/test_scorecard.py tests/test_conflict_lint.py tests/test_fact_substrate.py tests/test_coordination_check.py -q` → 115 passed (2026-07-06)
- **Active owner:** Claude Code (session `eca3f61c`)
- **In-flight work:** none blocking. Recently shipped: identifier fidelity in `session stats` (#7, `f518bee`); reviewer-notes-only protocol (`7f2e6f8`); cross-session `why` default (#6, `7e5d3f7`); coordination board + reporter (`fb57725`/`a18933f`/`c68761f`). Next: #5 subagent-verdict capture (design call pending).
- **Do not touch:** `CLAUDE.md` (hand-authored by the owner); `.claude/ctx/*` live ledger; committed eval results under `ctxpack/benchmarks/**/results/`

---

## Open Reviewer Questions

- [x] **Q1 — Cross-session `why` (#6): wire `session_why_across` as the CLI/MCP default, or behind an opt-in `--all-sessions` flag?**
  - Asked by: Claude Code (session `eca3f61c`), 2026-07-06
  - Context: `session_why` searches one session's doc; `session_why_across` folds the whole ledger. Live-verified on the real ledger — recovered the `$60 full pass` constraint from session `bdfbd48b` (turn 445, 6 sessions back) that single-session `why` on the latest session missed.
  - Suggested options: **(a)** default cross-session; `--session <id>` still scopes to one — *Claude's rec: "the thing agents actually call"*. **(b)** opt-in `--all-sessions` flag; zero behavior change to existing callers/tests.
  - Reviewer (Codex): reviewed the DAG + cross-session-`why` work off-board; endorsed the eval-first bar (test through `session why`, not only the fold) and the read-only coordination shape.
  - **Resolved (owner, 2026-07-06): option (a).** Cross-session is the default in CLI + MCP; `--session <id>` (CLI) / `session` arg (MCP) preserves explicit single-session scope. Shipped in commit `7e5d3f7`; decision banked this session as a `Decision:` line (recover via `ctxpack session why "cross-session"`).

---

## Handoffs

### 2026-07-06 — Claude Code (session `eca3f61c`)
- **What changed:** scorecard `--md` exec-summary (commit `ca080fe`); supersession DAG read-only fold + `why` surfacing (commit `2215519`); cross-session `why` core `session_why_across` + `_why_matches`/`_annotate_supersession` refactor (**UNCOMMITTED**).
- **Files touched:** `ctxpack/core/supersession_dag.py`, `ctxpack/agent/session_reader.py`, `ctxpack/agent/dashboard.py`, `ctxpack/cli/main.py`, `ctxpack/integrations/mcp_server.py`, `docs/session-memory-onboarding.md`, tests.
- **Tests run:** 77 passed (see Current Repo State). Live ledger finding: 0 `fact_superseded` across 219 events — the supersession DAG is dormant until agents use `Supersedes: <fact_id> — <reason>`.
- **Risks / concerns:** cross-session `why` is uncommitted pending **Q1**; DAG gist surfacing + candidate emission are intentionally gated until real edges exist.
- **Next recommended action:** Reviewer answers **Q1** → Claude wires + commits cross-session `why`.

### 2026-07-06 — Claude Code (session `eca3f61c`) — coordination + Q1 resolution
- **What changed:** agent coordination board + `AGENTS.md` (`fb57725`); read-only status reporter (`a18933f`); cross-session `why` default wired + shipped (`7e5d3f7`, resolves Q1); fixed the reporter's `_field` bold-strip so glob values keep `**`; added the reviewer-only board-edit exception to the protocol.
- **Files touched:** `ctxpack/agent/session_reader.py`, `ctxpack/cli/main.py`, `ctxpack/integrations/mcp_server.py`, `scripts/coordination_check.py`, `tests/test_cross_session_why.py`, `AGENT_COORDINATION.md`, `AGENTS.md`.
- **Tests run:** 27 (cross-session `why` incl. CLI + MCP defaults + `session_reader`); reporter re-verified on the live board.
- **Risks / concerns:** none open. SessionStart hook injection + any scheduler are intentionally **not** built — gated per owner + Codex on the board proving useful over a few real handoffs.
- **Next recommended action:** use the board for the next 3–5 real handoffs, then decide whether SessionStart injection earns its keep.


### 2026-07-06 - Codex - reporter false-unresolved fix
- **What changed:** fixed `scripts/coordination_check.py` so multi-finding reviewer notes with inline `Status: resolved` markers are not falsely reported as unresolved.
- **Files touched:** `scripts/coordination_check.py`, `tests/test_coordination_check.py`.
- **Tests run:** `python -m pytest tests/test_coordination_check.py -q` -> 6 passed; `python scripts/coordination_check.py` -> 0 open questions, 0 unresolved reviewer notes.
- **Risks / concerns:** small reporter-only change; no production CTX path touched.
- **Next recommended action:** commit this reporter fix separately from unrelated `.claude/ctx` hook churn and the untracked investor brief.

### 2026-07-06 — Claude Code (session `eca3f61c`) — accept Codex reporter fix
- **What changed:** committed Codex's `_unresolved_notes` fix (inline `**Status: resolved**` markers were wrongly read as unresolved — a gap in the earlier `a15dde0` fix) + its test; tidied blank-line spacing in the inserted test.
- **Files touched:** `scripts/coordination_check.py`, `tests/test_coordination_check.py`.
- **Tests run:** `python -m pytest tests/test_coordination_check.py -q` → 6 passed; reporter on the live board → 0 unresolved reviewer notes.
- **Next recommended action:** none open — the reporter-fix loop is closed.

### 2026-07-06 — Claude Code (session `eca3f61c`) — reviewer-notes-only + #7 fidelity
- **What changed:** codified reviewer-notes-only (`7f2e6f8` — reviewer flags, owner fixes); shipped identifier fidelity in `session stats` (#7, `f518bee`) — every checkpoint stamps `literal_fidelity` (verbatim id recovery across the fold), surfaced as `{min, latest}` complementing `raw_fallback_rate`.
- **Files touched:** `AGENTS.md`, `AGENT_COORDINATION.md`, `ctxpack/agent/checkpoint.py`, `ctxpack/agent/session_reader.py`, `tests/test_literals_ledger.py`.
- **Tests run:** 115 (literals / session_reader / cross-session / DAG / scorecard / conflict-lint / fact-substrate / coordination).
- **Next recommended action:** #5 subagent-verdict capture — a change to the parser's sidechain filter (`transcript_parser.py:517`); owner picks the capture approach before the parser is edited.

---

## Reviewer Notes

_Reviewer (Codex) appends findings here: `### <date> — Codex` with Finding /
Severity / Suggested fix / Status. Do not edit an implementer's Handoff._

### 2026-07-06 — Codex (headless `codex exec review --base cbb5d88`, read-only)
Reviewed commits `ca080fe..b6f1f8d`. Codex ran read-only; recorded here by Claude. Verdict: 3 findings, all valid, all fixed in `a15dde0`.
- **[P2] cross-session `why` masked a missing ledger** — an empty/wrong `--ledger` returned asserted-absence instead of an error. **Status: resolved** — `session_why_across` raises `LedgerError` when no sessions exist; CLI exits 1, MCP returns `ledger_not_found`.
- **[P2] a malformed session aborted the whole search** — the loop caught only `LedgerError`. **Status: resolved** — now catches `LedgerError`/`ParseError`/`UnicodeDecodeError`/`OSError` and skips the bad session.
- **[P3] reporter counted `Status: unresolved` as resolved** (substring of "resolved"). **Status: resolved** — `_unresolved_notes` parses the Status field with a word-boundary match.
