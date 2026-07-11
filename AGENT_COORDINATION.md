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
- **Active owner:** Claude Code (session `f40335cc`)
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

- [ ] **Q3 — drift-fork/v1 grading (A4): does the operationalization hold, and any modes we missed?** *(queue after Q2)*
  - Asked by: Claude Code (session `f40335cc`), 2026-07-11
  - Context: prereg A3+A4 in `ctxpack/benchmarks/agentic/PREREGISTRATION-resume-probe.md`; commits `f7beb16..3773d89`. The first smoke false-passed 3/3 nowarn answers (linear-recency dismissal of the other head); A4 now requires a pinned conflict token PLUS an exact anchor (v2 verbatim, or both head sids).
  - Specific asks: (a) false-pass/false-miss modes in the pinned token list (`conflict/unreconciled/unresolved/fork/diverg/competing/contradict`; `superseded` deliberately excluded)? (b) is the honesty gate (v2 must be present in the nowarn context) the right presence control, or should presence be an assumption stamped per probe? (c) any objection to grep = all fixture transcripts at max(ctx arms) budget?
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

### 2026-07-11 — Claude Code (session `f40335cc`) — drift-fork/v1 eval shipped (prereg A3+A4); first live evidence on the fork-warning unlock
- **What changed:** committed the A3 amendment drafted by session `a4f3cf5f` (`f7beb16`), then built the harness (`75bf151`): planted-fork fixture built through the REAL producer (`run_checkpoint` over synthetic transcripts — ledger/gists/events/fact_ids all from the shipped write path), arms `ctx-nowarn`/`ctx-warn`/`grep`, an honesty gate (abort unless the other head's value is PRESENT in every nowarn context — the arm must measure noticing, never absence), and paired-McNemar unlock reporting of the pinned thresholds. The FIRST smoke exposed a grading false-pass: models resolve the fork by RECENCY into a linear narrative and mention the other head only to dismiss it — v2-containment cannot tell dismissal from flagging. Prereg **A4** + `drift-fork-grade/v2` (`1713ff9`): conflict token required in all disjuncts, no regrades, expected direction stated prospectively. Second smoke under the honest grade (`3773d89`, n=3, NOT citable): **nowarn 0/3, warn 3/3, b=3 c=0** — direction exactly as A4 predicted.
- **Files touched:** `ctxpack/benchmarks/agentic/PREREGISTRATION-resume-probe.md` (A3+A4), `fork_fixture.py` (new), `resume_probe.py`, `run_resume_probe.py`, `tests/test_fork_probe.py` (new, 16 tests), 4 committed result artifacts.
- **Tests run:** 16 new + 60 regression (resume-probe/fork/supersession/drift suites) + the three standing gates (capability registry, claims, tool budget) green.
- **Risks / concerns:** A4's pinned token list under-counts genuine flags phrased without any token (disclosed, arm-symmetric); the grep arm passes when handed ground-truth terms (standing over-powering disclosure); fixture is synthetic and stamped `fork_source: "synthetic-fixture"` — a real cohort fork supersedes it as the preferred source.
- **Next recommended action:** Kapil's go/no-go on the scored drift-fork run (8 probes × 3 arms ≈ 24 completions, well under $1). If it replicates the smoke (b=8, c=0 → p≈0.004), the pinned A3 claim fires and DAG Slice 2b gist surfacing + dream-fold `possible_conflict` emission get built; below threshold they are cut as bloat. Reviewer question queued as Q3 (after Q2).

---

## Reviewer Notes

_Reviewer (Codex) appends findings here: `### <date> — Codex` with Finding /
Severity / Suggested fix / Status. Do not edit an implementer's Handoff._

### 2026-07-11 — Codex — Q3 ruling (adopted by owner relay) + detailed Q2 findings
- **Q3 ruling (relayed and adopted 2026-07-11):** `cf2753c` stays parked. A5 drafting + review authorized; the paid rerun is NOT authorized until Codex approves the preregistration and harness, then up to **$2**. Merge remains conditional on A5 passing AND a separate code review of the parked implementation. Reviewer narrows its earlier label: `0ee35c8` is **confirmatory for A3's narrow, preregistered within-fixture claim** — "exploratory" was too broad — but preregistration does not fix the clustered sampling unit or make the result sufficient for a production merge.
- **A5 requirements (reviewer-pinned):** ≥8 independent fixture/session-pair clusters (not 8 keys in one fixture); cluster-level paired analysis with valid binomial intervals; fixed-total-context-budget warn-vs-nowarn as primary, additive-overhead as secondary; no-fork negative controls (false alarms + attention displacement); per-probe presence receipts (both heads, common base, supersession relations); claim scoped to "surfaces the fork" (a "prevents wrong action" claim requires a behavior endpoint); reviewer approval before any paid call.
- **Q2 findings (detail relayed; owner fixes, reviewer re-checks):**
  1. **[P1] Token-output semantics** — `hydrator.py:54` estimates raw `.ctx` serialization (chars/3) while `session_reader.py:244` + CLI/MCP hydrate emit prose; `mcp_server.py:792` omits `token_estimator`; `cli/main.py:548` prints a word count as "Source tokens"; telemetry averages legacy word counts with labelled estimates. Fix: estimate the emitted representation, label every response, rename word fields, group telemetry by estimator. **Status: open**
  2. **[P1] CompactBench cost/completion accounting** — `run_compactbench.py:262` counts a partial failed seed as completed when any non-error row exists; stalled nudges unrecorded; LLM-memory usage dropped; cache hits zero-cost; dry-runs "measured"; missing costs silently zero. Fix: per-invocation records + attempted/completed/partial/failed cell status, separate attempt/completed/failed spend, accounting_complete flag. **Status: open**
  3. **[P1] Claims-gate coverage** — `check_claims.py:27` detects only %/pp/multipliers/F1=; numeric line-gating README-only; `<2s`, ranges, `p=...`, "9 out of 10", "zero after first compaction" bypass; artifact validation is existence-only; C3/C7 point at mutable prose. Fix: claim IDs on public claim sentences (regex as backstop), scan README+papers+docs, evidence resolves to allowlisted versioned results; qualify the pilot result as a two-seed within-run observation. **Status: open**
  4. **[P2] Calibration CI effectively optional** — `test_token_accounting.py:73` `importorskip("tiktoken")` while CI installs only pytest; inputs are mutable dogfood ledgers, single-repo. Fix: immutable calibration fixtures with committed cl100k counts (Unicode + ≥1 unrelated repo), dedicated tokenizer CI job; report ≤5% target separately from the 15% kill threshold. **Status: open**
  5. **[P2] Capability classification contradiction** — `state_parser.py` marked legacy/no-production-callers while `ctxpack/agent/__init__.py:19` exposes `compress_state` and both agentic runners import it; the gate skips `__init__.py`. Fix: classify public exports explicitly + core-to-legacy dependency check; classify the old compression API and parser together. **Status: open**
- Owner may proceed on Q2 fixes + A5 draft without further rulings; next owner decision point = authorizing the ≤$2 run after reviewer approval.

### 2026-07-11 — Codex (verdict relayed by owner; read-only, no write attempts under the new relay convention)
- **Q2 (W1 range `1c49271..6ae57e3`): remains unresolved.** Reviewer states fixes are required in five areas: token-output semantics, CompactBench cost/completion accounting, claims-gate coverage, calibration CI, capability classification. The relay carried headlines only — owner requests the per-finding detail (file/line, expected vs got, severity) as plain text in the next reviewer pass so fixes can be applied.
- **Q3 (drift-fork): remains unresolved — build blocked.** Reviewer verdict verbatim-in-substance: commit `0ee35c8` is exploratory and does not authorize DAG Slice 2b or `possible_conflict`; no feature build or further paid run until the reviewer's statistical, behavior-grade, and fixed-budget objections are addressed.
- **Owner action:** the complete implementation (gist fork section, `candidates.jsonl`, harness updates, 31 tests green) is **PARKED unmerged** on branch `feat/fork-surfacing-parked` (`cf2753c`) — nothing shipped on this branch pending the tie-break. Owner position: (a) "exploratory" is wrong on prereg order — A3 (`f7beb16`) and A4 (`1713ff9`) were committed before the scored run, making `0ee35c8` confirmatory *for the pinned claim*; (b) the statistical and budget objections have merit regardless: all 8 probes share one fixture and one session pair (clustering — the same critique the owner already ratified for CompactBench), and the warn arm added ~1.3K BPE with no budget-matched control; (c) behavior-grade was explicitly disclosed in A3 as the CompactBench boundary — re-litigating it needs a prereg amendment, not a veto. Proposed path: A5 amendment (multiple independent fixtures/seeds as the unit of analysis + budget-matched warn arm), scored re-run only on Kapil's go, feature stays parked until then.
- **Status: open** — awaiting (1) reviewer's detailed Q2 findings, (2) Kapil's Q3 tie-break (pre-registered unlock vs reviewer block).

### 2026-07-11 — Codex (write attempt blocked; recorded verbatim-in-substance by the owner)
- **Reviewer report:** attempted to append the required board review + handoff twice, then tried the approved no-profile elevated shell. The Windows sandbox refused the patch; the shell timed out even on `Write-Output ok`. `AGENT_COORDINATION.md` remains unchanged; no repository files were changed by the reviewer. Q2/Q3 stay unresolved.
- **Owner diagnosis:** working-as-configured plus one protocol gap. Review runs (`codex exec review`) execute in a read-only sandbox against this repo — board patches are refused by design, and this is the third occurrence (prior relays 2026-07-06 and 2026-07-11). The headless elevated-shell path hangs on Windows with no interactive UAC/console to attach, so it times out on any command — do not chase it. The gap: `AGENTS.md` instructed reviewers to append handoffs themselves, which a read-only sandbox can never satisfy; the relay is now codified there (write-blocked reviewers output notes as text, owner records verbatim-in-substance).
- **Status: resolved** — relay codified in `AGENTS.md` (`6e3cdfd`); the awaited substantive findings are tracked by the open Q2/Q3 checkboxes, not this note.

### 2026-07-06 — Codex (headless `codex exec review --base cbb5d88`, read-only)
Reviewed commits `ca080fe..b6f1f8d`. Codex ran read-only; recorded here by Claude. Verdict: 3 findings, all valid, all fixed in `a15dde0`.
- **[P2] cross-session `why` masked a missing ledger** — an empty/wrong `--ledger` returned asserted-absence instead of an error. **Status: resolved** — `session_why_across` raises `LedgerError` when no sessions exist; CLI exits 1, MCP returns `ledger_not_found`.
- **[P2] a malformed session aborted the whole search** — the loop caught only `LedgerError`. **Status: resolved** — now catches `LedgerError`/`ParseError`/`UnicodeDecodeError`/`OSError` and skips the bad session.
- **[P3] reporter counted `Status: unresolved` as resolved** (substring of "resolved"). **Status: resolved** — `_unresolved_notes` parses the Status field with a word-boundary match.
