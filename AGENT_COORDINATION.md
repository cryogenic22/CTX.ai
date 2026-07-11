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
- **Last green tests:** `python -m pytest tests/test_subagent_verdicts.py tests/test_transcript_parser.py tests/test_literals_ledger.py tests/test_session_reader.py tests/test_p0_trust_repairs.py -q` → 101 passed (incl. negation + determinism gates, 2026-07-06)
- **Active owner:** Claude Code (session `a21df970`)
- **In-flight work:** Week-1 of the ratified execution plan (`docs/execution-plan-2026-07.md`): W1-1 capability registry, W1-2 claims ledger + CI gate, W1-3 token accounting, W1-4 default tool surface, W1-5 CompactBench cost reporting, W1-6 pilot brief. Next big rocks (deferred/gated): E-1..E-7 evidence program per the plan; domain-contracts recipe; DAG Slice 2 (gated on real `fact_superseded` edges); consolidation/dream-fold; cohort read-path report (~07-18).
- **Do not touch:** `CLAUDE.md` (hand-authored by the owner); `.claude/ctx/*` live ledger; committed eval results under `ctxpack/benchmarks/**/results/`

---

## Open Reviewer Questions

- [x] **Q1 — Cross-session `why` (#6): wire `session_why_across` as the CLI/MCP default, or behind an opt-in `--all-sessions` flag?**
  - Asked by: Claude Code (session `eca3f61c`), 2026-07-06
  - Context: `session_why` searches one session's doc; `session_why_across` folds the whole ledger. Live-verified on the real ledger — recovered the `$60 full pass` constraint from session `bdfbd48b` (turn 445, 6 sessions back) that single-session `why` on the latest session missed.
  - Suggested options: **(a)** default cross-session; `--session <id>` still scopes to one — *Claude's rec: "the thing agents actually call"*. **(b)** opt-in `--all-sessions` flag; zero behavior change to existing callers/tests.
  - Reviewer (Codex): reviewed the DAG + cross-session-`why` work off-board; endorsed the eval-first bar (test through `session why`, not only the fold) and the read-only coordination shape.
  - **Resolved (owner, 2026-07-06): option (a).** Cross-session is the default in CLI + MCP; `--session <id>` (CLI) / `session` arg (MCP) preserves explicit single-session scope. Shipped in commit `7e5d3f7`; decision banked this session as a `Decision:` line (recover via `ctxpack session why "cross-session"`).

- [ ] **Q2 — Review request: Week-1 execution-plan range `1c49271..6ae57e3` (7 commits).**
  - Asked by: Claude Code (session `a21df970`), 2026-07-11
  - Packet with per-commit design calls, targeted questions (Q-a..Q-g), verify commands, and self-declared concerns: `docs/review-packet-w1-2026-07-11.md`. Headless: `codex exec review --base 1c49271`.
  - Highest-value targets: W1-3 token-estimator semantics change (`tokens_injected` ~2-4x larger; MCP pack metric keys renamed) and W1-5 `n_seeds` denominator semantics (feeds the E-3 budget freeze).
  - Reviewer: findings under Reviewer Notes (or here); notes-only — owner applies fixes.

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

### 2026-07-06 — Claude Code (session `eca3f61c`) — #5 subagent verdicts (backlog cleared)
- **What changed:** marker-gated subagent-verdict capture (#5, `945020a`, owner chose marker-gated): a marker-led line in a sidechain banks as a FINDING (source=subagent), surfaced on the resume gist + `stats.captured.findings`; unmarked chatter + isMeta stay filtered; FINDINGs excluded from the decision lint. This clears the ergonomics backlog #5/#6/#7.
- **Files touched:** `ctxpack/agent/transcript_parser.py`, `checkpoint.py`, `session_reader.py`, `tests/test_subagent_verdicts.py`, `tests/test_transcript_parser.py`.
- **Tests run:** 101 (incl. `test_p0_trust_repairs` determinism + `test_negation_preservation`).
- **Next recommended action:** none in the ergonomics track. Next big rocks are deferred/gated (see Current Repo State) — owner to pick the next thread (likely domain-contracts recipe).

### 2026-07-11 — Claude Code (session a21df970) — alignment response to external verdict
- **What changed:** appended an alignment response to the external repo verdict + 90-day directive pasted in `docs/notes.md` (verdict accepted with 3 corrections; directive re-sequenced for one-owner capacity; deep-tech rec = Track C post-T10). Docs-only; no code, no tests.
- **Files touched:** `docs/notes.md`.
- **Verified while responding:** the reviewer's T4 claim is real — whitespace-split token counts in `ctxpack/core/hydrator.py:55,196,297` and `mcp_server.py:642` user-facing telemetry.
- **Risks / concerns:** the external directive's T10 (powered CompactBench) conflicts with two banked preconditions — cost-reporting fix + probe hardening — flagged in the response §3.
- **Next recommended action:** Kapil answers the 5 decisions in `docs/notes.md` §7 (ratify plan, powered-run go/no-go, pilot recruitment, deep-tech track, claims-ledger enforcement); owner then starts week-1 items (T1/T3/T4/T16 + cost-reporting fix).

### 2026-07-11 — Claude Code (session a21df970) — plan ratified; execution plan published
- **What changed:** owner ratified the re-sequenced plan with statistical amendments (recorded in `docs/notes.md` ratification section — the reviewer's sandbox again could not write to repo files, so the owner recorded it). Key amendment accepted: 240 sentinel probes from 2 seeds are clustered, not independent — powered run moves to seed-level (cluster) analysis, preregistered endpoint hierarchy, Holm–Bonferroni across 4 co-primaries, power+budget frozen after an unscored pilot. Published `docs/execution-plan-2026-07.md`: W1-1..W1-6 (capability registry, claims ledger CI, token accounting, 5-tool surface, cost-reporting fix, recruitment brief), E-1..E-7 (probe hardening, prereg amendment v2, unscored pilot, powered run, fuzzing, security+redaction, Track C spec spike), G-1..G-8 gated, L-1..L-6 standing loops.
- **Files touched:** `docs/notes.md`, `docs/execution-plan-2026-07.md`, `AGENT_COORDINATION.md`.
- **Tests run:** none (docs only).
- **Risks / concerns:** the reviewer remains write-blocked on this repo from its sandbox — owner records reviewer positions verbatim-in-substance; flag if that relay ever distorts.
- **Next recommended action:** owner starts W1-1..W1-5 (W1-6 brief drafted for Kapil to send); external onboarding stays hard-gated on E-6 + G-4.

### 2026-07-11 — Claude Code (session a21df970) — Week-1 of the execution plan SHIPPED
- **What changed:** all six W1 tasks landed as separate review units: `07b740b` plan+board docs → `007a775` W1-1 capability registry + gate → `5041ae0` W1-2 claims ledger + CI gate → `860d1a8` W1-3 labelled token estimator (whitespace measured -49%..-78% vs cl100k; ctx-kind chars/3 lands -9%..+5% on real committed artifacts) → `d8b4bb0` W1-4 five-tool default surface + 4,500-char description budget → `9336af0` W1-5 CompactBench usage/per-seed-cost/run rollup (half the powered-run precondition; probe hardening E-1 remains) → `a3242ed` W1-6 pilot brief.
- **Files touched:** docs (capability-registry, claims-ledger, pilot-brief, execution-plan), scripts (check_capability_registry, check_claims), ctxpack/core/tokens.py (new), hydrator/telemetry/mcp_server/session_reader/cli, run_compactbench.py, 5 new/extended test files.
- **Tests run:** 135 passed across all touched suites incl. negation-preservation + determinism gates; three standing gates green (registry, claims, tool budget).
- **Risks / concerns:** MCP pack metrics keys renamed honestly (`source_words`, `ctx_token_estimate`, `compression_ratio_words`) — any external consumer of the old keys breaks loudly, none known in-repo. A zero-value dryrun artifact created during W1-5 plumbing verification was deleted (contained no measurements); the 2026-07-04 dryrun file remains untouched as the owner's decision.
- **Next recommended action:** Kapil sends `docs/pilot-brief.md` when ready; next thread is E-1 probe hardening + E-2 preregistration amendment v2 (owner), keeping E-6 security elevated.

---

## Reviewer Notes

_Reviewer (Codex) appends findings here: `### <date> — Codex` with Finding /
Severity / Suggested fix / Status. Do not edit an implementer's Handoff._

### 2026-07-06 — Codex (headless `codex exec review --base cbb5d88`, read-only)
Reviewed commits `ca080fe..b6f1f8d`. Codex ran read-only; recorded here by Claude. Verdict: 3 findings, all valid, all fixed in `a15dde0`.
- **[P2] cross-session `why` masked a missing ledger** — an empty/wrong `--ledger` returned asserted-absence instead of an error. **Status: resolved** — `session_why_across` raises `LedgerError` when no sessions exist; CLI exits 1, MCP returns `ledger_not_found`.
- **[P2] a malformed session aborted the whole search** — the loop caught only `LedgerError`. **Status: resolved** — now catches `LedgerError`/`ParseError`/`UnicodeDecodeError`/`OSError` and skips the bad session.
- **[P3] reporter counted `Status: unresolved` as resolved** (substring of "resolved"). **Status: resolved** — `_unresolved_notes` parses the Status field with a word-boundary match.
