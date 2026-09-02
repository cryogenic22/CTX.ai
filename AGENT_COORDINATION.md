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
- **Last green tests:** 2026-07-30 — **full non-slow suite 1684 passed / 35 skipped / 57 deselected in 60s** (`python -m pytest tests/ -q -m "not slow"`). NOTE for reviewers: a bare `pytest tests/` appears to hang on this machine at ~24%. It is not a hang — `tests/test_codebase.py` is `@pytest.mark.slow` and `skipif(not SCRIPTIVA_ROOT.exists())`, and `C:/Users/kapil/Scriptiva_SCA` DOES exist here, so it walks a large external repo. Pre-existing and environment-dependent; the non-slow sweep is this repo's convention (see the `04e5bde` handoff). Earlier affected-area sweep: 344 passed / 0 failed (`-k "checkpoint or lint or session or scorecard or dashboard or backfill or gist or cli or mcp or transcript or state or oracle or telemetry"`), incl. 21 new state-algebra property tests, 20 trust-telemetry tests, 26 H-4 oracle tests. Full suite not re-run for this packet. Historic: main — 184 passed / 6 product-gated skips across fork/resume/rank/DAG/session-reader/negation/determinism/token/claims/compactbench/fixture-privacy suites, capability-registry + claims gates green; parked (`feat/fork-surfacing-parked` @ `57321b9`) — 162 passed / 1 skipped incl. negation + determinism gates (2026-07-12, post-re-review remediation)
- **Active owner:** Claude Code (session `95edc6ae`, 2026-08-09)
- **Current unit (2026-08-10, latest):** **journal-integrity follow-up APPROVED (`14ea469` all four acceptance cases PASS; `44595be` accepted)** → TM-5..7 unfrozen and **IMPLEMENTED: `31fc0ad..644731f`** (comment precision; TM-5 schema-routed receipts TC-10/11; TM-6 one trust-annotation path TC-12; TM-7+TM-14 stable error codes on receipts + hook stderr TC-13/17). Full non-slow **1783 passed / 35 skipped / 57 deselected**; 9 red-on-parent + 1 self-identified pin; **review requested on `31fc0ad..644731f`**. QUEUED owner decision: IncrementalPacker harden-or-retire before AMBIENT (mtime fast-path can hide equal-timestamp content change; zero callers). Next after approval: PF-15 → PF-16/16b → PF-17 (incl. raw-corpus egress fixture). Prior state: **re-re-review: FIVE OF SIX APPROVED** (`ae3c780`, `eee6dda`, `5e87547`, `fa031c0`, `b5a6d2c`); journal integrity completed in the required single follow-up **`14ea469`** (strict UTF-8, FileNotFoundError-only absence + `journal_read_failed` code, writer-side `by` validation; 4 acceptance tests, 3 red-on-parent + 1 self-identified pin) + invited non-blocking `44595be` (APP_SECRET, corpus truly 33). Full non-slow **1776 passed / 35 skipped / 57 deselected**. Reviewer-note format switched to acceptance-case tracking after the compressed-relay defect. **Scoped re-review requested on `14ea469`.** Prior state: all four P1 + both P2 re-review fixes landed as `ae3c780..b5a6d2c` (TM-2 local-cli, TM-3 strict ts/by, TM-8 CommonMark fence state, TM-1 *_KEY + span-consumption + full TC-1 matrix, TM-4 every occurrence, provenance tp/1.3 + redact/v2 stamped; 18 red-on-parent via worktree sweep). Prior state: **PF-11 v2.1 APPROVED** (threat model only — no E-6 approval, no live-enforcement claim) → Onto_Wiz owner-confirmed canonical (`85302ea`; artifact `scorecard-20260809T183423Z.json`, `e46984e`, `--check` green) → **P1 batch IMPLEMENTED, five one-mechanism commits each with its own TCs: `870387e` TM-1, `6953a44` TM-8, `b2b5b30` TM-2, `af11ee4` TM-3/16, `600aef9` TM-4.** Full non-slow suite 1752 passed / 35 skipped (one pre-existing flaky wall-clock timing test, passes in isolation, untouched since July — disclosed). **P1-batch re-review requested on `85302ea..600aef9` before TM-5..7 starts.** Loops 5–6, live hooks, paid runs, parked merges stay frozen. Prior state: **PF-11 v2.1 (`4afef09`, doc-only) approved** — the four contradictory capability statements are corrected: no elevated-local/owner-authority language; role-evidence sets never collapse into authority; hand-edited `.ctx` marked UNDETECTABLE TODAY (future read-time verification named, unscheduled, accidental class only); journal recovery = quarantine rotation with epochs. Execution rule banked: one mechanism per commit, each remediation ships its own TCs immediately, PF-17 is additive cross-boundary coverage. Prior state: **PF-11 v2 committed design-only.** v1 (`c6471c7`) drew four mandatory amendments, all applied: LOCAL_RATIFIED carries NO elevation (authority = four separate axes; owner-approval gate UNSATISFIABLE in v1); B6 control-plane boundary + Advisory/Enforced modes (no guarantee/prevent/block claims in advisory mode — TM-12); TM-8 corrected (fenced markers DO extract today — reviewer repro confirmed against `_sentences`; fence-aware extraction is now a planned fix); TM-13..16 added (ledger tampering/rollback-replay, diagnostic leakage, PF-15 deletion attacks incl. TOCTOU + plan-hash, ratification-journal DoS accepted-and-surfaced); git-commit identity removed as a human channel. TC list now TC-1..TC-20. Post-approval order: TM-1..4 units → TM-5..7 → PF-15/16/16b/17 → E-6 re-review → Loops 5–6 (held). Owner opens: **Onto_Wiz canonical confirmation (still provisional)**; LOCAL_RATIFIED rename objection window.
- **In-flight work (2026-08-07, current):** Loops 1–2 shipped (`d09a879`, `f259dd4`) → re-review CHANGES REQUESTED → **all seven residuals fixed same-day**: `6cce9c6` (receipt reader dict-only + shared validity + `ctx-injections/v2` full ids + unambiguous-prefix join + freshness-only `--check` claim + fail-closed cohort validation + dashboard "committed" overclaim removed), `62b4817` + `07882e9` (OntoWiz corrected to measured local repo — **canonical-ledger choice `Documents/Onto_Wiz` awaits owner confirmation**; artifact `scorecard-20260807T195126Z.json`: 7/7 measured, explicit recall 0.067, raw fallback 0.465, zero-recall 265 = 9 with-emission + 256 unmeasured + 0 empty/failed, injections 56/56, malformed 0 — cite the dated artifact, never "latest"). **Sequencing disclosure:** Loops 3 (`6768b74` authority provenance), 4a (`d2747d5` ingest redaction), 4b (`7d389e0` outgoing scan) were implemented before the changes-requested verdict arrived mid-session; they stand for re-review, and per the mandated order **PF-11 threat model is the next unit** — it must define the poisoning/authority boundary the committed PF-03 schema is then validated against. Loops 5–6 HELD. NO live hook (s:eca3f61c#turn802), NO paid run, NO parked merge. Prior thread unchanged: consolidated packet still awaits Codex re-check (`5f80e5b..3667094`).
- **Prior in-flight (2026-07-30):** trusted-session-resume hardening SHIPPED — `fc2489f` (canonical state algebra), `a815b78` (honest telemetry), `4ea08d4` (H-4 oracle), `76d766f` (four corrected documents), then **round-2 review fixes** `dcc8c14` (NOT_APPLICABLE fold leak), `0263e85` (structured-verdict H-4 grading + mandatory ledger binding), `3667094` (receipt written after emission; emitted-not-delivered naming). Full range for re-review: **`5f80e5b..3667094`**. Origin: OntoWiz field report 2026-07-25 + owner ratification. Three review rounds on this package, all findings fixed before commit; the packet sat uncommitted for five days while its own docs claimed "shipped" and "pre-registered", which is now corrected on the record rather than tidied away. **Standing:** query-surface expansion FROZEN (no new MCP tools); no scored/paid run authorized; Track C implementation gated on E-6 + deterministic spike + calibration. Next owner thread: **E-6**.
- **Prior thread (2026-07-13, unchanged):** scored run unlock=True $0.5056 (artifact `3e1aaee`, immutable) → artifact review 2 blockers FIXED (`815c1ed`, notes v5, lessons `c221851`) → fix re-review 2 residuals FIXED (`17ed897` byte-level evidence, `83f6af1` strict paths, notes v6 `2310ae7`) → round-3 re-review 2 fail-closed gaps FIXED (`e355196` absent-key sibling gate + denylist-free paths, notes v7 `e0fa952`) → **round-4 re-review of main `99b9697` + parked `da8d354`: P1 APPROVED, one P2 privacy residual → FIXED same-day**: `f679314` two-tier path scan (raw-string drive-letter/backslash-UNC/`file://` checks — URL-smuggled paths rejected; http(s) masking only for POSIX/forward-UNC; generic negative token boundary + non-whitespace path start — `path:/etc/passwd`, `see,/workspace/run`, `{/guides/x`, `/数据/private` rejected; HTTPS `/home/` acceptance retained) + notes v8 `32c2a46`. Parked updated: merge `bf6c1fd` + v8 dry-run receipt → head **`3f32ec3`**. STANDING: no replication approved, NO new $2 authorization, `3e1aaee` immutable, do-not-merge, parked-code review outstanding. Awaiting round-5 re-review (P2 scope only). Next owner thread: **E-6, not E-1**.
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

- [ ] **Q4 — A5 harness approval: drift-fork/v2 is built; approve text + harness (+ notes) before any paid call.** *(queue after Q2 re-check)*
  - Asked by: Claude Code (session `b6331eef`), 2026-07-12
  - Harness: `af6dda5` (`fork_cluster.py`, `run_resume_probe.py --probe-set drift-fork-v2`, 22 tests); zero-cost 8-cluster dry-run receipt: `94e31c4` (96 completions enumerated, all presence receipts pass, `pad_delta=0` everywhere, grep ≤ warn budget). Harness notes appended to the prereg (pre-approval, part of the reviewable package).
  - Specific asks: **(a)** cost-table correction — the A5 Arms section pins 4 contexts for fork probes but the Cost arithmetic said "3 arms"; harness implements the Arms section (96 completions ≈ $1.1–1.5, ceiling $2 unchanged). OK, or drop the unpadded `ctx-nowarn` secondary arm back to 80? **(b)** false-alarm control: on the clean no-fork ledger the product warning is correctly EMPTY, so the two ctx arms coincide by construction — the control measures fork-vs-linear discrimination + inverted-grade specificity. Acceptable as pinned, or should the control take a different shape? **(c)** inverted-grade anchors for false alarms pinned as prior chain values (vB/v0) verbatim or both chain sids — any modes missed?
  - Reviewer: findings under Reviewer Notes (or here); notes-only — owner applies fixes. After approval, the scored run additionally waits on Kapil's explicit ≤$2 go.

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

### 2026-07-11 — Claude Code (session `f40335cc`) — Q2 fixes (all 5) + A5 design shipped
- **What changed:** per the adopted Q3 ruling: A5 drift-fork/v2 prereg DESIGN (`af71a6d` — independent clusters, fixed-budget arms, negative controls, presence receipts; run gated on reviewer approval then ≤$2). All five Q2 findings fixed as separate review units: `af542a2` Q2-5 (state_parser→eval, lazy init import, `__init__.py` coverage + static core→legacy dependency gate) → `f9596b6` Q2-4 (frozen calibration fixtures w/ committed cl100k counts + sha pins; kill gate runs without tiktoken; dedicated tokenizer CI job; byte-canonical fixtures via `.gitattributes`) → `d260473` Q2-1 (all hydrate surfaces estimate their EMITTED text with matching labels; telemetry grouped by estimator, blended average removed; "Source words" relabel) → `ef7a879` Q2-2 (per-cell completed/partial/failed status, separated attempt/completed/failed spend, driver invocation ledger recording timeouts before propagation, memory-cache cost sidecars, accounting_complete flag) → `a1416b8` Q2-3 (inline `[CL:id]` claim IDs, widened backstop patterns verified zero README false positives, immutable-results allowlist + sha256-pinned artifacts, C3/C7 repointed off prose, C8 qualified two-seed within-run, papers/docs numeric WARN summaries) → `31191c0` test-isolation fix.
- **Tests run:** 177 across all touched suites + the three standing gates green (registry, claims, tool budget); full sweep includes negation-preservation + determinism gates.
- **Risks / concerns:** Q2-3 partially applied by design — line-FAIL outside README stays gated on the banked false-positive kill condition (papers/docs warn with per-file summaries instead); reviewer may want more. The smoke-to-bill ≤5% reconciliation (Q2-2 validation) is a live step needing separate approval. README's unevidenced `<2s` hook-latency claim was REMOVED rather than ledgered (no immutable artifact exists for it).
- **Next recommended action:** reviewer re-checks the five fixes (statuses link shas) + approves/amends A5; then Kapil's ≤$2 authorization for the drift-fork/v2 scored run. E-1/E-2 remain the next plan items.

### 2026-07-12 — Claude Code (session `b6331eef`) — A5 drift-fork/v2 harness shipped
- **What changed:** the A5 harness (`af6dda5`): `fork_cluster.py` — 8 pinned independent clusters (distinct ledger dirs, sid pairs, key/value families; run-wide non-substring + conflict-token validation), each with 2 planted forks + 1 linear displacement key plus a no-fork variant, ALL built through the real checkpoint producer; fixed-budget primary arms via a pinned sha256-stamped neutral filler (exact BPE parity — dry-run shows `pad_delta=0` on every padded arm, abort at |Δ|>3); per-probe presence receipts with the pinned >1-exclusion abort; cluster-level sign test / Wilson intervals / false-alarm gate / unlock. Runner: `--probe-set drift-fork-v2`, deterministic 96-completion enumeration, live-run interlock (`--authorized-run` required; `--clusters` dry-run only). Zero-cost dry-run receipt committed (`94e31c4`). Prereg harness notes appended pre-approval (cost-table arm-count correction 96-vs-80 among them — flagged as Q4 ask (a)).
- **Files touched:** `ctxpack/benchmarks/agentic/fork_cluster.py` (new), `run_resume_probe.py`, `tests/test_fork_cluster.py` (new, 22 tests), `ctxpack/benchmarks/agentic/PREREGISTRATION-resume-probe.md`, 1 result artifact (dry-run receipt).
- **Tests run:** 70 across fork/resume/DAG suites incl. negation-preservation + determinism gates; capability-registry, claims, and tool-budget gates green; end-to-end 8-cluster dry run verified (no API calls).
- **Risks / concerns:** the false-alarm control's two ctx arms coincide by construction (disclosed — Q4 ask (b)); A4's pinned-token under-count disclosure carries over arm-symmetrically; fixture remains synthetic (`fork_source` stamped) — a real cohort fork still supersedes it as preferred source.
- **Next recommended action:** Codex reviews Q2 fixes re-check + Q4 (A5 text + harness + notes). On approval, Kapil's explicit ≤$2 authorization unlocks the scored run (runner enforces the interlock). Owner's next plan items meanwhile: E-1 probe hardening / E-2 CompactBench prereg v2.

### 2026-07-12 — Claude Code (session `b6331eef`) — all 6 cf2753c review findings fixed on the parked branch
- **What changed (on `feat/fork-surfacing-parked`, one commit per finding, branch STAYS parked):** `ca9029b` F1 status-bearing fold (`load_supersession(with_status=True)` distinguishes missing vs unreadable/malformed events; degraded folds preserve candidates.jsonl, journal `degraded`, and render a top-priority gist banner; atomic candidate writes) → `24138c9` F2 simulated-fallback removed (`missing_product_warning()` pre-flight, run aborts naming failing probes; `warn_arm_source` only ever product output) → `3fcd7f4` F3 copy = "independent successor facts" in both renderers, detector unchanged, same-session + 3-head tests → `6662d85` F4 byte-identity scoped to .ctx/gist/events and tested vs pre-feature sha256 goldens; journal versioned `ctx-checkpoints/v2` → `edade6d` F5 fork block: per-family caps (3 heads / 2 roots), 600-BPE sub-budget, whole-family drops with explicit counts, structural floor; high-fan-out + 10-family tests → `c715dc5` F6 A3 numeric efficacy copy removed from production comments/test docstring/onboarding; merge evidence = the approved A5 artifact.
- **Main-branch twin:** the A5 harness's simulated warn block got the same F3 copy fix + a fresh zero-cost 8-cluster dry-run receipt (pad deltas still 0, receipts all pass); the earlier receipt stays immutable.
- **Tests run:** parked branch 75 (fork surfacing 14 + fork probe + DAG + session reader + negation + determinism); main 38 (fork probe + fork cluster).
- **Risks / concerns:** F3 resolved via the copy option (detector still flags same-session double-supersession — arguably a real unreconciled state; reviewer may prefer the distinct-sessions detector instead, one-line change). F4 goldens pin the pre-feature producer at `94e31c4`; a legitimate future serializer change must regenerate them consciously.
- **Next recommended action:** reviewer re-checks Q2 fixes, the six parked-branch fixes, and Q4 (A5 text + harness + notes); then Kapil's ≤$2 go for the scored run. Owner's next thread: E-1 probe hardening / E-2 CompactBench prereg v2; E-6 security stays elevated and blocks external pilots.

### 2026-07-12 — Claude Code (session `d84e91c2`) — consolidated review packet applied (Q2 residuals + parked F1 + A5 v2)
- **What changed (main `feat/literals-ledger`, one commit per unit):** `4f24183` board record → `8c09099` Q2-1 (CLI `--list` + MCP section listings label their ctx-kind token estimates) → `6a66bc2` Q2-2 (failed/timed-out probe calls raise DriverError → cell partial/failed, never a completed-cell miss; ledger-only known spend folds into `run_cost_usd` via `unattributed_known_cost_usd`; a materially negative reconciliation delta flips `accounting_complete` off) → `97d78c3` Q2-3 (an inline `[CL:id]` covers only when the CITED row's own cover strings match the line; `_allowlisted` resolves the artifact path before deciding containment; the old test that encoded the bypass now asserts the fix) → `73c3099` Q2-4 (raw KP_SDLC calibration fixture replaced by a fully synthetic `meridian-etl` ledger, generator committed alongside; cl100k count + sha re-pinned in the same change, chars/3 error −4.3%; policy note added) → `2a3ec39` A5 harness v2 (all nine blockers + answers a/b/c: product-sourced treatment with in-place placebo, pinned `_VARIATIONS` cluster diversity, A4.1 polarity grade `drift-fork-grade/v2.1`, error-abort retry policy, enforced $2 ceiling with pinned `claude-sonnet-4-6` + durable `invocations.jsonl` + preflight worst-case + running guard, tiktoken required + context/filler/manifest/harness-commit sha stamps, any failed receipt aborts + exact 8×2 completeness, 0/8 false-alarm + displacement non-inferiority hard gates, counterbalanced arm order, **88 completions** replacing the 80/96 contradiction; prereg harness notes v2 pin all of it).
- **Parked branch (STAYS PARKED, no merge):** `2a5e612` F1 re-check fix (missing events.jsonl at `_fork_report` = degraded — candidates preserved, banner rendered, regression added) → `4d9ec14` merge of main into parked (the reviewer's "updated parked branch") → `1e59fad` fresh zero-cost 8-cluster dry-run receipt: 88 completions, ALL receipts pass incl. the detector-output receipts, pad deltas {0,1} (bound ±3), preflight worst-case **$0.9596** under the $2 ceiling, tokenizer `tiktoken 0.12.0 cl100k_base` + manifest + harness commit stamped, zero API calls.
- **Tests run:** main — 70 fork-suite (6 product-gated skips by design: plan construction needs the product renderer) + 98 regression (DAG/session-reader/negation/determinism/token/claims/compactbench) + standing gates green (registry, claims, tool budget). Parked — **121 passed / 1 skipped** (the product plan tests RUN there; the single skip is the pre-feature abort test, meaningful only on main).
- **Risks / notes:** (a) A5 scored runs execute from the parked branch only — the main-branch harness ABORTS by design rather than simulate; (b) `tests/fixtures/rank_v1/kp_sdlc_ca35891c_events.jsonl` carries the same raw-cohort privacy class (123 personal-path hits) but is the LABELED fixture behind rank/v1's measured priors — replacing it is a deliberate re-label, proposed as an E-6 work item, not done unilaterally; (c) the withdrawn calibration fixture remains in git history — purging needs a history rewrite (owner call); (d) the displacement non-inferiority margin is pinned at ≤1 harmful-discordant cluster — reviewer may prefer a different bound; (e) A4.1's clause-window negation has a disclosed enumerated-negation limitation ("not a conflict, fork, or divergence" grades positive — arm-symmetric).
- **Next recommended action:** reviewer re-checks this packet (Q2 residuals, F1, Q4/A5 v2 + receipt `1e59fad`); after approval, Kapil's explicit ≤$2 go (runner enforces the interlock, pinned model, and ceiling). Owner's next thread per the reviewer's instruction: **E-6 before E-1**.

### 2026-07-12 — Claude Code (session `fb94cd9f`) — all five recheck residuals remediated (headline relay grounded against code)
- **Context:** the reviewer's recheck arrived as headlines only (see the recheck Reviewer Note above); the owner grounded each name against the code at `a7164cd` before fixing, and every operationalization below is disclosed for the substantive re-review — **flag any divergence from the intended finding**.
- **What changed (main `feat/literals-ledger`, one commit per unit):** `4c011e4` board record → `a9f7e56` **A4.2 grading** (`drift-fork-grade/v2.2`, prereg harness notes v3 item 1: negation scope extends across comma enumeration continuations — bare ≤3-word fragments or or/and/nor openers ≤4 words; hard punctuation still resets; "no objection at first glance, but this fork is real" still flags; disclosed limitation pinned as a test: "no delays, fork detected" reads as an enumeration; prospective only, no scored run exists) → `1b7379f` **retry-level budget enforcement** (v3 item 2: single-attempt `fidelity.anthropic_attempt` + `fork_cluster.call_with_budget` own the loop — every attempt ceiling-guarded BEFORE issue, ledgered durably before (`issued`) and after (`result`) each call; pinned accounting: ok = actual priced usage, transient HTTP rejection = $0 (not billed, no usage block), unknown-billing outcome reserves the full worst case — a tightening over v2, which never counted a timed-out call's possible spend) → `e150b4d` **empty-response abort** (v3 item 3: an empty/whitespace HTTP-200 completion aborts the scored run — the v2 loop graded it as a miss; no silent retry, cost still charged) → `1e3e656` **exact-manifest gate** (v3 item 4: `PINNED_CLUSTER_MANIFEST_SHA256` = `554f2492…`; every run, dry or live, aborts on mismatch via `require_pinned_manifest`; input changes now require a conscious re-pin in the same diff) → `7438514` **E-6A privacy cleanup** (rank/v1 fixture pseudonymized IN PLACE: the rows carry no prose — the privacy class was exactly the personal `cwd` on all 123 rows, the real session UUID, and verbatim quotes in `labels.json`; `anonymize_fixture.py` committed as the receipt; fold scores byte-identical so the ratified rise/sink labels stay empirically anchored — full synthesis (Q2-4 style) was not needed because this fixture is not sha-pinned and the redaction is mechanically verifiable; a standing no-personal-paths gate test guards regression; pre-anonymization file remains in git history — owner call on a rewrite, same disclosure as Q2-4).
- **Parked branch (STAYS PARKED, no merge):** merge of main `a53d6fd` → fresh zero-cost dry-run receipt **`caa45b8`**: 88 completions, ALL receipts pass, pad deltas {0,1} (bound ±3), preflight worst-case **$0.9596** under the $2 ceiling, grade id v2.2 + verified manifest + retry policy v3 + tokenizer stamped, zero API calls.
- **New SHAs for the substantive re-review (as requested):** main head = this board commit (remediation range `4c011e4..7438514`); parked head = **`caa45b8`**.
- **Tests run:** main — 174 passed / 6 product-gated skips (fork/resume/rank/DAG/session-reader/negation/determinism/token/claims/compactbench) + capability-registry and claims gates green; parked — 152 passed / 1 skipped (product plan tests run there; the skip is the pre-feature abort test).
- **Risks / concerns:** (a) the relay carried headlines only — if any fix misreads the intended finding, say so and the owner re-does that unit; (b) A4.2's enumeration heuristic neutralizes a genuine flag phrased as a bare ≤3-word fragment after a negated comma segment (disclosed, arm-symmetric, pinned as a test); (c) transient-rejection-at-$0 accounting assumes rejected HTTP calls are unbilled (no usage block) — worst case is reserved wherever billing is unknown; (d) E-6A deliberately did NOT re-label: pseudonymization preserved every fold score, so the rank/v1 empirical anchor survives — if the reviewer intended full synthetic replacement instead, that is the re-label decision the 2026-07-12 handoff flagged as an owner call.
- **Next recommended action:** reviewer performs the substantive re-review against the SHAs above; on approval, Kapil's explicit ≤$2 go (runner enforces interlock, pinned model, ceiling, manifest gate). Owner thread meanwhile: **E-6 (threat model + secret redaction), not E-1**, per the standing instruction.

### 2026-07-12 — Claude Code (session `fb94cd9f`) — all four substantive-re-review blockers remediated
- **What changed (main `feat/literals-ledger`, one commit per finding):** `70b9d9b` board record → `21ef27d` **finding 1, result-set manifest gate** (`validate_result_manifest`: exact unique (cluster, ptype, probe_id, arm) set — 88 rows, no duplicates/unexpected rows, one false-alarm observation per cluster, complete displacement pairs, 2 fork probes × 4 arms; the runner validates against the plan's key set before analysis, deviation aborts `result-manifest`; `cluster_analysis` gates are now vacuity-proof — the false-alarm gate requires all 8 clusters OBSERVED, the displacement gate requires 8 complete pairs; deletion/duplication/unexpected-arm/plan-mismatch tests; the v3 input-table pin stays in force alongside) → `ad1434d` **finding 2, A4.3 grading** (`drift-fork-grade/v2.3`, implemented as prescribed: negation tracks the negated conflict — clause-wide scope from any negator, restored to positive by pinned contrast markers, broken by non-continuation comma segments, inherited by or/and/nor enumerations; all three reviewer cases pinned as tests — the two negated-conflict dismissals grade negative, "no delays, fork detected" grades POSITIVE, the A4.2 limitation is withdrawn not disclosed away; new disclosed limitation pinned: a flag under a negated attention verb ("we cannot ignore the unresolved fork") is neutralized — cannot create false alarms since that direction needs a positive flag) → `e613139` **finding 3, full-request worst case** (`request_worst_case_usd` prices the ENTIRE request incl. `_build_prompt` wrapper + system prompt, then pinned `TOKENIZER_HEADROOM=1.25` + `REQUEST_OVERHEAD_TOKENS=64`; the SAME bound backs preflight and every per-attempt guard; `invocations.jsonl` now fsyncs after every append) → `aed94a5` **finding 4, E-6A widened** (`ctx_session_frozen.ctx` replaced by a fully synthetic session ledger — fictional `lattice-docs` repo, deterministic `gen_synth_session.py` committed, cl100k+sha re-pinned same change, chars/3 −0.57%; `gen_synth_cohort.py` output now `__file__`-relative; new `tests/test_fixture_privacy.py` sweeps ALL of `tests/fixtures/**` — owner username forbidden outright, home-dir paths must name a pinned fictional user (dev/Müller/zoë)).
- **Parked branch (STAYS PARKED, no merge):** merge of main `0a4a37a` → fresh zero-cost dry-run receipt **`57321b9`**: 88 completions, ALL receipts pass, grade id v2.3, input-manifest gate verified, preflight worst-case **$1.0667** under the $2 ceiling with the new conservative bound, zero API calls.
- **New SHAs for re-review:** main head = this board commit (remediation range `70b9d9b..aed94a5`); parked head = **`57321b9`**.
- **Tests run:** main — 184 passed / 6 product-gated skips (fork/resume/rank/DAG/session-reader/negation/determinism/token/claims/compactbench/fixture-privacy) + capability-registry and claims gates green; parked — 162 passed / 1 skipped.
- **Risks / concerns:** (a) A4.3's clause-wide scope neutralizes flags phrased under negated attention verbs (pinned + disclosed in prereg notes v4; the anchor requirement and positive-flag false-alarm direction bound the damage); (b) the $1.0667 preflight uses the deliberately conservative bound — actual spend will land well below it; (c) the withdrawn real-session and KP_SDLC fixtures remain in git history — the history-rewrite decision stays with the owner.
- **Next recommended action:** reviewer re-reviews against the SHAs above; on approval, Kapil's explicit ≤$2 go. Owner thread meanwhile: **E-6 (threat model + secret redaction), not E-1**.

### 2026-07-13 — Claude Code (session `fb94cd9f`) — A5 SCORED RUN EXECUTED (authorized): unlock=True, all gates pass, $0.5056
- **Authorization chain:** reviewer approval of main `37bdb99` + parked `57321b9` (note above) AND Kapil's explicit ≤$2 go, both received 2026-07-13 before any paid call.
- **Execution:** from the parked head `57321b9` exactly, via an isolated git worktree (live repo untouched); `python run_resume_probe.py --probe-set drift-fork-v2 --authorized-run`; harness stamped its own commit into the artifact (`harness_commit: 57321b9…`); input-manifest gate verified (`554f2492…`); result-set manifest gate passed (88/88 graded rows = the enumerated plan); zero aborts.
- **Results (cluster-level, pre-registered A5 + harness notes v2–v4, grade `drift-fork-grade/v2.3`):**
  - **Primary:** cluster-mean fork-miss **padded-nowarn 1.0 vs warn 0.0**; sign test 8/8 clusters warn-better, ties 0, **p_one_sided = 0.0039**.
  - **False-alarm gate:** 0/8 flagged, 8/8 observed — **passed**.
  - **Displacement non-inferiority:** 0 harmful discordant (max 1), 8/8 complete pairs, both arms 8/8 correct (Wilson95 [0.676, 1.0]) — **passed**.
  - **Secondary (disclosed, non-inferential):** unpadded nowarn 0.0 vs warn 1.0 over 16 fork probes; mean warn block 377 BPE; **grep null 0.875** (14/16 — the honest null remains strong and is disclosed, not gated).
  - **Unlock rule: ALL terms satisfied → `unlock: true`.**
- **Spend:** **$0.5056** actual vs $1.0667 preflight worst case vs $2.00 ceiling; model pinned `claude-sonnet-4-6`; 88 calls / 176 fsync'd invocation-ledger rows.
- **Immutable artifact (new versioned files, parked branch commit `3e1aaee`):** `ctxpack/benchmarks/agentic/results/resume-probe-fork-fixture-v2-drift-fork-v2-full-20260713T124646+0000.json` (+ sibling `.invocations.jsonl`, the durable per-attempt ledger). Artifact sha256 prefix `304da6c795e26e51`.
- **New parked head for artifact review: `3e1aaee`** (parent `57321b9`, the approved head — the only delta is the two result files; no code changed).
- **Branch state: STAYS PARKED.** Per the reviewer's verdict and the unlock rule, merge additionally requires (1) the reviewer's review of this scored artifact and (2) the separate code review of the parked implementation. No merge performed; no further paid runs planned.
- **Risks / concerns:** (a) primary effect is at ceiling (miss 1.0 vs 0.0) — consistent with the sentinel-run pattern that unwarned decisions die after compaction, but the fixtures are synthetic and the claim stays scoped to SURFACING on this fixture family; (b) grep at 0.875 is within 1 cluster-probe of warn — the differentiation claim remains literal-exactness/reliability, not raw recall (pre-committed grep rule stays in force); (c) worktree ran under the session temp dir — results carry no workspace paths (verified: artifact stamps repo `fork-fixture-v2`).
- **Next recommended action:** Kapil relays parked `3e1aaee` (artifact commit) to Codex for the artifact review + parked-code review. Owner thread meanwhile: **E-6 (threat model + secret redaction), not E-1**.

### 2026-07-13 — Claude Code (session `fb94cd9f`) — both artifact-review blockers remediated + cross-repo lessons registry shipped
- **Evidence determination first (reviewer next-action 1):** the original full responses exist in NO retained log — the fsync'd ledger's result rows carried status/cost/usage only, the work dir holds cluster builds + the ledger, the runner kept answers in memory. Recorded in the verdict note above; therefore the replication path applies and **no paid run was made this session**.
- **Blockers 1+2 fixed in ONE commit `815c1ed`** (deliberate deviation from one-commit-per-finding: a single shared gate implements both findings — splitting it would have duplicated the mechanism):
  - **Blocker 1 (verbatim evidence):** result rows now store the COMPLETE answer + `answer_sha256`; the fsync'd invocation ledger's ok/empty rows store the same verbatim answer + sha (the durable ledger IS the immutable retained log). `fork_cluster.validate_report_evidence()` runs BEFORE any artifact write on every path (scored/aborted/dry): graded rows must match their own sha AND the ledgered row's sha byte-for-byte, else no artifact is written.
  - **Blocker 2 (artifact hygiene):** the artifact now references its ledger as a committed sibling — relative filename + SHA-256 (`invocation_ledger` / `invocation_ledger_sha256`); dry runs stamp null. The same pre-write audit refuses ANY report string carrying machine-local paths or the owner identity (forbidden set mirrors the E-6A fixture gate incl. fictional-user allowlist). Disclosed: earlier dry-run receipts in git history also stamped absolute temp paths — immutable, prevented going forward; history rewrite stays the owner's call.
  - Prereg: **harness notes v5** appended (`eb587ed`) — verbatim-evidence rule, artifact-hygiene rule, and the pinned replication protocol: any future scored run of this probe set is a CLEARLY LABELLED REPLICATION requiring fresh reviewer approval AND fresh budget authorization. The `3e1aaee` scored artifact is untouched (sha `304da6c7…` unchanged).
- **Cross-repo lessons registry (owner initiative, Kapil-requested; `c221851`):** `ctxpack/agent/lessons.py` + `ctxpack lessons [--check|--json]` — curated, evidence-linked lessons distributed to cohort repos through the onboard CLAUDE.md block (marker now `v5.L1`; a lessons bump alone refreshes every repo on re-onboard — this is how KP_SDLC stays regularly aware). Seeded with six reviewed lessons from this program (verbatim evidence, artifact hygiene, synthetic fixtures, immutable results/abort-on-error, polarity-aware graders, code-enforced paid-run interlocks). Scope firewall honored: promotion is manual with receipts; no auto-promotion until ≥2-repo incident-evidence machinery exists (ratified learning-layer design).
- **Parked branch (STAYS PARKED), head now `d81bfbd`:** merge of main `ca2724e` → fresh zero-cost dry-run receipt `d81bfbd` — 88 completions, all receipts pass, grade v2.3, worst case $1.0667, zero API calls, and the FIRST receipt produced under the new self-audit (`invocation_ledger: null`, no machine-local strings — verified).
- **Tests:** main sweep 218 passed / 6 product-gated skips (fork/resume/rank/DAG/session-reader/negation/determinism/token/claims/compactbench/fixture-privacy/lessons/onboard/cli + capability registry); parked sweep 184 passed / 1 skipped.
- **New SHAs for re-review:** main head = this board commit (remediation `815c1ed..c221851`); parked head = **`d81bfbd`**.
- **Risks / concerns:** (a) full answers in artifacts make scored artifacts larger and they now embed model prose verbatim — acceptable (synthetic fixtures; the audit gates identity/path leaks), flagging for reviewer awareness; (b) the report self-audit will refuse to write an artifact for an aborted run whose exception text carries a local path — console + work-dir ledger remain for diagnosis (deliberate: privacy over convenience on a release surface); (c) KP_SDLC pickup requires running `ctxpack onboard` there + a CC restart (standing cohort-restart caveat).
- **Next recommended action:** Kapil relays main head + parked `d81bfbd` to Codex for re-review of the two fixes; the separate parked-code review remains outstanding; replication (if the reviewer wants one) needs fresh approval + a fresh ≤$2 authorization. Owner thread meanwhile: **E-6, not E-1**.

### 2026-07-13 — Claude Code (session `fb94cd9f`) — both fix-re-review residuals remediated (byte-level audit, strict path rule)
- **Residual P1 fixed (`17ed897`):** `validate_report_evidence()` no longer trusts any DECLARED hash — every ledgered ok/empty row's answer must RECOMPUTE to its own sha256 (corrupted ledger content with a stale sha fails); graded artifact rows must be **byte-identical** to their ledgered ok-row answer, not merely sha-equal by declaration; and the sibling ledger's **actual file bytes** are now part of the audit — they must hash to the stamped `invocation_ledger_sha256` AND parse to exactly the report's embedded invocation rows, row-for-row. The runner passes the bytes it is about to write into the audit; invocations without a declared sibling are refused. Tests: corrupted-ledger-bytes (stale sha), self-consistent-but-diverging ledger row, tampered sibling bytes (sha mismatch), re-stamped tampered file (row mismatch), declared-but-missing bytes.
- **Residual P2 fixed (`83f6af1`):** strict absolute-path matcher on the artifact surface — drive-letter (`C:\tmp`, `D:\scratch`, `e:/x`), msys-munged (`/c/...`), UNC (`\\host\share`), POSIX system roots (`/tmp` `/var` `/scratch` `/opt` `/srv` `/private` `/home` `/users` `/mnt` `/media` `/root`), and any home-directory segment inside a path. **No fictional-path allowance on artifacts** (that allowance stays fixture-gate-only) — safe because the synthetic fork fixtures emit no absolute paths at all, verified against both committed artifacts: the strict matcher correctly FLAGS the immutable `3e1aaee` artifact's known disclosed leak and PASSES the post-fix receipts. Reviewer's four example classes pinned as tests; URLs/relative names stay accepted.
- **Prereg:** harness notes v6 appended (`2310ae7`) — supersedes v5's audit description on both points; standing state restated (no replication approved, no new $2 authorization, `3e1aaee` immutable, do-not-merge, parked-code review outstanding).
- **Parked (STAYS PARKED), head now `737ceac`:** merge `287f7b7` + fresh zero-cost dry-run receipt `737ceac` produced under the byte-level audit + strict path rule (88 completions, all receipts pass, worst case $1.0667, zero API calls, `invocation_ledger: null`).
- **Tests:** main sweep 220 passed / 6 product-gated skips; parked sweep 111 passed / 1 skipped (core suites) — full parked sweep matches main minus product-gated differences.
- **New SHAs for re-review:** main head = this board commit (remediation `17ed897..2310ae7`); parked head = **`737ceac`**.
- **Next recommended action:** Kapil relays the new SHAs to Codex. Still outstanding after this round: the separate parked-code review; replication only on fresh reviewer approval + fresh ≤$2 authorization. Owner thread: **E-6, not E-1**.

### 2026-07-13 — Claude Code (session `fb94cd9f`) — round-3 residuals remediated (absent-key sibling gate, denylist-free path rule)
- **Residual P1 fixed (`e355196`):** the sibling requirement no longer depends on key membership — a report carrying invocations is refused unless a sibling ledger is DECLARED and its bytes verify; a null `invocation_ledger` and an entirely absent key both fail. The accepted test fixtures were themselves the bypass vector (they omitted the key), so they now declare the sibling and supply its bytes; an explicit deleted-key regression test is pinned.
- **Residual P2 fixed (same commit `e355196`):** the path rule is now denylist-free — ANY token-leading POSIX absolute path is rejected (`/etc/passwd`, `/usr/local/bin`, `/workspace/run`, and the innocuous-looking `/guides/section-1/` alike; the old root allowlist is gone), plus forward-slash UNC (`//server/share`) and `file://` URIs (a path wearing a scheme). The one documented exclusion, per the reviewer's suggested shape: http(s) URL spans are masked out BEFORE the path scan — the HTTPS `/home/` false-reject is regression-tested; owner-identity substrings are still checked on the raw string, URLs included. All five reviewer round-3 cases pinned as tests.
- **Artifact re-verification under the tightened gate:** both committed post-fix dry-run receipts (v5 `135231`, v6 `145310`) PASS; the immutable `3e1aaee` scored artifact still FAILS on its known disclosed leak (evidence of the old defect, unchanged, sha `304da6c7…` untouched).
- **Prereg:** harness notes v7 appended (`e0fa952`) — supersedes v6's audit description on both points; standing state restated.
- **Parked (STAYS PARKED), head now `da8d354`:** merge `64c15fd` + fresh zero-cost dry-run receipt `da8d354` — the FIRST receipt produced under the round-3 audit (88 completions, all receipts pass, worst case $1.0667, zero API calls, `invocation_ledger: null`).
- **Tests:** main full non-slow sweep 1552 passed / 35 skipped; harness-adjacent set 89 passed / 6 product-gated skips; parked core sweep 94 passed / 1 skipped.
- **New SHAs for re-review:** main head = this board commit (remediation `e355196..e0fa952`); parked head = **`da8d354`**.
- **Risks / concerns:** the strict rule means a scored run whose MODEL ANSWERS happen to contain an absolute-path-shaped token (e.g. quoting `/etc/passwd`) will abort at write time with no artifact — deliberate fail-closed behavior on a release surface (console + work-dir ledger remain for diagnosis), flagged for reviewer awareness since answers are model-generated.
- **Next recommended action:** Kapil relays main head + parked `da8d354` to Codex for round-4 re-review. Still outstanding: the separate parked-code review; replication only on fresh reviewer approval + fresh ≤$2 authorization. Owner thread: **E-6, not E-1**.

### 2026-07-13 — Claude Code (session `fb94cd9f`) — round-4 P2 residual remediated (two-tier path scan)
- **Fix (`f679314`), implemented exactly along the reviewer's four suggested steps:**
  1. **Raw-string tier:** drive-letter, backslash-UNC, and `file://` patterns now check the UNMASKED string — these forms are never legitimate inside an http(s) URL on this artifact surface, so `https://host/upload?path=C:\tmp\work`, `https://host/x,file:///tmp/run`, and a URL-embedded `\\fileserver\share` are all rejected (pinned).
  2. **Masked tier:** http(s) URL masking now applies ONLY to POSIX-absolute and forward-slash-UNC detection (the one documented allowance).
  3. **Generic boundaries:** the delimiter and ASCII allowlists are gone — token boundary is a generic negative class (any non-word, non-slash character delimits: `:`, `,`, `{`, `-` included), path start is any non-whitespace, non-slash character. `path:/etc/passwd`, `see,/workspace/run`, `{/guides/x`, and Unicode `/数据/private` all rejected (pinned).
  4. **Regressions retained:** the HTTPS `/home/` acceptance test is unchanged and still passes.
- **Artifact re-verification:** all three committed dry-run receipts (v5 `135231`, v6 `145310`, v7 `164219`) PASS the round-4 matcher; the immutable `3e1aaee` still FAILS on its known disclosed leak (untouched, sha `304da6c7…`).
- **Prereg:** harness notes v8 appended (`32c2a46`) — supersedes v7's masking description.
- **Parked (STAYS PARKED), head now `3f32ec3`:** merge `bf6c1fd` + fresh zero-cost dry-run receipt `3f32ec3` — the FIRST receipt produced under the two-tier scan (88 completions, all receipts pass, worst case $1.0667, zero API calls, `invocation_ledger: null`).
- **Tests:** main full non-slow sweep 1552 passed / 35 skipped; fork suite 62 passed / 6 product-gated skips; parked core sweep 94 passed / 1 skipped.
- **New SHAs for re-review:** main head = this board commit (remediation `f679314..32c2a46`); parked head = **`3f32ec3`**.
- **Next recommended action:** Kapil relays main head + parked `3f32ec3` to Codex for round-5 re-review (scope: the P2 fix only — P1 is approved). Still outstanding: the separate parked-code review; replication only on fresh reviewer approval + fresh ≤$2 authorization. Owner thread: **E-6, not E-1**.

### 2026-07-13 — Claude Code (session `fb94cd9f`) — transcript adapters shipped: Codex first-class + generic spec adapter + hollow fail-loud guard (`57bbfa2`; Kapil-ratified, separate from the A5 review cycle)
- **Origin:** another team correctly declined to install capture hooks on Codex sessions (parser was CC-only; a foreign transcript silently parsed to an empty corpus — the hollow-ledger failure class, same as the bracket blast-radius incident). Kapil ratified: build it, prioritize Codex alongside Claude Code, no hardcoding for other agents.
- **Architecture (one pipeline, many formats):** `ctxpack/agent/transcript_adapters.py` normalizes every format into Claude-Code-shaped entries, so the entire extraction pipeline (markers, literals, incidents, constraints, sidechain verdicts) is shared. CC = byte-identical passthrough (full suite green, determinism preserved). Codex = rollout `session_meta`/`response_item` mapping pinned against real local rollouts (`event_msg` duplicates/telemetry skipped, encrypted `reasoning` skipped, role=developer + instruction envelopes never bank). Any other agent = `GenericJSONLAdapter` with a JSON field map via `--format-spec` — explicit only, NEVER auto-sniffed.
- **Fail-loud guard (both halves):** unrecognized format → `TranscriptFormatError` at parse (never a silent empty corpus); non-trivial transcript normalizing to nothing → `HollowTranscriptError` BEFORE any write. CLI checkpoint + MCP `ctx_checkpoint` = hard error; hook path = existing fail-open converts it to a loud stderr skip — the previous good gist is untouched byte-for-byte (test pins this).
- **Evidence:** 15 new tests (synthetic fictional-user fixtures only, privacy gate respected); full non-slow sweep **1567 passed / 35 skipped**; read-only smoke on the 5 most recent REAL local Codex rollouts — all auto-detected, extraction live (e.g. one session: 55 entities, 2 decisions, 44 literals from 1203 raw lines).
- **Standing gate honored:** cohort/KP_SDLC hook installs for Codex repos remain BLOCKED until a resume-probe-style eval runs on a real Codex transcript (the eval-evidence constraint banked 2026-07-13). What shipped is the substrate + deterministic smoke, not an install approval.
- **A5 review cycle unaffected:** the round-5 SHAs under review stay main `888324b` + parked `3f32ec3`; this feature is a later main commit (`57bbfa2`) and was NOT merged to the parked branch.
- **Next recommended action:** owner thread E-6 unchanged; Codex-capture eval probe to be scheduled after the A5 cycle closes; reviewer may include `57bbfa2` in a future pass (not part of round-5 scope).

### 2026-07-21 — Claude Code (session `fb94cd9f`) — capture-coverage reconciliation shipped (`04e5bde`; Kapil-ratified, from the setu field report)
- **Origin (field evidence, banked in owner memory):** setu's agent self-diagnosed that a whole session (their live task) was never packed — crash/kill//clear skipped the hooks — and the gap was invisible until file-mtime archaeology. Validated in the same report: identifier_fidelity 1.0/61 checkpoints, "orientation not truth" role, contradiction-detection value. The hollow guard (`57bbfa2`) protects write integrity; this package protects the other half, COVERAGE.
- **Shipped:** `ctxpack/agent/backfill.py` — `capture_coverage` (packed/stale/unpacked/active per transcript + worktree-local-ledger flag), `ctxpack backfill [--dry-run]` (idempotent, per-session fail-open with reported skips), **archive mode** in `run_checkpoint` (a backfilled past session never touches `latest-gist.md`, never hijacks `resolve_session`'s default — archive-flagged journal rows; `session_reader` prefers the last LIVE row), SessionStart hook now prepends a loud `[ctx capture gap]` line when unpacked transcripts exist (fail-open), scorecard gains per-repo `capture` block + cohort `capture_unpacked`.
- **Evidence:** 10 new tests; full non-slow sweep **1577 / 35-skip**; dogfooded live on THIS repo — coverage found 1 stale session (`a4f3cf5f`), backfilled in archive mode (28 entities, 55 turns), default session resolution verified unaffected.
- **Open design question (Kapil):** worktree ledger anchoring — coverage/doctor now FLAGS a worktree-local ledger, but anchoring worktree sessions to the main repo's ledger (`git rev-parse --git-common-dir`) is an undecided write-location change.
- **Cohort:** setu's Jul-20 session is recoverable with one `ctxpack backfill` run in their repo (after their ctxpack update); root cause of the drop still unconfirmed (restart-caveat suspected). Prime cohort-report material.
- **A5 review cycle unaffected:** round-5 SHAs stay main `888324b` + parked `3f32ec3`; not merged to parked.

### 2026-07-30 — Claude Code (session `fb94cd9f`) — trusted session resume: telemetry honesty, state algebra, H-4 oracle (`fc2489f`, `a815b78`, `4ea08d4`, `76d766f`)
- **Origin:** OntoWiz field report 2026-07-25 — a second independent report of the read path going entirely unused (zero `ctx/session_*` calls), plus a stale-fact incident (banked "the reseal test is a pre-existing red", green at HEAD) and an estimate that a hook plus a hand-maintained markdown file reproduces ~70% of the value exercised. Owner-ratified direction: *a flat file remembers; CTX explains what it remembers, how it knows it, what capture failed, and what may no longer be true.*
- **`fc2489f` — canonical state algebra** (`ctxpack/core/states.py`, `ctx-states/v1`). Replaces four competing vocabularies with two independent fact axes plus a delivery axis. Lifecycle `draft/banked/superseded/retracted` (forward-only; `expired` dropped — evidence ageing is a freshness statement). Freshness `not_applicable/unanchored/not_checked/current/stale/invalid` (`NOT_APPLICABLE` isolated both directions). `worst()` folds worst-first so a healthy observation never conceals an unhealthy one. Definitions only: nothing reads the repo or changes rendered output. 21 property tests incl. exhaustiveness guards.
- **`a815b78` — telemetry honesty.** Three defects of one class, a coverage claim wider than the work done. (1) The gist rendered `N comparisons (D × C)`; the live ledger showed 1001 rendered as (31 × 40) = 1240 — false whenever the turn gate excludes a pair or a protected subject is checked. **A test asserted that identity and passed**, because its fixture triggered no gating: the test pinned the bug. Now marginals only, with two exact identities and an adversarial turn-gated fixture. (2) On hitting `MAX_ROWS` the loop breaks but meta reported `len(decisions)` as linted; now `decisions_examined` vs `decisions_in_scope` plus a `truncated` flag. (3) Delivery was described as consumption in the dashboard, scorecard and plan — an injection receipt proves bytes were emitted, not that a model read or benefited from them. Zero-recall is now split by delivery receipt (an absent log reports *unmeasured*, never zero).
- **`4ea08d4` — H-4 oracle** (`h4-oracle/v1`). The protocol claimed the resume-probe generator could instantiate stale-claim probes; it cannot — H-4 needs a second source of truth the generator has never had, so an ungradable handoff would have entered a scored run. Adds an immutable content-addressed manifest (six required fields, no defaults), hard completeness checks, **exact row sets** (intersection scoring is how a truncated run reports as complete), **mandatory negative controls** (only-stale manifests cannot distinguish freshness tracking from blanket hedging), and a mutation test flipping the gate red. Found and fixed while testing: the grader substring-matched, scoring "test_reseal passes at HEAD" as an assertion of "the reseal test is red" — the exact inversion H-4 measures.
- **`76d766f` — four documents corrected.** Truthful status (real SHAs; the five-day false "shipped"/"pre-registered" window left on the record); one vocabulary deferring to `ctx-states/v1`; delivery/consumption separated with evidence classes named; **gate 5 removed** from the session-memory continuation decision — it was already true before the experiment ran, so no result could fail it and it made the five-point gate unfalsifiable (retained for the narrower audit/checkpoint product).
- **Tests:** `python -m pytest tests/test_state_algebra.py tests/test_trust_telemetry.py tests/test_h4_oracle.py -q` (67 passed); affected sweep 344 passed / 0 failed. Full suite not re-run.
- **Scope excluded deliberately:** live `.claude/ctx/*` churn, `.review_tmp_*`, `docs/notes.md`, `docs/ctx-investor-brief.html`. A stray 0-byte `{v` file (shell-quoting accident) removed. `.claude/settings.local.json` is globally gitignored.
- **Standing constraints unchanged:** query surface FROZEN; no replication approved; no new $2 authorization; `3e1aaee` immutable; parked branch do-not-merge; parked-code review outstanding; A5 round-5 SHAs main `888324b` + parked `3f32ec3` untouched.
- **Open reviewer questions:** (a) is one code commit spanning lint + receipts + delivery acceptable, given `checkpoint.py` and one test file interlock all three, or should the test file be split? (b) `_QUALIFIER_RE` in the H-4 grader is a fixed phrase list by design (a regex that "understands" hedging is an LLM judge with extra steps) — are the listed qualifiers sufficient, and should the list be frozen in the preregistration rather than in code? (c) `min_negative_control=0.8` is a guessed threshold with no measurement behind it; it should probably be set from the calibration baseline rather than pre-committed.
- **Not done:** the offline three-adapter freshness spike, the evaluation harness beyond the oracle, E-6 itself, and the H-4 manifest instance (the schema and validator exist; no manifest has been built).

### 2026-07-30 — Claude Code (session `fb94cd9f`) — round-2 review fixes (`dcc8c14`, `0263e85`, `3667094`)
- **All five findings on `5f80e5b..065f05e` accepted and fixed.** Every one was a case of a check that looked present but could not fire.
- **P1 · H-4 grading (`0263e85`).** The prose grader was replaced, not patched. Answers must now carry a line-anchored `VERDICT: holds|stale|unknown`, graded on that token alone — polarity and clause scope become the arm's obligation to express rather than the grader's to infer. The reviewer's two examples survive as frozen adversarial tests: *"Historical observation … but X is true now"* with `holds` scores as a stale assertion, and *"It is false that X"* with `stale` does not. Missing verdict = `unparseable`, a disclosed protocol failure, gate-failing, never silently graded. Vocabulary + pattern + required fields + expected verdicts are hashed into `grader_id` (`h4-grader/v2`) and stamped in every result; results either side of a change are not comparable. Requiring the token is a protocol obligation on **all** arms equally, not a CTX affordance. The fixed qualifier list is **gone** rather than frozen — the stronger form of the instruction.
- **P1 · ledger binding (`0263e85`).** `ledger_facts` is required on `validate_manifest` and `grade_run`; `validate_shape` is the separately-named structural check. A test asserts the no-argument call raises `TypeError` so the default cannot return. An optional integrity check is not an integrity check.
- **P1 · protocol/implementation divergence (`0263e85`).** Aligned toward the code: `stale_assertion_rate` is over stale-positives only, because a still-true claim cannot be confidently asserted stale and pooling would let a bigger control set flatter the headline. The preregistration now states this and records that it previously said otherwise. Mutation test rebuilt on **three** items, changing **exactly one** `expected_verdict`, asserting the change set is a singleton.
- **P1 · injection ordering (`3667094`).** The receipt is written after the emit, inside a `try`; a `BrokenPipeError` is banked as `failed` with the emit error, not as `injected`. Renamed to what is actually measured: `measures: "emitted_to_hook_stdout"`, `emit_success_rate`, `emitted_sessions()`, `sessions_zero_recall_with_emission`. The dashboard test asserts the rendered page contains no form of "delivered". Track C's "surfaces they already consume" corrected.
- **P2 · `not_applicable` fold leak (`dcc8c14`).** `worst([NOT_APPLICABLE, CURRENT])` returned `CURRENT`, so a fact with no verifiable support could render VERIFIED once one unrelated recipe came back clean. Mixed folds now raise; `render_claim` handles it separately, since a durable constraint has no evidence to re-run and "requires revalidation" would be false in the other direction. **How it survived:** the property test folded all six states pairwise but asserted only order-independence — a property a wrong answer satisfies as easily as a right one.
- **Threshold guidance taken:** the guessed `0.8` negative-control rate is gone. Permitted control errors and unparseable answers are exact counts defaulting to **zero**; a deterministic oracle has no noise to absorb, and any allowance must be preregistered with its justification.
- **Tests:** `python -m pytest tests/ -q -m "not slow"` → **1684 passed, 35 skipped, 57 deselected, 60s**. Targeted: `tests/test_state_algebra.py tests/test_h4_oracle.py tests/test_trust_telemetry.py` → 82 passed.
- **Suite caveat for the reviewer:** a bare `pytest tests/` stalls at ~24% on this machine. Not a hang and not caused by this packet — `tests/test_codebase.py` is `slow`-marked and gated on `C:/Users/kapil/Scriptiva_SCA`, which exists here, so it walks a large external repo. Both of my first two full-suite attempts died there before I isolated it.
- **Still not done:** E-6, the offline three-adapter freshness spike, the evaluation harness past the oracle, and any H-4 manifest instance (schema + validator exist; no manifest built). No scored, paid, or calibration run executed or authorized.
- **Re-review requested on `5f80e5b..3667094`.**

### 2026-08-05 — Claude Code (session `d84e91c2`, continued) — scriptiva field report assessed; strategy verdict recorded; preflight backlog authored
- **What changed:** third field report (scriptiva: checkpoint + startup injection work, explicit recall 0.4%, secret-scanning + retention asked) assessed against the two prior reports; the resulting strategy verdict recorded above under Reviewer Notes verbatim-in-substance; `docs/preflight-backlog-2026-08.md` authored — Phases 0–5 (observability repair → E-6 expanded → shadow matcher → gated live preflight → behavioral experiment → freshness/fork control), six-field contracts, dependency spine.
- **Verification performed:** all four reviewer code citations checked against HEAD and confirmed — `hydrator.py:244` (unweighted overlap, unusable as injector), `injection_log.py:109` + `session_reader.py:677-680` (pre-coverage sessions misclassified `no_emission`), `cli/main.py:1420` (no UserPromptSubmit in `_HOOK_SETTINGS`).
- **Files touched:** `docs/preflight-backlog-2026-08.md` (new), `AGENT_COORDINATION.md` (this entry + Reviewer Notes + Current Repo State). No code changed; no tests run (docs/board only).
- **Constraint interactions declared, none relaxed:** E-6 remains the next owner thread (Phase 1 = E-6 expanded); s:eca3f61c#turn802 gates Phase-3 hook activation on explicit owner supersession; query-surface freeze intact; Phase 4 is paid ⇒ fresh reviewer approval + owner budget authorization; parked branch do-not-merge, its review still outstanding (gates PF-52); no scored/paid run authorized. Prior thread (consolidated packet awaiting Codex re-check on `5f80e5b..3667094`) unchanged.
- **Open for the owner:** ratify/edit the backlog; PF-16 rank_v1 fixture disposition; Phase-3 supersession is owner-only; Phase-4 budget when reached.
- **Next recommended action:** owner ratifies backlog → Phase 0 (PF-01/PF-02, small) → E-6 expanded (PF-11..17) as the standing next thread.

### 2026-08-07 — Claude Code (session `d84e91c2`, continued) — ratification recorded; backlog v2; Loops 1–2 executed
- **What changed:** ratification verdict + anti-slop assessment recorded under Reviewer Notes (verbatim-in-substance); backlog rewritten to v2 (`docs/preflight-backlog-2026-08.md` — all five mandatory corrections applied: receipt fold not timestamps; source_role/authority split from extraction basis; eligibility split from relevance; minimum freshness/fork before the experiment; labelled estimator not exact BPE at runtime; plus adopted amendments — scale strata, fair flat-file arm, measured-then-frozen latency, batched ratification queue, semantic fork scoping, Phase-6 drift-control boundaries designed-not-activated, multi-writer safety as external-pilot prerequisite, language ruling on provenance claims).
- **Loop 1 (`d09a879`):** `fold_emission_receipts()` replaces `emitted_sessions()`. Deterministic per-session fold (injected > failed > empty), missing receipt = unmeasured with no timestamp consulted, malformed rows counted; `classify_read_path` buckets are now with_emission / emission_empty / emission_failed / emission_unmeasured — the `no_emission` bucket is gone. Scorecard + dashboard + prose updated; delivery-vs-use wording untouched.
- **Loop 2 (`f259dd4`):** scorecard schema v2 stamps `cohort_config_sha256` + per-repo `inputs` fingerprints (checkpoints.jsonl + injections.jsonl; capture block documented NOT covered); `verify_latest()` + CLI `--check` (exit 1 on stale/missing/pre-v2); denominators measured/unmeasured/excluded partition all statuses incl. new `path_missing`; cohort config gains `external` entries preserved by `save_cohort`.
- **Population + artifact (`1ffb226`, `967e6d8`):** OntoWiz added as external unmeasured member in its own commit; artifact regenerated: 6/7 measured, **explicit_recall_rate 0.061, raw_fallback 0.454, zero-recall split 8 with-emission / 252 unmeasured / 0 proven-empty / 0 failed** — under the retired code those 252 (mostly Scriptiva's 247 pre-log sessions) would have read "handed nothing". `--check` green post-generation. Note: our own live ledger mutates with every checkpoint, so `--check` will correctly report CTX_mod stale between regenerations — that is the feature.
- **Tests:** full non-slow suite `python -m pytest tests/ -q -m "not slow"` → **1698 passed, 35 skipped, 57 deselected, 48s**; targeted: trust-telemetry 25, scorecard-selfcheck 10, scorecard 8.
- **Constraint status:** the "no cohort telemetry number may be quoted until the emission-window fix lands" constraint (s:fb94cd9f#turn2305) is discharged by Loop 1 — the numbers above are quotable. The banked "per-repo coverage window" fix decision is superseded (receipt fold instead; see ledger).
- **Open for reviewer:** re-check Loops 1–2 (`d09a879..967e6d8`); the consolidated packet re-check (`5f80e5b..3667094`) remains outstanding.
- **Next recommended action:** expanded E-6 (Loop 4) on owner's word; Loop 3 (authority provenance) timing is an owner call relative to E-6.

### 2026-08-07 — Claude Code (session `d84e91c2`, continued) — Loops 3/4a/4b built; re-review residuals all fixed; artifact corrected
- **Timeline honesty:** on the owner's "next 4 loops" authorization I built Loop 3 (`6768b74`), Loop 4a (`d2747d5`) and Loop 4b (`7d389e0`); the reviewer's changes-requested verdict on Loops 1–2 arrived mid-session AFTER those commits. Work on Loops 4c+/5/6 stopped immediately; the three commits stand disclosed for re-review rather than being rebased away. Per the mandated ordering, **PF-11 threat model is the next unit** and must validate (or amend) the already-committed authority schema — poisoning controls depend on knowing who asserted a fact, and the boundary definition now has to catch up with the schema. That inversion is on the record here, not smoothed over.
- **Loop 3 (`6768b74`):** SOURCE-ROLE stamped at parse (extractor tp/1.2); `Authority` derived from role + explicit ratification events only (`ratifications.jsonl`, append-only, last event wins; `ctxpack session ratify <fact_id>` refuses unknown ids); basis ≠ authority is a frozen adversarial test (assistant's `Decision:` marker stays agent_candidate); legacy facts = legacy_unknown; `why` annotates authority.
- **Loop 4a (`d2747d5`):** ingest redaction between normalization and extraction — type-only `[REDACTED:<type>]` (no hash8 by policy), single choke point, fail-closed (scanner crash aborts the checkpoint; nothing unscanned persists), counts in checkpoint stats, limitations documented in-module.
- **Loop 4b (`7d389e0`):** egress scan of the final serialized context; found secrets redacted type-only with the count on the receipt; scanner crash → NO memory emitted + `failed` receipt, never a healthy empty.
- **Re-review residuals (all seven):** `6cce9c6` + `62b4817` + `07882e9` — see the Reviewer Notes entry above for the per-finding mapping. Corrected cohort numbers (cite `scorecard-20260807T195126Z.json`): 7/7 measured, explicit_recall_rate 0.067, raw_fallback 0.465, zero-recall 265 = 9/0/0/256, injections 56/56, malformed 0.
- **Tests:** full non-slow suite → **1733 passed, 35 skipped, 57 deselected, 41s** (rerun after the residual fixes); targeted: trust-telemetry 28, scorecard-selfcheck 15, redaction 16, authority 11.
- **Open for the owner:** confirm `C:/Users/kapil/Documents/Onto_Wiz` as the canonical OntoWiz deployment ledger (sibling authoring-kit + worktree ledgers excluded — see cohort notes); note the OntoWiz ledger records 2 explicit-recall sessions, which post-dates the 07-25 field report's "0 recall calls" claim — worth reconciling in the field-report memory.
- **Open for the reviewer:** re-review of the corrected Loops 1–2 range plus the disclosed Loops 3/4a/4b (`d09a879..07882e9`).
- **Next:** PF-11 threat model (next unit, per mandated ordering) on the owner's word; then remaining E-6 units; Loops 5–6 stay held.

### 2026-08-08 — Claude Code (session `d84e91c2`, continued) — PF-11 threat model drafted (design-only; NO code changed)
- **What changed:** `docs/preflight-threat-model-pf11.md` — the memory-boundary threat model the reviewer mandated. One file, no code, per the design-only instruction; all seven 2026-08-08 findings are named threats (TM-1..TM-7) with 14 concrete adversarial acceptance cases (TC-1..TC-14) that will become the PF-17 security suite.
- **Adversary model as instructed:** primary actor is the shell-capable resident agent (prompt-injected ≡ malicious), plus poisoned content and other local processes. Three rulings the reviewer should weigh:
  1. **The local CLI is not a human** — `USER_RATIFIED` is renamed `LOCAL_RATIFIED` in the design (elevated-local, never rendered as human approval); genuine human ratification requires a trusted channel that does not exist yet, stated as an explicit non-capability.
  2. **Uncertain journal ⇒ degraded authority** — any malformed row in `ratifications.jsonl` fail-closes ratification-derived elevation.
  3. **TM-11 (new, self-found): transcript tampering** — a shell-capable agent can forge "user" turns in the transcript file itself, so `USER_STATED` honestly means *user-per-transcript* (explicit trust assumption TA-1); this bounds ALL local authority claims and is why LOCAL_RATIFIED must not masquerade either.
- **Loop 3/4a/4b judged against the model** (§5): 4a/4b validated with amendments (scanner corpus TM-1; error-text TM-7); Loop 3 validated in structure with two amendments (LOCAL_RATIFIED rename TM-2; role-evidence set replacing first-wins role TM-4); ratification reader requires the TM-3 degradation.
- **Normative secret corpus** (§6) covers the reviewer's exact bypasses (prefixed env-var assignments, `github_pat_`, quoted values with whitespace) plus GitLab/Azure/GCP/npm/connection-string classes; limitations stay disclosed.
- **Tests run:** none — no code changed; the acceptance cases are deliberately unimplemented until the model is approved.
- **Open for the reviewer:** approve/amend PF-11 — especially the three rulings above and the §7 fix ordering (restates the mandated sequence).
- **Open for the owner:** confirm `Documents/Onto_Wiz` canonical (still provisional); the LOCAL_RATIFIED rename touches the CLI surface you use — objection window is now.
- **Next:** on PF-11 approval — TM-1..4 P1 fixes, then TM-5..7 P2s, then remaining E-6 units (retention, PF-16/16b, PF-17 absorbing TC-1..14), then E-6 re-review. Loops 5–6 held. No live hook, paid run, or parked merge.

### 2026-08-08 — Claude Code (session `d84e91c2`, continued) — PF-11 v2: all four mandatory amendments applied (design-only; NO code changed)
- **What changed:** `docs/preflight-threat-model-pf11.md` revised to v2 with ONLY the four amendments, per instruction.
  - **A1:** authority is now four separate axes (source provenance / local intent marker / owner approval / tool evidence-freshness), not a total order. LOCAL_RATIFIED = local intent marker, explicitly no stronger security evidence than AGENT_CANDIDATE; the owner-approval axis is UNSATISFIABLE in v1 and gates must say so rather than accept a proxy (TC-5 rewritten). TOOL_OBSERVED stays evidence-not-authority.
  - **A2:** new B6 control-plane boundary + TM-12. Advisory mode (now) protects against poisoned content and ordinary drift assuming intact CTX code/config; Enforced mode (later, out of scope) = reference monitor + policy store + owner channel outside the agent-writable workspace. Claim discipline: surface/flag/audit/degrade — never guarantee/prevent/block (TC-15 makes it lintable).
  - **A3:** TM-8 corrected on the record — the v1 "fenced-block exclusion, validated" claim was false; I confirmed the reviewer's repro against HEAD (`_clean_multiline`/`_sentences` have no fence awareness; fence logic exists only in `_extract_incidents`). Fence-aware extraction for ALL extractors is now a named planned fix; TC-14 carries the reviewer's exact fenced-`Decision:` repro for both user and assistant short messages.
  - **A4:** TM-13 (direct ledger/gist tampering + valid rollback/replay — documented as UNDETECTABLE in advisory mode; no doc may claim otherwise), TM-14 (diagnostic leakage via stderr/temp/tracebacks — error-code rule extended), TM-15 (PF-15 deletion attacks: realpath containment, junctions never followed, plan-hash re-validation at apply, TOCTOU re-check at unlink), TM-16 (ratification-journal DoS: fail-closed availability loss ACCEPTED and surfaced; repair = append fresh events). Git-commit identity removed from human-channel candidates. Acceptance cases now TC-1..TC-20; §5 validation table gains the parser-fence row and the global B6 bound.
- **Tests run:** none — design-only; one read-only grep to confirm the A3 repro grounds truthfully.
- **Open for the reviewer:** short re-review of PF-11 v2.
- **Open for the owner:** Onto_Wiz canonical confirmation (cohort snapshot stays provisional); LOCAL_RATIFIED-without-elevation now also means `ctxpack session ratify` is a bookkeeping surface, not a promotion lever — objection window before TM-2 implements.
- **Next:** on approval, TM-1..4 as separate review units (fence-aware extraction joins the TM-1 unit), then TM-5..7, then PF-15/16/16b/17, then E-6 re-review.

### 2026-08-09 — Claude Code (session `d84e91c2`, continued) — PF-11 approved; Onto_Wiz governance done; P1 batch implemented (5 units); re-review requested
- **PF-11 v2.1 approved** (threat model only). Owner confirmed Onto_Wiz canonical in-session ("it's the repo where ctx is being used") → recorded in cohort notes (`85302ea`), artifact regenerated under the changed config hash (`e46984e`, `scorecard-20260809T183423Z.json`, prior artifacts immutable as provisional snapshots), field report reconciled as historically accurate at its observation date.
- **TM-1 (`870387e`)** — scanner corpus per PF-11 §6: segment-based name matching (splits `_-.` + camelCase; `oauth` never fires on the `auth` substring; bare `key` needs a qualifying sibling), quoted values with whitespace, same-line separator (a benign `config:` line must not swallow the next line's assignment — found while testing, pinned), `github_pat_`/`glpat-`/`AIza` classes. TC-1 end-to-end: the reviewer's four exact bypasses planted in user/assistant/tool_result/tool_use reach zero persisted bytes.
- **TM-8 (`6953a44`)** — `_drop_fenced` after incident extraction in user, assistant AND sidechain paths; the exfiltrate repro is pinned in both roles; fenced literals excluded; unterminated fence drops the remainder fail-closed; incident fence rule pinned unchanged.
- **TM-2 (`b2b5b30`)** — `user_ratified` removed from the enum entirely; `derive_authority` loses the `ratified` parameter (folding it in rebuilt the forbidden ordering); every `why` match carries the axes separately: `authority` (provenance), `local_ratification` (bookkeeping), `owner_approval` (always `unavailable`).
- **TM-3/TM-16 (`af11ee4`)** — strict row validation incl. schema; any malformed row empties the state and marks every match `local_ratification: degraded` + a top-level `ratification_journal` block; CLI refuses append-on-degraded and `--rotate-quarantine` performs the recovery epoch (rotating a healthy journal refused); quarantined count surfaced.
- **TM-4 (`600aef9`)** — SOURCE-ROLES evidence set (`role@turn`, first turn per role); `why` reports the whole set, distinct roles render as `multiple` never one role; SOURCE-ROLE remains the first-assertion provenance record.
- **Tests:** each unit shipped its TCs in the same commit; full non-slow suite **1752 passed / 35 skipped / 57 deselected**. One failure in the sweep — `test_count_tokens_faster_than_materialization` — is a pre-existing wall-clock performance comparison (July, `a94211a`), passes in isolation, unrelated files; disclosed, not fixed here.
- **Open for the reviewer:** P1-batch re-review of `85302ea..600aef9` (7 commits incl. governance). TM-5..7 not started, per the gate.
- **Next:** on P1-batch approval — TM-5 schema-routed receipts, TM-6 scoped-why authority parity, TM-7+TM-14 error codes; then PF-15/16/16b/17; then E-6 re-review. Frozen: Loops 5–6, live hook, paid runs, parked merge.

### 2026-08-09 — Claude Code (session `d84e91c2`, continued) — harness parity with the owner's other repos (`7ecf5fb`)
- **Owner directive:** follow the SAME harness strategy as Scriptiva_SCA/setu/KP_SDLC — no invented checks. Audit found CTX_mod was the outlier: it ships `ctxpack codebase harness` and instructed the Scriptiva team to run it, but never ran it on itself (no `.claude/rules/`, no anti-slop index, no codebase map).
- **Adopted (same files, same doctrine):** generator run on this repo (anti-slop symbol index, commit-conventions, quality-check hook, codebase-map — privacy-scanned, no personal paths); `test-requirements.md` replaced with hand-authored doctrine per the setu pattern ("not regenerated"), expressing this repo's EXISTING invariants (byte determinism, negation preservation, immutable results, can-fail guards, red-on-parent, pins/forward-guards self-identify, paste-output-never-memory, flaky = disclosed); `conservation-gates.md` transplanted from the market_zero/setu doctrine onto native primitives (bar = preregs/graders/results/reviewer gate; spine = deterministic write path; two lanes = deterministic vs authorized-paid; DoD incl. independent review).
- **Honest floor/ceiling accounting (setu principle 4):** CTX_mod is mostly ceiling — no CI, no CODEOWNERS, no protected-surface enforcement; gates run when an agent runs them. Flagged as owner decisions in conservation-gates.md, NOT built.
- **Evidence check that motivated this:** the P1 batch's 23 new tests re-run against the pre-batch commit — 21 red (fix-detecting), 2 designed passes (incident-fence regression pin; false-positive forward guard). Standing gates green: claims gate OK (20 warn-only), coordination reporter clean, determinism + negation gates in the 1752-passed suite.
- **Owner wiring left to you (CLAUDE.md is do-not-touch):** add `@.claude/codebase-map.md` to CLAUDE.md if you want the map auto-loaded; CI/branch-protection floor items when ready.

### 2026-08-09 — Claude Code (session `95edc6ae`) — re-review remediation: all four P1 blockers + both P2 residuals fixed; six one-mechanism commits `ae3c780..b5a6d2c`; re-re-review requested
- **TM-2 (`ae3c780`)** — ratification attributes `local-cli`; CLI help says "local ratification event — bookkeeping by an unauthenticated local actor, never owner approval"; module docstring states `by` is a path label, never an actor claim; stale `USER_RATIFIED` backlog language updated in `docs/preflight-backlog-2026-08.md` (PF-03 section + adversarial-adoption bullet). Tests: help text (whitespace-normalized against argparse wrapping), recorded row, CLI-emitted JSON.
- **TM-3 (`47b3072`)** — `_row_is_valid` now requires ISO-8601 `ts` (via `fromisoformat`) and a non-empty string `by`; missing/garbage/wrong-typed variants each degrade the journal; a complete-row control pins that the gate can distinguish.
- **TM-8 (`eee6dda`)** — `_FenceTracker` shared by `_drop_fenced` AND `_extract_incidents`: opens on 3+ backticks or tildes, remembers marker char + opening length, closes only on the same char, ≥ opening length, with no info string; a backtick opener whose info string contains a backtick is inline code, not a fence; unterminated fences stay fail-closed. Pinned leaks: 4-backtick fence w/ inner ``` example, tilde fence, ```python-as-close, unterminated tilde, incident-extractor twin; forward guard: tildes cannot close a backtick fence.
- **TM-1 (`5e87547`)** — scanner catches uppercase env-style `*_KEY` (fullmatch; lowercase `sort_key` bound retained per TC-3). The preregistered matrix then found TWO MORE ingest gaps beyond the reviewer's: (a) a benign-name assignment match consumed a value span containing a real secret assignment (`auth failed for azure-accountkey: AccountKey=...` — value now rescanned recursively); (b) a secret-like name with a nested quoted assignment (`...: X_SECRET_KEY="Zq8... pT7"`, and the spaced `PROD_DB_PASSWORD: "..."` form) left the quoted payload unredacted — the unquoted value alternative now takes a quoted tail, spaced only when the run ends in the separator itself (prose quotes pinned untouched). TC-1 now = full §6 corpus (33 entries: all five `gh?_` prefixes, `github_pat_`, `glpat-`, `xox`, `sk-`, JWT, PEM + truncated PEM, Bearer, URL creds, `postgres://` + `mongodb+srv://`, `AccountKey=`, `AIza`, npm `_authToken`, every `*_(KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIALS?)` class incl. quoted-whitespace values) × all four content positions (user / assistant / tool_result / tool_use) × BOTH boundaries — zero secret bytes in any ledger file after checkpoint AND in the session-start emission; every entry planted in the shape that BANKS for its position so a pass cannot be vacuous.
- **TM-4 (`fa031c0`)** — SOURCE-ROLES keeps EVERY unique `role@turn` occurrence in transcript order (second same-role assertion no longer dropped); dedup only on the exact occurrence; SOURCE-ROLE unchanged as first-assertion provenance.
- **Provenance (`b5a6d2c`)** — `EXTRACTOR_VERSION` → `tp/1.3`, `REDACTION_VERSION` → `redact/v2`; both stamped into every `checkpoints.jsonl` receipt (`extractor`, `redaction` keys).
- **Red-on-parent (worktree at each fix's parent, that commit's test files copied in):** `ae3c780` 2 failed; `47b3072` 1 failed; `eee6dda` 5 failed + 1 designed pass; `5e87547` 7 failed + 1 designed pass; `fa031c0` 1 failed; `b5a6d2c` 2 failed — **18 red total; both designed passes self-identify as forward guards in their docstrings.**
- **Tests run:** full non-slow `python -m pytest tests/ -q -m "not slow"` → **1772 passed / 35 skipped / 57 deselected in 30.8s** (the previously-disclosed wall-clock flaky passed this run); claims gate OK (20 warn-only), capability registry OK, `git diff --check d19bea7..HEAD` clean. `scorecard --check` reports STALE from live mid-session ledger churn — deliberately NOT regenerated: the approved dated artifact `scorecard-20260809T183423Z.json` / `scorecard-latest.json` byte-identity from the re-review must not be disturbed by an unreviewed regeneration.
- **Risks / notes for the reviewer:** (a) the `_ASSIGNMENT` quoted-tail widening is bounded by the ends-in-separator rule + a prose-quote pin, but it is the one place this batch widens a match; (b) the fence tracker is CommonMark-faithful, so a line like ``` `x` ``` no longer opens a fence — following prose extracts (correct per spec; extraction ≠ authority); (c) SOURCE-ROLES is now unbounded per fact within a session (deduped occurrences) — flagging the growth property explicitly.
- **Open for the reviewer:** re-re-review of **`ae3c780..b5a6d2c`** (6 commits). TM-5..7 still not started per the gate; Loops 5–6, live hooks, paid runs, parked merges stay frozen.

### 2026-08-09 — Claude Code (session `95edc6ae`) — journal-integrity follow-up (`14ea469`) + non-blocking corpus fix (`44595be`); scoped re-review requested
- **`14ea469` (the required single journal commit)** — all four acceptance cases, status per case in the reviewer entry above: binary read + per-row STRICT UTF-8 decode (an invalid byte in `note`/`by` now degrades: empty state, `malformed_rows` counted); `FileNotFoundError` is the only healthy absence — every other `OSError` degrades with stable non-sensitive code `journal_read_failed` (surfaced in the CLI degraded message, rotation-failure path now reports instead of raising, and in `why`'s `ratification_journal` block); `record_ratification()` validates `by` before writing and encodes the row before opening the file (binary append, no platform newline translation, no half-written row — `ensure_ascii` means the writer can never produce bytes the strict reader rejects).
- **`44595be` (invited non-blocking)** — standalone `APP_SECRET` corpus entry; the previous handoff's "33 entries" overstated a 32-entry corpus, now truly 33. Regression pin, self-identified in the comment.
- **Red-on-parent (worktree at `e11dd96`, commit's test file copied in):** 3 failed / 1 designed pass (the genuine-absence regression pin, self-identified in its docstring); the 5th match in the sweep output is a pre-existing unrelated `test_trust_telemetry.py` test.
- **Tests run:** full non-slow `python -m pytest tests/ -q -m "not slow"` → **1776 passed / 35 skipped / 57 deselected in 38.2s**; focused ratification/consumer sweep 95 passed; redaction file 35 passed.
- **Process adoption:** reviewer-note format switched to Finding / Required acceptance cases / Fix SHA / Status per acceptance case (header blurb updated); acceptance cases now relayed verbatim — the compressed-relay defect that caused this follow-up is recorded in the reviewer entry.
- **Accepted forward constraints:** SOURCE-ROLES raw occurrence list is never emitted into prompt context and a scale test gates live injection; PF-17 adds the whole raw corpus to an old-ledger/gist egress fixture directly.
- **Open for the reviewer:** scoped re-review of **`14ea469`** (+ optional glance at `44595be`). TM-5..7, Loops 5–6, live hooks, paid runs, parked merges stay frozen.

### 2026-08-10 — Claude Code (session `95edc6ae`) — TM-5/TM-6/TM-7+TM-14 implemented per the unfreeze; range `31fc0ad..644731f`; review requested
- **`31fc0ad`** — reviewer's non-blocking wording correction applied to the writer comment (interrupted filesystem writes can still truncate; the strict reader detects and degrades). Comment-only.
- **TM-5 (`ca3fa13`)** — emission receipts route on the row's DECLARED `schema`, never id length: a `ctx-injections/v2` row folds under `by_full` even with an exactly-8-char session id (TC-10 — on the parent it fell into the legacy prefix pool where a colliding session made it unmeasured); a row declaring an unknown schema (`ctx-injections/v9`) is malformed — counted, folded nowhere (TC-11); schemaless v1 rows keep the prefix pool + unambiguity join (regression pin). The schema route lives inside `_receipt_session_outcome` — the ONE valid-receipt definition shared with `injection_stats`, so "attempted" and "folded" still cannot disagree.
- **TM-6 (`174555d`)** — ONE trust-annotation path for every `why` variant: `session_why` (CLI `--session`, MCP `session` arg) now runs the same `_annotate_authority` + shared `_ratification_journal_block` as the cross-session default. TC-12 pins identical `authority` / `local_ratification` / `owner_approval` across scopes AND identical journal-degradation surfacing. Doc-only callers without a ledger_dir still stamp the authority axis; ratification reads as an absent journal (real zero).
- **TM-7+TM-14 (`644731f`)** — the injection receipt journal and hook stderr never receive free exception text: `record_injection` persists only stable codes (`startup_read_failed` / `egress_scan_failed` / `emit_failed`; anything else is COERCED to `unknown_error` — a structural guard, not a convention) plus the exception class name (identifier-checked); all three session-start failure sites converted; the checkpoint-hook stderr line prints `checkpoint_failed (<ExceptionClass>)` only. TC-13: a crash whose message embeds a corpus secret leaves zero secret bytes in the receipt journal. TC-17: a checkpoint-hook failure with a secret-bearing message leaves zero secret bytes on stderr or in any persisted file (this hook path creates no temp files — nothing to sweep). Pre-existing free-text assertions updated to the code contract (three tests).
- **Red-on-parent (worktree at each fix's parent, that commit's test files copied in):** `ca3fa13` 2 failed + 1 designed pass (legacy-prefix pin, self-identified); `174555d` 1 failed; `644731f` 6 failed — **9 red total, 1 designed pass.**
- **Tests run:** full non-slow `python -m pytest tests/ -q -m "not slow"` → **1783 passed / 35 skipped / 57 deselected in 36.4s**; claims gate OK (20 warn-only); capability registry OK; `git diff --check efb2d18..HEAD` clean.
- **Queued owner decision (from the reviewer's non-blocking note):** `IncrementalPacker` (`ctxpack/core/incremental.py`) mtime fast-path can hide a content change when timestamps are equal; zero callers today. Decide **harden or retire** before any wiring into AMBIENT/live injection. Also pre-queued from the same verdict: the unrelated IncrementalPacker timing-test flake the reviewer observed lives in the same component.
- **Open for the reviewer:** review of **`31fc0ad..644731f`** (4 commits: 1 comment-only + TM-5 + TM-6 + TM-7/14). Next per the mandated order once approved: PF-15 (TM-15-bound), PF-16/16b, PF-17 cross-boundary (incl. the raw-corpus egress fixture accepted 2026-08-09). Loops 5–6, live hooks, paid runs, parked merges stay frozen.

---

## Reviewer Notes

_Reviewer (Codex) appends findings here: `### <date> — Codex`. Format
(reviewer-mandated 2026-08-09): **Finding / Required acceptance cases /
Fix SHA / Status per acceptance case** — a finding is not "fixed" until
EVERY acceptance case is linked to a test. Relays must carry the
acceptance cases verbatim, never a compressed summary (see the
2026-08-09 relay-process defect). Do not edit an implementer's
Handoff._

### 2026-08-10 — Reviewer (scoped re-review of `14ea469` + `44595be`; relayed verbatim-in-substance, acceptance-case format) — APPROVED
- **Finding:** prior journal-integrity blocker closed; no new blocking findings.
- **Required acceptance cases:** strict UTF-8; only FileNotFoundError means absence; genuine absence remains healthy; invalid `by` rejected before writing.
- **Fix SHA:** `14ea469`.
- **Status per acceptance case:** (a) PASS — invalid UTF-8 degrades and empties state. (b) PASS — other read failures produce `journal_read_failed`. (c) PASS — genuine absence remains a real zero. (d) PASS — writer validates `by` and serializes before opening.
- **Optional SHA:** `44595be` accepted; corpus now contains 33 cases.
- **Verification reproduced:** authority tests 24 passed; consumer tests 84 passed; redaction tests 35 passed; range `git diff --check` clean; full sweep 1,775 passed with one unrelated IncrementalPacker timing failure that passes in isolation (zero-caller legacy component, last modified in May, outside this range).
- **Non-blocking corrections:** (1) wording — "no half-written row" → "validation and encoding failures cannot partially append a row; an interrupted filesystem write can still truncate, which the strict reader detects and degrades". **Status: fixed in `31fc0ad`** (code comment; board correction recorded here). (2) **Queue the IncrementalPacker mtime fast-path issue** — equal timestamps can hide a content change; zero callers today; decide harden-or-retire BEFORE wiring into AMBIENT. **Status: QUEUED as an owner decision** (recorded in the 2026-08-10 handoff; no code change in this batch).
- **Standing at verdict:** TM-5..7 unfrozen (mechanism-per-commit order mandated); Loops 5–6, live hooks, paid runs, parked merges remain frozen. No repository writes attempted during review.

### 2026-08-09 — Reviewer (re-re-review of `ae3c780..b5a6d2c`; relayed verbatim-in-substance, acceptance-case format) — NARROW CHANGES; five of six commits APPROVED
- **Approved:** `ae3c780` (honest local-cli attribution), `eee6dda` (robust shared fence tracking), `5e87547` (scanner + corpus expansion), `fa031c0` (all role@turn occurrences), `b5a6d2c` (version bumps + receipt stamps). Verification reproduced: focused 66 passed; full non-slow 1772/35/57; claims gate OK (20 warn-only); capability registry OK; `git diff --check` clean.
- **Finding (blocking, `47b3072`): journal integrity incomplete** — ts/by validation is correct but two prior-verdict requirements were unmet: (1) `ratification.py:130` used `errors="replace"` — an invalid UTF-8 byte in an otherwise valid row became U+FFFD and the row still conferred ratify (probe: `state={'aaa…':'ratify'}, degraded=False`); (2) `ratification.py:146` treated every OSError as healthy absence (mocked PermissionError → `state={}, malformed_rows=0, degraded=False`).
- **Required acceptance cases:** (a) strict UTF-8 decode — invalid bytes ⇒ empty state + `degraded=True`; (b) only FileNotFoundError = healthy absence; permission/directory/other read failures degrade with a stable non-sensitive error code; (c) genuine-absence control stays a real zero; (d) `by` validated inside `record_ratification()` before writing so the public API cannot create a row its reader rejects. Pin four tests: invalid byte / permission-read failure / genuine absence / invalid writer `by`.
- **Fix SHA:** `14ea469` (single follow-up commit as instructed).
- **Status per acceptance case:** (a) FIXED — binary read + per-row strict decode; test `test_invalid_utf8_byte_in_a_valid_row_degrades_the_journal` (red on parent). (b) FIXED — `FileNotFoundError` alone is absence; all other `OSError` → `degraded=True, error="journal_read_failed"` (code surfaced in CLI message + `ratification_journal` block; rotation failure now reported, not raised); test `test_unreadable_journal_degrades_never_reads_as_absent` (red on parent). (c) PINNED — `test_genuinely_absent_journal_is_a_real_zero` (regression pin, passes on parent by design, self-identified). (d) FIXED — writer validates `by` before writing, encodes the row before opening (no half-written rows), appends binary; test `test_writer_refuses_a_by_its_reader_would_reject` (red on parent).
- **Relay-process defect (acknowledged):** the earlier board relay compressed P1-2 to "rows missing ts and by", dropping the invalid-byte and OSError criteria; the team faithfully fixed the recorded subset. Reviewer-note format changed to Finding / Required acceptance cases / Fix SHA / Status per acceptance case (header blurb updated); relays now carry acceptance cases verbatim.
- **Non-blocking notes:** (1) TC-1 corpus was 32 not 33 → intended standalone `APP_SECRET` case added in `44595be` (regression pin, self-identified) — count now truly 33. (2) SOURCE-ROLES grows linearly for hot facts — accepted: scale test gates live injection; the raw occurrence list is never emitted into prompt context (constraint banked this session). (3) PF-17 scope addition accepted: plant the entire raw corpus directly in an old-ledger/gist egress fixture rather than relying on scanner+egress composition.
- **Standing:** TM-5..7 frozen; re-review scoped to the journal-integrity commit and its tests.

### 2026-08-09 — Reviewer (P1-batch re-review of `85302ea..600aef9`; relayed by owner verbatim-in-substance) — CHANGES REQUESTED; governance/artifact commits approved
- **Approved:** governance + dated scorecard artifact (cohort sha matches, partitions reconcile, dated/latest byte-identical); `git diff --check` clean; focused suites 47 passed; full non-slow reproduced 1753/35/57; the original secret bypasses, simple triple-backtick TC-14 cases, authority-axis separation, and basic quarantine recovery all pass.
- **P1-1 — local ratification still masquerades as owner approval:** `cli/main.py:396` says "owner ratification event"; `ratification.py:43` writes `by: owner-cli`. Fix: `local-cli`/`unverified-local-cli`, remove all owner/human wording, update stale USER_RATIFIED backlog language, test CLI help + emitted JSON. **Status: fixed in `ae3c780`.**
- **P1-2 — journal validation not strict/complete:** `ratification.py:69` accepts rows missing `ts` and `by`. **Status: fixed in `47b3072`.**
- **P1-3 — fence-aware extraction bypassable:** `transcript_parser.py:298` blindly toggles on any ``` line; a valid 4-backtick fence with an inner ``` example leaked its poisoned `Decision:`; tilde fences leaked entirely. Fix: fence state remembering marker type + opening length, close only on same marker ≥ length, both backtick and tilde CommonMark fences, shared with incident extraction. **Status: fixed in `eee6dda`.**
- **P1-4 — TM-1 does not implement its normative corpus:** `redaction.py:73` lets `DATA_KEY=Zx9k2mPq8vLw4njR` through; TC-1 tested only four secrets in one position each, not every corpus entry × all four positions + emitted context as preregistered. **Status: fixed in `5e87547`.**
- **P2 — TM-4 keeps only first turn per role** (`transcript_parser.py:665`, second user occurrence dropped): preserve every unique role@turn or narrow the contract. **Status: fixed in `fa031c0` (every unique occurrence).**
- **P2 — provenance versions did not move** (`tp/1.2`, `redact/v1` unchanged; redaction version not stamped into artifacts). **Status: fixed in `b5a6d2c`.**
- **Standing:** TM-5..7, Loops 5–6, live hooks, paid runs, parked merges stay frozen; fixes as mechanism-scoped commits, relay the new range; no replication run needed.

### 2026-08-08 — Reviewer (PF-11 v2 `4d0c3b0` review; read-only) — NARROW CHANGES; four contradictory capability statements
- **Passes:** B6 + advisory/enforced modes, TM-8 correction, TM-13..16 coverage, git-identity removal, LOCAL_RATIFIED as bookkeeping only.
- **(1)** TM-2 control still said "elevated-local"/`USER_STATED` as owner authority — contradicts B2 + TC-5; delete. **(2)** TM-4 still derived authority from the "strongest evidenced role" — preserve occurrences WITHOUT collapsing into authority; owner approval stays unavailable. **(3)** TC-16 claimed hand-edited `.ctx` detected on read — false, `load_session()` compares nothing; mark undetectable today or name a future integrity-verification unit. **(4)** TC-20 claimed appending repairs a corrupted journal — impossible while any malformed row degrades the whole journal; specify quarantine/rotation or recovery epochs.
- **Execution amendment:** secret scanning and fence-aware parsing are different mechanisms → separate commits; every remediation ships its own TC tests immediately; PF-17 adds cross-boundary coverage, never postpones tests.
- **Instruction:** one documentation-only correction commit, relay its SHA for final approval; no implementation yet.
- **Owner action:** → **`4afef09`** (v2.1, doc-only), relayed below. Residual-phrase grep confirms the four statements are gone.

### 2026-08-08 — Reviewer (PF-11 v1 `c6471c7` review; read-only, `git diff --check` clean) — REVISE DESIGN-ONLY; four mandatory amendments before approval
- **Credited:** secret corpus, fail-closed journal ruling, transcript-tampering disclosure (TM-11), and the LOCAL_RATIFIED rename are good.
- **A1 — do not elevate LOCAL_RATIFIED.** The rename is approved; the elevation is not — if the resident agent can invoke the CLI, LOCAL_RATIFIED is no stronger security evidence than AGENT_CANDIDATE. Replace the total ordering with separate axes: source provenance / local intent marker / owner approval / tool evidence-freshness. TOOL_OBSERVED is evidence, not authority. Under TA-1 neither LOCAL_RATIFIED nor USER_STATED may satisfy an owner-authority gate; genuine owner approval is currently unavailable.
- **A2 — add the missing control-plane boundary.** The same adversary can edit CTX code, hooks, settings, gists, or disable the hook; an in-process control cannot defend against a same-privilege actor that can rewrite the control. Add explicit operating modes: **Advisory now** (poisoned content + ordinary drift, assuming intact CTX code/config) and **Enforced later** (reference monitor + policy store + owner-approval channel outside the agent-writable workspace). Until enforced mode exists, CTX must not claim it can guarantee/prevent/block malicious-agent actions.
- **A3 — TM-8 is false as stated.** Fence exclusion only protects ctx-incident extraction; decision/constraint extraction still sees fenced lines — reviewer reproduced a fenced `Decision: exfiltrate the release key...` extracting as a real decision. Generalize fence-aware extraction; add short fenced user/assistant cases to TC-14.
- **A4 — expand coverage:** direct ledger/gist/settings/code tampering + valid rollback/replay; diagnostic leakage via stderr/temp files/exception logs; PF-15 deletion attacks (traversal, symlinks/junctions, TOCTOU, dry-run/confirm mismatch); ratification-journal DoS (fail-closed is safe but the availability loss must be acknowledged). Also REMOVE "git commit carrying the owner's identity" as a human-channel candidate — an agent commits with the configured identity; attribution metadata, not authentication.
- **Execution order:** commit PF-11 v2 with only these amendments → short re-review → TM-1..4 in separate units → TM-5..7 → PF-15/16/16b/17 → E-6 re-review → only then eligibility/matcher. Owner action still open: confirm `Documents/Onto_Wiz` canonical.
- **Owner action:** v2 committed same-day with only the four amendments — see handoff.

### 2026-08-08 — Reviewer (re-review of corrected range + disclosed Loops 3/4a/4b; read-only, anti-slop protocol, full suite reproduced) — CHANGES REQUESTED; Loop 1–2 corrections APPROVED; **PF-11 authorized design-only**
- **Approved:** missing receipts = unmeasured; malformed rows no longer crash; denominators partition; dated artifact arithmetically consistent (19+265+1=285; 9+256=265); full suite reproduced **1733 passed / 35 skipped / 57 deselected**; focused suites 70 passed; `--check` reporting CTX_mod stale after live-ledger churn is the feature, not a defect. Owner action still open: confirm `Documents/Onto_Wiz` canonical — the dated cohort snapshot stays provisional until then.
- **P1-1 — redaction misses common production secrets** (`redaction.py` assignment matcher): `AWS_SECRET_ACCESS_KEY=...`, `AWS_SESSION_TOKEN=...`, `github_pat_...`, `DATABASE_PASSWORD="correct horse battery staple"` all passed unchanged in HEAD probes — key matcher only sees standalone names, quoted values cannot contain whitespace; ingest and egress share the bypass. PF-11 must define a representative secret corpus; then amend scanner + end-to-end leakage tests.
- **P1-2 — USER_RATIFIED is not authenticated as a user action**: any process that can invoke the CLI can mint the event (`owner-cli` is a label, not evidence); an agent can promote its own candidate. PF-11 must define the trusted approval boundary; until then rename to local/unverified-actor ratification — honest explicit trust assumption if human attribution is claimed.
- **P1-3 — ratification corruption fails open**: malformed rows silently skipped, so a truncated rejection leaves an earlier ratification active. Validate schema/hex/complete rows, surface malformed counts, DEGRADE ratification authority when journal integrity is uncertain.
- **P1-4 — one SOURCE-ROLE cannot represent multiple assertions**: first-wins dedup freezes the first writer's role; record role-evidence occurrences instead, never an irreversible collapse.
- **P2-5 — v2 receipt routing uses id LENGTH not schema**: an exactly-8-char v2 id becomes legacy; route on declared schema, unknown schema = malformed; add the exact collision regression.
- **P2-6 — scoped `why` loses authority annotation**: cross-session annotates, `--session` does not — CLI/MCP return different trust information by scope.
- **P2-7 — failure telemetry can persist sensitive exception text** (`record_injection` error field unscanned): prefer stable error codes + exception classes at a security boundary.
- **Instruction:** proceed with **PF-11 as a design-only threat model incorporating every finding**, modeling an agent that can run repository commands (not merely accidental corruption), with concrete adversarial acceptance cases for authority escalation, journal tampering and secret leakage. After PF-11 review: fix authority+scanner P1s → receipt/scoped-why P2s → remaining E-6 units + security suite → E-6 re-review → only then eligibility/matcher. No live hook, paid run, parked merge, or Loops 5–6.
- **Owner action:** PF-11 drafted same-day — `docs/preflight-threat-model-pf11.md` (see handoff).

### 2026-08-07 — Reviewer (re-review of Loops 1–2, `d09a879..967e6d8`; relayed by owner verbatim-in-substance; read-only at `921fd59`+) — CHANGES REQUESTED; core design accepted, artifact invalidated
- **P1-1 — OntoWiz misclassified external/unmeasured.** Its ledger IS local: `C:\Users\kapil\Documents\Onto_Wiz` (7 sessions, 71 checkpoints, 4 injection receipts; 2 explicit-recall / 5 zero-recall / 1 with-emission / 4 unmeasured), plus `OntoWiz_Authoring_Kit_Claude` and worktree `Onto_Wiz_wt_F0.10`. `1ffb226`/`967e6d8` use the wrong population; the 6.1%/45.4%/8-252/52-52 numbers are NOT approved. Identify the canonical ledger (likely Onto_Wiz — owner confirms), remove the false external entry, avoid double-counting worktrees, regenerate. → **FIXED `62b4817` + `07882e9`** (owner confirmation flagged in cohort notes).
- **P1-2 — non-object JSON rows crash the receipt fold** (`injection_log.py` appends any `json.loads` result; `[]`/`"x"`/`null`/`42` reproduce AttributeError). Fix: dict rows only, everything else malformed; invalid UTF-8 handled not crashed; ONE shared valid-receipt definition for `injection_stats` and the fold; malformed total surfaced in the scorecard. → **FIXED `6cce9c6`**.
- **P2-3 — "per-session" was an 8-char prefix** (collision attributes one receipt to two sessions; reproduced). Fix: full ids in a new receipt schema; legacy prefixes join only when unambiguous. → **FIXED `6cce9c6`** (`ctx-injections/v2`).
- **P2-4 — `--check` is input-freshness, not self-verification** — it proves selected source files unchanged, not that report numbers are honest; capture unfingerprinted. Rename the guarantee. → **FIXED `6cce9c6`** (message + docstring + backlog claim narrowed; citations must reference the dated immutable artifact).
- **P2-5 — fail-closed validation missing** (missing≡unreadable conflated; wrong-shaped JSON can crash `verify_latest`; duplicate/path-aliased repos double-count). → **FIXED `6cce9c6`** (present/absent/unreadable states, strict cohort schema, canonical-path uniqueness incl. Windows case, unique external ids, controlled nonzero failures).
- **P2-6 — committed artifact exposes absolute personal paths and overclaimed "committed" inputs.** → sentence **FIXED `6cce9c6`** (dashboard/md no longer claim git tracking); path-aliasing **queued into E-6 as PF-16b** per the reviewer's "enter E-6 remediation".
- **P3-7 — stale status text** (backlog "authorized and executing"; "247 pre-log" should be 243 emission-unmeasured of Scriptiva's 247 total). → **FIXED** (backlog v2.1; the handoff misstatement is corrected here, not rewritten).
- **Mandated ordering:** fix residuals + regenerate → re-review corrected range → **PF-11 threat model only** → PF-03 authority (the threat model must define the poisoning/authority boundary before the authority schema is committed) → remaining E-6 units. No live hook, paid run, or parked merge.

### 2026-08-07 — Reviewer (ratification of `921fd59`; relayed by owner verbatim-in-substance; reviewer read-only, no tree changes, no tests rerun) — DIRECTION APPROVED; backlog changes requested; **Loops 1–2 authorized**
- **Verdict:** approve the direction; ratify `921fd59` with amendments. Start Phase 0 now. Do NOT authorize the live hook, the paid experiment, or the parked-branch merge. Product: `prompt → secure facts → authority/freshness policy → deterministic match → fork override → bounded packet → outgoing scan → emission → auditable receipt`.
- **Five mandatory backlog corrections:** (1) PF-01's first-timestamp approach insufficient — replace `emitted_sessions()` with a deterministic per-session receipt fold (any injected → injected; else failed → failed; else empty); a missing receipt stays unmeasured regardless of timestamps; backfilled checkpoint timestamps are not session-start times. (2) Extraction basis ≠ authority — `marker_stated` (`factid.py:31`) only describes extraction; add separate `source_role` + `authority`; legacy facts default unknown/candidate. (3) Split eligibility from relevance — hard eligibility ships before/independent of the matcher. (4) Move minimum freshness/fork controls before the behavioral experiment or drop those endpoints. (5) No exact-BPE promise at runtime — conservative labelled estimator budget live; exact tokenizer only in the eval harness.
- **Ten engineering loops defined** (1 emission telemetry, 2 self-verifying scorecards, 3 authority provenance + explicit ratification events, 4 E-6 boundary with fail-closed scanning, 5 pure eligibility policy + minimal pytest TOOL_OBSERVED verifier, 6 deterministic matcher, 7 two-row fsynced preflight receipts + class rendering, 8 cluster-split shadow evaluation, 9 narrow live canary, 10 falsification experiment with primary composite "avoidable control failure" + safety hard gates). **Authorized now: Loops 1–2 only.** Then expanded E-6.
- **Market criterion:** success = fewer confidently wrong actions, near-zero harmful automatic injections, faster authoritative-source recovery, exact provenance per injected statement, better behavioral outcomes than disciplined flat-file+grep. Loop 10 losing to flat-file ⇒ stop broad memory positioning; retain checkpoint/provenance/audit utility.

### 2026-08-07 — Reviewer (anti-slop assessment of a third-party adversarial review; relayed by owner verbatim-in-substance) — adopt its problems, correct its fixes
- **Drift question answered:** prompt-time injection alone cannot guarantee course-holding — it makes CTX an advisory control layer. "Doubt" must be a system state (low margin / stale / competing heads / unknown authority ⇒ "unknown — verify or reconcile"), never something the model is expected to notice. The potentially game-changing layer is closing the loop: PreToolUse (ask/block on deterministic violation of ratified constraints only), PostToolUse (TOOL_OBSERVED evidence + freshness invalidation), Stop/TaskCompleted (completion gate) with graduated observe/advise/ask/block — **design now, activate only after primary shadow gates pass**.
- **Third-party review triage:** scale objection valuable (add history-scale strata; keep the flat-file arm fair — equal maintenance budget, time recorded); latency objection valuable but <150ms arbitrary (measure warm/cold p50/p95/p99 + time-to-first-token in shadow, then freeze; precomputed index keyed by ledger sha, no per-prompt git subprocess); cold-start problem real but implicit merge-based ratification UNSAFE (merge may create corroborating TOOL_OBSERVED evidence for exact code/test claims, never silent USER_RATIFIED; use a batched ratification queue); fork fatigue real but git-branch scoping conceptually wrong (CTX forks are semantic supersession forks — warn on lineage/entity match with live competing heads, dedupe in-session).
- **Two omissions the third-party review missed:** autonomous-loop drift (the boundaries above) and multi-writer safety (immutable per-session event segments + deterministic derived index = external-pilot prerequisite; the one-active-owner board rule is a workaround, not a product property).
- **Language ruling:** "masterclass"/"mathematical proof"/"cryptographic provenance" language must not enter product documentation — hashes prove byte integrity, not truth or authorship.
- **Owner action:** backlog v2 applied (`docs/preflight-backlog-2026-08.md`); Loops 1–2 executed this session — see handoff.

### 2026-08-05 — Reviewer (strategy verdict on the scriptiva field report + owner's push-conversion assessment; relayed by owner verbatim-in-substance; reviewer made no repository changes — active owner on the board) — CONTINUE BUILDING, with corrections
- **Verdict:** the concept is not wasted; the three-site pattern (OntoWiz 0 recall calls, setu near-zero, scriptiva 0.4%) changes the thesis: CTX should be **an automatic, proof-carrying context control layer**, not a memory tool agents are expected to query. Voluntary pull is an audit escape hatch, not the agent product.
- **Two owner overclaims corrected:** (1) three deployments show voluntary recall is unused — they do **not** prove the sole cause is deficient model metacognition (alternatives: low need, startup-gist sufficiency, tool-selection friction, incomplete telemetry); (2) UserPromptSubmit injection is architecturally natural but **not a "cheap fix"** — it is a synchronous, every-prompt security and relevance boundary (the hook blocks model processing while it runs).
- **Mandated sequence:** fix measurement → secure the memory boundary (E-6, expanded) → evaluate prompt matching in **shadow mode** → narrowly gated live injection → verified freshness + fork control. E-6 lands and is approved before any live injection; security and injection are one initiative but never one commit or review unit.
- **Specific architecture required:** injection-eligibility policy (lifecycle/authority/freshness/security/relevance/conflict; agent-inferred facts default to candidate, never authoritative — automatic push makes memory poisoning far more dangerous than voluntary recall; authority layer is a critical E-6 addition); a **new deterministic matcher cascade** — do not reuse `hydrator.py:244` unweighted query overlap as the live injector; `ctx-preflight/v1` receipts (prompt hash never plaintext; candidates, scores, emissions, rejections, HEAD + ledger sha, matcher version); visibly structured packet classes (UNRESOLVED CONFLICT / APPLICABLE CONSTRAINT / CURRENT DECISION / UNVERIFIED PRIOR OBSERVATION / SOURCE); dedup against SessionStart context.
- **Phase-0 defect cited:** the pre-log-session emission join between `injection_log.py:109` and `session_reader.py:634` — represent instrumentation coverage intervals, not merely "a log exists"; separate measured/unmeasured/excluded denominators; stale scorecards must fail "latest" automatically. **Owner verified all four code citations against HEAD (2026-08-05): accurate**; precise form of the defect: log-exists-but-session-predates-first-row classifies as `no_emission` instead of unmeasured (`session_reader.py:677-680`).
- **E-6 scope changes:** redaction before literal extraction or any persistent write; a second outgoing scan before any context emission; memory-poisoning + authority policy; retention/deletion with dry-run + confirm; **no unsalted `[REDACTED:type:hash8]` fingerprints by default** (type-only replacement; repo-scoped keyed HMAC only if correlation is necessary, key never committed).
- **Shadow gates (candidate, frozen after unscored pilot):** ≥95% injected-fact precision; ≥80% critical-fact recall; ≤5% of no-memory-needed prompts receive context; zero authoritative rendering of stale/conflicting/untrusted; hard budget; p50/p95 latency measured not asserted. Gates fail ⇒ no live injection.
- **Evaluation:** behavioral experiment (gist-only vs gist+preflight vs flat-file+grep) at fixed total context budget; outcomes = stale assertions, fork-side actions, constraint violations, repeated failed approaches, recovery time, harmful false alarms. **Recall-call rate is not a success metric.** If preflight does not beat flat-file, retain CTX as an audit/checkpoint utility and stop broad memory claims.
- **Freeze list:** more recall/MCP tools; semantic-graph expansion; dream/consolidation; LLM memory rewriting; additional secondary trigger hooks; broad vendor integrations; generic memory / token-compression marketing. The moat is trustworthy selection, authority-aware evidence, deterministic replay and safe convergence of conflicting history — not the hook.
- **Owner action:** backlog authored per this verdict — `docs/preflight-backlog-2026-08.md` (Phases 0–5, six-field contracts, all standing constraints preserved incl. s:eca3f61c#turn802 gating any new hook surface on owner supersession). Owner ratification pending; see handoff.

### 2026-07-30 — Reviewer (round-2 on `5f80e5b..065f05e`; relayed by owner verbatim-in-substance; reviewer did not re-run tests and attempted no board write) — AMBER / changes requested, not approval
- **Credited:** commits atomic, scope clean, status reporting much more honest, adversarial tests finding real defects.
- **P1 — H-4 grading not trustworthy** (`h4_oracle.py:131`). A qualifier anywhere passes the whole answer, and exact claim substrings ignore negation: *"Historical observation … but X is true now"* passes, *"It is false that X"* can score as asserting X. Make grading polarity- and clause-aware or require structured verdicts, then freeze the grader ID/hash and adversarial cases before any run. → **FIXED `0263e85`** (structured verdicts).
- **P1 — advertised manifest checks are optional** (`h4_oracle.py:74`). `ledger_facts` defaults to `None` and `grade_run()` validates without it, bypassing fact-resolution and byte-equality. The grading entry point must require ledger-backed validation. → **FIXED `0263e85`**.
- **P1 — protocol and implementation diverge** (`PREREGISTRATION-flatfile-arm.md:143` vs `h4_oracle.py:200`). Prereg defines stale rate over all graded items; code divides by stale-positives. The "one-expectation" mutation test actually swaps two (`test_h4_oracle.py:183`). Align the metric; use ≥3 items for a genuine single-expectation mutation. → **FIXED `0263e85`**.
- **P1 — injection telemetry overclaims delivery** (`cli/main.py:1222`). Receipt written before the hook output is printed, so a failed stdout write can be recorded as injected. Record after successful emission and label it precisely as `emitted_to_hook_stdout`; agent delivery and use remain unmeasured. Remove remaining "consume/read" wording (`track-c-verified-freshness-spec.md:106`). → **FIXED `3667094`**.
- **P2 — `not_applicable` not isolated through aggregation** (`states.py:163`, spec `:375`). `worst([NOT_APPLICABLE, CURRENT])` returns `CURRENT`, potentially rendering unsupported evidence as verified. Reject mixed folds; handle separately in `render_claim()`. → **FIXED `dcc8c14`**.
- **Direct answers given:** combining the telemetry repairs in `a815b78` is acceptable (one coherent trust-reporting unit); the fixed qualifier list is not sufficient — fix polarity/clause scope, then freeze and stamp the grader version; do not retain the guessed `0.8` threshold — use an exact permitted-error count, preferably zero, or derive and preregister it from an unscored baseline.
- **Standing:** after approval, continue to E-6. No H-4 manifest/run, paid work, or Track C integration yet.

### 2026-07-30 — Reviewer (relayed by owner verbatim-in-substance; the reviewer's sandbox refused the board write) — AMBER: judgment improved, completion did not
- **Verdict:** "yes, the team is learning and self-correcting; no, this work is not yet reviewable as a finished packet." Recommendation: stop adding features, close four semantic gaps, clean scope, update the board honestly, then commit in atomic review units. No calibration or paid run.
- **Credited as fixed:** tree access unblocked and `{v` gone; false shipped/pre-registered language corrected in the new protocol; `states.py` a strong correction (three independent axes with property tests preventing delivery from being read as use); gate 5 correctly removed as unfalsifiable; `pytest-result/v1` described as historical evidence rather than current verification.
- **Four semantic gaps (all now closed, see the handoff above):** (1) "consumed" still inferred from delivery at `execution-plan-2026-07.md:326` and `dashboard.py:264`, and zero-recall described as "injection-only" without joining it to a per-session injection receipt → `a815b78`; (2) the lint arithmetic defect still pinned by `test_trust_telemetry.py:102` while `checkpoint.py:217` rendered the misleading decomposition → `a815b78`; (3) H-4 lacked an immutable oracle manifest — deterministic generation described, but not the exact stale fact, expected current state, grading rule, or completeness checks → `4ea08d4`; (4) Track C's `:46` lifecycle values disagreed with the new canonical enums and its six-state section used a third naming system → `76d766f`.
- **Also required and now done:** scope cleaned (live ledger, review temporaries, investor material and unrelated notes separated from the intended files); board updated (it still described the July 13 state and did not mention this packet); commits split into atomic units.
- **Standing prohibitions restated:** no new MCP/query tools; no vector DB, knowledge graph or LLM truth grader; no background verifier daemon; no arbitrary shell recipes; no dashboard expansion beyond truthful telemetry; no Track C startup behaviour before E-6, spike and calibration gates; no paid flat-file or four-arm run; no claim that injection delivery demonstrates use or value.
- **Status:** all four gaps closed and committed 2026-07-30. **Re-review requested** on `5f80e5b..76d766f`.

### 2026-07-13 — Codex (round-4 re-review of main `99b9697` + parked `da8d354`; relayed by owner verbatim-in-substance; no board write attempted per the read-only relay convention) — CHANGES REQUESTED; P1 approved, one P2 privacy residual
- **P1 APPROVED:** the missing-key bypass is closed correctly (`fork_cluster.py` sibling gate) and the regression test now supplies genuine sibling bytes.
- **P2 residual (privacy):** (a) HTTP masking occurs BEFORE every path detector — strings such as `https://host/upload?path=C:\tmp\work` or `https://host/x,file:///tmp/run` are entirely masked and accepted; (b) `_TOKEN_START` and the ASCII first-character class still miss `path:/etc/passwd`, `see,/workspace/run`, `{/guides/x`, and valid Unicode paths such as `/数据/private`.
- **Reviewer's suggested fix:** (1) check drive-letter, backslash-UNC, and `file://` patterns on the RAW string; (2) apply HTTP masking only for POSIX/forward-UNC detection; (3) replace the delimiter and ASCII allowlists with a generic negative token boundary plus non-whitespace path-start check; (4) pin the bypass examples while retaining the HTTPS `/home/` acceptance test.
- **Verified as passing:** correct remediation and merge topology; `da8d354` adds only the v7 zero-cost receipt (88 unique rows, eight clusters, all receipts true, padding deltas {0,1}, zero invocations, $1.0667 preflight); the original artifact and ledger remain byte-identical with their established hashes; parked source and tests match main.
- **Standing:** no replication approval, no fresh $2 authorization, no merge; the separate parked-code review remains outstanding. Verdict from direct committed-object and adversarial source inspection (reviewer did not rerun tests; the board records an active Claude owner).
- **Owner action:** the P2 residual remediated this session — see the handoff below.

### 2026-07-13 — Codex (round-3 re-review of main `8f54c25` + parked `737ceac`; relayed by owner verbatim-in-substance; no board write attempted per the read-only relay convention) — CHANGES REQUESTED; original examples fixed, two fail-closed gaps remain
- **[P1 evidence] Missing ledger key bypasses the sibling requirement.** At `fork_cluster.py:1325`, non-empty invocations are rejected only when `"invocation_ledger"` exists but is null. If the key is ABSENT entirely, validation succeeds without ledger bytes. The accepted fixture at `tests/test_fork_cluster.py:827` already exercises this bypass. Fix: reject whenever invocations is non-empty and no sibling is declared, independent of key membership; add an explicit deleted-key test.
- **[P2 privacy/policy] "Any absolute path" is not actually enforced.** The allowlist-style regexes at `fork_cluster.py:1213` still allow `/etc/passwd`, `/usr/local/bin`, `/workspace/run`, `//server/share`, and `file:///tmp/run`. Conversely, an HTTPS URL containing `/home/` is REJECTED, conflicting with the stated URL allowance; the test accepting standalone `/guides/section-1/` also conflicts with "no POSIX absolute path of any form". Fix: either enforce the strict rule consistently — excluding parsed http(s) URL spans — or narrow the documented policy; add the cases above plus an HTTPS `/home/` regression test.
- **What passed:** exact commit topology and remediation propagation are correct; normal runner wiring hashes and validates the same ledger bytes it writes; the original `C:\tmp`, alternate-drive, backslash-UNC, and `/tmp` cases are covered.
- **Standing:** the separate parked-code review also remains outstanding.
- **Owner action:** both gaps remediated this session — see the handoff below.

### 2026-07-13 — Codex (re-review of main `f540385` + parked `d81bfbd`; relayed by owner verbatim-in-substance) — CHANGES REQUESTED; supersedes the owner's "all fixed" summary
- **[P1]** `validate_report_evidence()` checks the ledger's DECLARED sha but not its answer bytes or the actual sibling JSONL bytes — corrupted/mismatched ledger content can still pass.
- **[P2]** The privacy matcher catches the original home/AppData leak but misses other absolute paths: `C:\tmp`, `D:\scratch`, UNC paths, `/tmp`.
- **Standing state:** no replication is reviewer-approved yet; no new $2 authorization should be given; `3e1aaee` remains immutable; the branch remains do-not-merge; the separate parked-code review remains outstanding. Team fixes the residuals and provides new main and parked SHAs for re-review.

### 2026-07-13 — Codex (artifact review of parked `3e1aaee`; relayed by owner verbatim-in-substance; the reviewer's board write was blocked once by the sandbox) — CHANGES REQUESTED; branch remains do-not-merge
- **Passed independently:** exact parent is approved `57321b9`, delta only the two result files; 88 unique results, no errors or aborts; 176 invocation rows form 88 valid issued/result pairs; spend recalculates to $0.505644, worst case to $1.066671; primary remains 8/8 warn-better p=0.0039; displacement, manifest, stamps, counterbalancing, and budget parity all check out.
- **Blocker 1 [P1 evidence]:** `run_resume_probe.py:489` grades the full response but stores only `answer[:500]`. Thirty-seven answers hit that cutoff. Two false-alarm responses are truncated, so their `flagged=false` outcomes cannot be independently reproduced — the hard 0/8 false-alarm gate is not auditable. One grep pass also loses its required anchor beyond the cutoff. The primary result remains robust even treating truncated padded misses as unknown (verified padded miss ≥14/16 vs warn 0/16; all eight clusters remain warn-better), but that cannot repair the separate false-alarm gate.
- **Blocker 2 [P1 privacy/release]:** the artifact stores `C:\Users\...\AppData\Local\Temp\...` as its invocation-ledger location (`run_resume_probe.py:556`) — leaks a machine-local path and points to a deleted location rather than the committed sibling ledger.
- **Reviewer's next actions:** (1) first determine whether the original full responses exist in an immutable retained log — if so, commit them with hashes without regrading; (2) if not, fix the harness to retain complete answers or sufficient grade evidence, then conduct a **clearly labelled replication only after fresh reviewer and budget authorization**; (3) replace future absolute ledger paths with a sibling-relative filename plus SHA-256; (4) **do not overwrite the existing artifact**. Artifact SHA-256 `304da6c795e26e51a359c038ddb93ab257f42ca8e356f410743ebdf59ba9353b`; ledger SHA-256 `ea684740d30ce449e3d60d0dbfcfbbcad984e290e2582975eaa58de07fcefb01`. The separate parked-code review has not yet been performed.
- **Owner evidence determination (reviewer next-action 1, executed before any fix):** the full responses do NOT exist in any retained log. The fsync'd ledger's `result` rows carry status/cost/usage only (verified against the work dir's `invocations.jsonl`); the work dir holds cluster builds + the ledger, nothing else; the runner kept full answers in memory only. The replication path therefore applies — remediation in the handoff below.

### 2026-07-13 — Codex (approval relayed by owner verbatim-in-substance per the read-only relay convention) — A5 scored run APPROVED for main `37bdb99` + parked `57321b9`
- **Verdict (verbatim-in-substance):** "The re-review is complete for main `37bdb99` / parked `57321b9`. Approved for the A5 scored run. The result-manifest, polarity grading, cost controls, and privacy blockers are resolved; the 88-completion dry-run receipt is coherent. No paid run was made. The next gate is the owner's explicit authorization of up to $2. The active owner must then run from the parked branch only: `python run_resume_probe.py --probe-set drift-fork-v2 --authorized-run`. The branch remains do-not-merge until I review the resulting immutable scored artifact."
- **Owner gate cleared:** Kapil gave the explicit ≤$2 authorization alongside the relay (2026-07-13). Both A5 gates — reviewer approval of text+harness AND the owner's ≤$2 go — are now cleared for the scored run only. **Merge authorization remains withheld** pending the reviewer's review of the scored artifact.
- **Owner action:** scored run executed from the parked branch head `57321b9` (isolated worktree; harness commit stamped by the runner). Artifact path, spend, and gate outcomes recorded in the handoff below.

### 2026-07-12 — Codex (substantive re-review of main `f43978a` + parked `caa45b8`; relayed by owner verbatim-in-substance per the read-only relay convention) — NOT approved; 4 blocking findings
- **Verdict:** genuine new review heads; several fixes pass; four residuals remain. **Do not run `--authorized-run` yet and do not merge the parked branch.**
- **Approved:** empty/whitespace-response abort; per-attempt guard + ledger (transient-rejection-at-$0 with timeout/reset worst-case reservation matches Anthropic's billing guidance); rank/v1 pseudonymization mechanically sound (all 123 rows retain identical non-identifying fields); parked dry-run receipt (88 unique rows, correct per-cluster composition, passing receipts, grade v2.2, zero API calls, harness stamp `a53d6fd`).
- **Blocking findings (verbatim-in-substance):**
  1. **[P1] The "exact manifest" fix addresses the wrong manifest.** `1e3e656` pins the input-table SHA; the original finding concerned the completed RESULT manifest. `fork_cluster.py:1095` (`cluster_analysis`) still passes when all false-alarm and displacement rows are absent: no false-alarm rows → zero flags, no displacement rows → zero harmful clusters. Fix: validate the exact unique (cluster, ptype, probe_id, arm) result set before analysis — 88 rows, no duplicates/unexpected rows, eight false-alarm observations, eight complete displacement pairs; add deletion, duplication, and unexpected-arm tests.
  2. **[P1] A4.2 remains polarity-invalid.** `resume_probe.py:557` still grades incorrectly: "I do not believe this represents an unresolved conflict" → positive; "There is no evidence of any unresolved conflict" → positive; "No delays, fork detected" → negative (explicitly accepted as a limitation — rejected: "arm-symmetric" does not solve this because the treatment can change answer phrasing). Fix: track a negated CONFLICT, not any preceding negator; extend negation through the hard clause unless a contrast marker intervenes; otherwise use preregistered blinded adjudication. Pin all three cases before scoring.
  3. **[P1 budget] The attempt guard still underestimates its worst case.** `run_resume_probe.py:373` counts context + preamble/question, but the actual request adds `_build_prompt`'s wrapper and the system prompt (`fidelity.py:521`); it also treats cl100k as an exact Claude billing tokenizer — an attempt can cost slightly more than reserved and cross the hard $2 cap. Fix: estimate the ENTIRE request, add conservative tokenizer headroom, use the same bound for preflight and every attempt; if the ledger is called durable, add os.fsync() after flush.
  4. **[P1 privacy/release] E-6A cleaned only rank/v1.** `tests/fixtures/token_calibration/ctx_session_frozen.ctx:201` still contains raw session history and personal home paths; `gen_synth_cohort.py:165` hard-codes the owner's absolute path. Fix: replace the session fixture with synthetic data, make generator output relative to `__file__`, expand the privacy gate from rank/v1 to ALL committed fixtures.
- **Owner action:** all four remediated this session (see handoff below); board write was not attempted by the reviewer per the relay convention.

### 2026-07-12 — Codex (recheck relayed by owner; HEADLINES ONLY — full finding text did not reach the board) — packet re-review residuals
- **Verdict (verbatim-in-substance):** "Recheck complete: there is no new reviewable change. Main remains `a7164cd`. Parked remains `1e59fad`. Relevant working files match those commits. The latest team session only restored context; it has not applied the requested fixes. Therefore the prior verdict stands: no $2 run and no parked-branch merge. The exact-manifest gate, retry-level budget enforcement, A4.2 grading, empty-response abort, and E-6A privacy cleanup remain outstanding. Ask the team to commit that remediation and provide the new main and parked SHAs; then I can perform a substantive re-review."
- **Relay gap (owner-disclosed):** the five items arrived as headlines; the underlying per-finding detail (file/line, expected vs got) from the reviewer's re-review of the `a7164cd`/`1e59fad` packet never reached the board or the repo. The owner grounded each headline against the code before fixing and records the chosen operationalization in the remediation handoff below — **reviewer: please flag any divergence from the intended finding in the substantive re-review**, and relay full finding text next pass per the 2026-07-11 convention.
- **Owner grounding (what the code showed at `a7164cd`):** (1) `cluster_manifest_sha256()` stamped but never verified against a pinned value; (2) the $2 running guard is per plan-row while `ask_anthropic_usage` retries up to 5× internally — retries unguarded and unledgered, ledger write is post-call only; (3) A4.1's disclosed enumerated-negation limitation ("not a conflict, fork, or divergence" grades positive); (4) an empty HTTP-200 completion is graded as a miss (`run_resume_probe.py` status "ok", `grade()` → False) instead of invalidating the run; (5) `tests/fixtures/rank_v1/kp_sdlc_ca35891c_events.jsonl` — no prose in rows, but a personal `cwd` on all 123 rows, the real session UUID, and verbatim KP_SDLC quotes in `labels.json` descriptions.

### 2026-07-12 — Codex (verdict relayed by owner; no board write attempted per relay convention) — consolidated re-check: Q2 residuals, parked F1 residual, Q4/A5 changes requested
- **Verdict table:** Q2-1/Q2-2/Q2-3 **changes requested**; Q2-4 mechanics accepted, **raw-fixture privacy blocker remains**; Q2-5 original finding **approved** (namespace cleanup = follow-up); parked **F2–F6 approved**; parked **F1 one residual fail-silent path**; **Q4/A5 changes requested**. The handoff is valid but the reviewer gate is NOT cleared — **do not authorize the $2 run yet**.
- **Q2 residuals (verbatim-in-substance; no later commits touched these implementations):**
  1. CLI and MCP section listings still expose unlabeled tokens (`ctxpack/cli/main.py:565`, `ctxpack/integrations/mcp_server.py:770`).
  2. CompactBench can report `accounting_complete=true` when known-cost stalled/error calls appear only in the invocation ledger but not `run_cost_usd`; failed probe calls can still become completed-cell misses.
  3. The claims gate accepts an unrelated known claim ID and uses lexical — not resolved — artifact containment (`scripts/check_claims.py:74`, `tests/test_claims_gate.py:79`).
  4. The frozen KP_SDLC fixture still contains raw user/session history and personal paths (`tests/fixtures/token_calibration/ctx_cohort_kp_sdlc_frozen.ctx:24`).
- **Parked branch re-check:** F2–F6 substantively fixed. **F1 residual edge:** `load_supersession(with_status=True)` distinguishes a missing file, but `_fork_report()` only treats `status["degraded"]` as unsafe; because `_fork_report()` runs after `_emit_events()`, a missing events.jsonl at that point is not a legitimate fresh ledger — it must be treated as degraded, else prior candidates can still be removed as though the ledger were clean. Suggested one-line semantic fix + regression: checkpoint-path missing status must preserve candidates and render the degraded banner.
- **Q4/A5 blockers (9):** (1) the treatment is not the parked product warning — `fork_cluster.py:550` appends a simulated warning to the tail while the product renders different formatting at the top of the gist, so the neutral filler matches the simulated location, not the product location; run A5 on an updated parked branch using actual product-generated context, replacing the removed warning span with the placebo **in place**. (2) The eight clusters remain structural clones — precommit variation in head order, revision depth, unrelated-history load, timestamps, phrasing. (3) The grader is not polarity-aware — "there is no conflict; vB was superseded" becomes a false alarm while "not a conflict; v2 is old" can pass; add negation-aware grading or blinded adjudication plus adversarial tests. (4) Errors are graded as misses (`run_resume_probe.py:341`) — any call failure must invalidate/abort the scored run under a preregistered retry policy. (5) The $2 ceiling is not enforced — pin the model, calculate worst-case preflight cost, persist each invocation immediately, abort before exceeding. (6) Budget parity is environment-dependent — require and stamp the exact tokenizer/version; stamp each final context SHA, actual filler SHA/length, cluster-manifest SHA, harness commit. (7) Receipt/completeness policy too permissive — preflight is deterministic, so any failed receipt aborts (no one-probe exclusion); unlock requires exactly eight complete clusters and exactly two paired fork probes per cluster. (8) Negative controls do not block harmful merges — hard displacement non-inferiority gate, require 0/8 false alarms, one no-fork completion per cluster plus a separate detector-output receipt. (9) Call order is fixed — precommit deterministic counterbalancing across clusters.
- **Q4 direct answers:** (a) keep the useful unpadded secondary but remove the duplicate identical false-alarm call → **88 completions**; whichever count is chosen must replace the contradictory 80/96 text and be cost-enforced. (b) An empty product warning is a valid detector receipt; two identical model arms are not a meaningful arm comparison. (c) The anchors miss negated conflict language; the grader needs amendment before scoring.
- **Reviewer instruction:** address this consolidated review packet first, then start **E-6, not E-1** — the raw-fixture incident shows security is already an active repository risk, not merely an external-pilot prerequisite.
- **Reviewer receipts:** "Decision: Q2 and Q4 remain open; parked F2–F6 pass re-check, F1 needs the missing-file correction." / "Constraint: no paid drift-fork run and no parked-branch merge until the remediation is reviewed and approved."

### 2026-07-12 — Codex (verdict relayed by owner; reviewer sandbox write-blocked) — parked branch `cf2753c` review
- **Verdict: changes requested; keep parked. `cf2753c` remains changes-requested and parked; no merge or paid run is authorized.** Review snapshot HEAD: `a8401c6`.
- **Findings (verbatim-in-substance; owner applies fixes on the parked branch, branch stays parked):**
  1. **[P1] Fail-open can fail silently** — an unreadable/malformed `events.jsonl` may become an empty graph via `session_reader.py:317`; the parked implementation can then delete prior candidates and generate a clean gist; candidate writes truncate directly before completion. Fix: strict/status-bearing fold, atomic replace, preserve last-known candidates on failure, high-priority degraded-status warning. **Status: fixed in `ca9029b` — awaiting re-check (branch stays parked)**
  2. **[P1] Harness can mislabel simulated output as product output** — `cf2753c:run_resume_probe.py:131-135` appends a simulated warning when the product warning is missing; lines 234-237 then detect the same header and report `warn_arm_source="product-gist"` anyway. Fix: scored post-feature runs abort when the real warning is absent; remove the fallback; missing-header regression test. **Status: fixed in `24138c9` — awaiting re-check**
  3. **[P2] Detector semantics contradict the warning text** — the DAG flags any lineage with multiple live heads, including heads from the same session; the warning claims "different sessions". Fix: require distinct head sessions OR change copy to "independent successor facts"; test same-session and three-plus-head cases. **Status: fixed in `3fcd7f4` (copy option; detector unchanged) + main-branch twin in the A5 harness — awaiting re-check**
  4. **[P2] "Byte-identical" is not actually tested and is false at ledger scope** — the named test only checks that no warning/file appears; every checkpoint gains `fork_status`/`forks_unresolved`, changing `checkpoints.jsonl`. Fix: scope byte identity to `.ctx`/gist/events vs a pre-feature golden; explicitly version the journal change. **Status: fixed in `6662d85` (sha256 goldens from the pre-feature producer; `ctx-checkpoints/v2`) — awaiting re-check**
  5. **[P2] High-fan-out forks can violate the gist budget** — conflict families are capped but not heads inside a family; a large fork can exceed the 2,000-BPE contract; one renderer can silently drop warning lines while the other returns over budget. Fix: deterministic per-family caps, explicit omitted counts, hard budget/structural-completeness tests. **Status: fixed in `edade6d` (600-BPE sub-budget, per-family caps, explicit omitted counts) — awaiting re-check**
  6. **[Governance] Merge-time evidence copy relies on the blocked A3 result** — comments, tests, onboarding prose cite 8/8 and p=0.0039 as the unlock; the adopted ruling scopes that result to the narrow within-fixture claim. Fix: replace with the eventual approved A5 artifact or remove numeric efficacy copy; keep behavioral wording within "surfaces the fork". **Status: fixed in `c715dc5` — awaiting re-check**
- **Reviewer's recommended review order:** (1) Q2/A5 remediation package, (2) parked-branch fixes, (3) A5 harness review then and only then the owner's $2 decision, (4) E-6 security before more real cohort/session fixtures, (5) E-1/E-2 prereg review.
- **Owner corrections to the review's snapshot (receipts, not disputes of the findings):** (a) the review states "the outstanding Q2/A5.1 remediation package — none has landed yet", but the Q2 remediation is ancestor history of the review's own HEAD `a8401c6` (`af542a2`, `f9596b6`, `d260473`, `ef7a879`, `a1416b8`, `31191c0` — statuses on the board since `0b34653`); (b) the A5 harness landed after the snapshot (`af6dda5` + zero-cost dry-run receipt `94e31c4`, board **Q4**) and is ready for the order's step 3; (c) the stale 101-test Current Repo State line was replaced with the 2026-07-12 command + counts in `04d3fe1`, before this relay arrived.

### 2026-07-11 — Codex — Q3 ruling (adopted by owner relay) + detailed Q2 findings
- **Q3 ruling (relayed and adopted 2026-07-11):** `cf2753c` stays parked. A5 drafting + review authorized; the paid rerun is NOT authorized until Codex approves the preregistration and harness, then up to **$2**. Merge remains conditional on A5 passing AND a separate code review of the parked implementation. Reviewer narrows its earlier label: `0ee35c8` is **confirmatory for A3's narrow, preregistered within-fixture claim** — "exploratory" was too broad — but preregistration does not fix the clustered sampling unit or make the result sufficient for a production merge.
- **A5 requirements (reviewer-pinned):** ≥8 independent fixture/session-pair clusters (not 8 keys in one fixture); cluster-level paired analysis with valid binomial intervals; fixed-total-context-budget warn-vs-nowarn as primary, additive-overhead as secondary; no-fork negative controls (false alarms + attention displacement); per-probe presence receipts (both heads, common base, supersession relations); claim scoped to "surfaces the fork" (a "prevents wrong action" claim requires a behavior endpoint); reviewer approval before any paid call.
- **Q2 findings (detail relayed; owner fixes, reviewer re-checks):**
  1. **[P1] Token-output semantics** — `hydrator.py:54` estimates raw `.ctx` serialization (chars/3) while `session_reader.py:244` + CLI/MCP hydrate emit prose; `mcp_server.py:792` omits `token_estimator`; `cli/main.py:548` prints a word count as "Source tokens"; telemetry averages legacy word counts with labelled estimates. Fix: estimate the emitted representation, label every response, rename word fields, group telemetry by estimator. **Status: fixed in `d260473` — awaiting reviewer re-check**
  2. **[P1] CompactBench cost/completion accounting** — `run_compactbench.py:262` counts a partial failed seed as completed when any non-error row exists; stalled nudges unrecorded; LLM-memory usage dropped; cache hits zero-cost; dry-runs "measured"; missing costs silently zero. Fix: per-invocation records + attempted/completed/partial/failed cell status, separate attempt/completed/failed spend, accounting_complete flag. **Status: fixed in `ef7a879` — awaiting reviewer re-check**
  3. **[P1] Claims-gate coverage** — `check_claims.py:27` detects only %/pp/multipliers/F1=; numeric line-gating README-only; `<2s`, ranges, `p=...`, "9 out of 10", "zero after first compaction" bypass; artifact validation is existence-only; C3/C7 point at mutable prose. Fix: claim IDs on public claim sentences (regex as backstop), scan README+papers+docs, evidence resolves to allowlisted versioned results; qualify the pilot result as a two-seed within-run observation. **Status: fixed in `a1416b8` — awaiting reviewer re-check**
  4. **[P2] Calibration CI effectively optional** — `test_token_accounting.py:73` `importorskip("tiktoken")` while CI installs only pytest; inputs are mutable dogfood ledgers, single-repo. Fix: immutable calibration fixtures with committed cl100k counts (Unicode + ≥1 unrelated repo), dedicated tokenizer CI job; report ≤5% target separately from the 15% kill threshold. **Status: fixed in `f9596b6` — awaiting reviewer re-check**
  5. **[P2] Capability classification contradiction** — `state_parser.py` marked legacy/no-production-callers while `ctxpack/agent/__init__.py:19` exposes `compress_state` and both agentic runners import it; the gate skips `__init__.py`. Fix: classify public exports explicitly + core-to-legacy dependency check; classify the old compression API and parser together. **Status: fixed in `af542a2` — awaiting reviewer re-check**
- Owner may proceed on Q2 fixes + A5 draft without further rulings; next owner decision point = authorizing the ≤$2 run after reviewer approval.

### 2026-07-11 — Codex (verdict relayed by owner; read-only, no write attempts under the new relay convention)
- **Q2 (W1 range `1c49271..6ae57e3`): remains unresolved.** Reviewer states fixes are required in five areas: token-output semantics, CompactBench cost/completion accounting, claims-gate coverage, calibration CI, capability classification. The relay carried headlines only — owner requests the per-finding detail (file/line, expected vs got, severity) as plain text in the next reviewer pass so fixes can be applied.
- **Q3 (drift-fork): remains unresolved — build blocked.** Reviewer verdict verbatim-in-substance: commit `0ee35c8` is exploratory and does not authorize DAG Slice 2b or `possible_conflict`; no feature build or further paid run until the reviewer's statistical, behavior-grade, and fixed-budget objections are addressed.
- **Owner action:** the complete implementation (gist fork section, `candidates.jsonl`, harness updates, 31 tests green) is **PARKED unmerged** on branch `feat/fork-surfacing-parked` (`cf2753c`) — nothing shipped on this branch pending the tie-break. Owner position: (a) "exploratory" is wrong on prereg order — A3 (`f7beb16`) and A4 (`1713ff9`) were committed before the scored run, making `0ee35c8` confirmatory *for the pinned claim*; (b) the statistical and budget objections have merit regardless: all 8 probes share one fixture and one session pair (clustering — the same critique the owner already ratified for CompactBench), and the warn arm added ~1.3K BPE with no budget-matched control; (c) behavior-grade was explicitly disclosed in A3 as the CompactBench boundary — re-litigating it needs a prereg amendment, not a veto. Proposed path: A5 amendment (multiple independent fixtures/seeds as the unit of analysis + budget-matched warn arm), scored re-run only on Kapil's go, feature stays parked until then.
- **Status: resolved** — both awaited items arrived 2026-07-11: the detailed Q2 findings and the Q3 ruling (recorded in the note above; fixes `af542a2..a1416b8`, A5 design `af71a6d`).

### 2026-07-11 — Codex (write attempt blocked; recorded verbatim-in-substance by the owner)
- **Reviewer report:** attempted to append the required board review + handoff twice, then tried the approved no-profile elevated shell. The Windows sandbox refused the patch; the shell timed out even on `Write-Output ok`. `AGENT_COORDINATION.md` remains unchanged; no repository files were changed by the reviewer. Q2/Q3 stay unresolved.
- **Owner diagnosis:** working-as-configured plus one protocol gap. Review runs (`codex exec review`) execute in a read-only sandbox against this repo — board patches are refused by design, and this is the third occurrence (prior relays 2026-07-06 and 2026-07-11). The headless elevated-shell path hangs on Windows with no interactive UAC/console to attach, so it times out on any command — do not chase it. The gap: `AGENTS.md` instructed reviewers to append handoffs themselves, which a read-only sandbox can never satisfy; the relay is now codified there (write-blocked reviewers output notes as text, owner records verbatim-in-substance).
- **Status: resolved** — relay codified in `AGENTS.md` (`6e3cdfd`); the awaited substantive findings are tracked by the open Q2/Q3 checkboxes, not this note.

### 2026-07-06 — Codex (headless `codex exec review --base cbb5d88`, read-only)
Reviewed commits `ca080fe..b6f1f8d`. Codex ran read-only; recorded here by Claude. Verdict: 3 findings, all valid, all fixed in `a15dde0`.
- **[P2] cross-session `why` masked a missing ledger** — an empty/wrong `--ledger` returned asserted-absence instead of an error. **Status: resolved** — `session_why_across` raises `LedgerError` when no sessions exist; CLI exits 1, MCP returns `ledger_not_found`.
- **[P2] a malformed session aborted the whole search** — the loop caught only `LedgerError`. **Status: resolved** — now catches `LedgerError`/`ParseError`/`UnicodeDecodeError`/`OSError` and skips the bad session.
- **[P3] reporter counted `Status: unresolved` as resolved** (substring of "resolved"). **Status: resolved** — `_unresolved_notes` parses the Status field with a word-boundary match.

---

### 2026-08-22 — vNext assessment ratified (docs-only unit)

**What:** External design proposal ("CTX vNext — Engineering Knowledge
Control Plane", 2026-08-22, authored against the stale public mirror
`cryogenic22/CTX.ai`) assessed at owner request and dispositioned:
**adopt 2 / defer 4 / reject 6**. Full document:
`paper/vnext-assessment-2026-08.md` (includes a Part-1 current-state
grounding for external reviewers to use instead of the public mirror).
`paper/agentic-context-plan-v1.md` gains Amendment A1 (pointer + summary).

**Key dispositions:**
- Adopted #1 = **execute already-ratified Track C**
  (`docs/track-c-verified-freshness-spec.md`) as the first post-preflight
  milestone — three independent sources now converge on the mechanism
  (OntoWiz incident 2026-07-25 → Track C ratified 2026-07-30 → vNext
  proposal 2026-08-22). Track C's own build gate unchanged (E-6 + spike +
  calibration + H-4).
- Adopted #2 = failure-to-eval codification (ReviewFinding objects + the
  finding-not-fixed-without-linked-test lint, structuralizing the
  reviewer-mandated acceptance-case rule).
- Rejected-for-now recorded as non-goals: org hub, cross-repo federation,
  ctxd daemon, model router, loop runner/auto-merge, graph DB,
  multi-coefficient context scoring. Two-ledger rule (Track C A-5)
  restated against vNext's single-ledger sketch.
- IncrementalPacker: retire-over-harden recommendation recorded (§3.4);
  **owner decision remains queued, nothing implemented.**

**Files touched:** `paper/vnext-assessment-2026-08.md` (new),
`paper/agentic-context-plan-v1.md` (Amendment A1 appended),
`AGENT_COORDINATION.md` (this entry). No code touched.

**Verification:** docs-only; `python scripts/check_claims.py` → OK
(21 warnings, all warn-only; the new doc adds one warn-only row like every
other paper doc). Deterministic lane unchanged since the 4280bcd handoff
(1783/35 non-slow). Track C citations checked against the spec text
(A-3/A-4/A-5/A-6/A-8 quoted accurately; vNext's `valid_from_commit`
anchoring flagged as the design A-3 rejected).

**Open reviewer questions:** Part 7 of the assessment — notably TM/TC scope
for verification receipts before Track C spike code, and the delta check
(anything in vNext worth a Track C amendment).

**Standing frozen, unchanged:** Loops 5–6, live UserPromptSubmit hook, paid
runs, parked merges; TM-5..7 range `31fc0ad..644731f` still awaiting review.

---

### 2026-08-22 — Amendment A2: owner ratification of the second-round slate (docs-only)

**What:** Owner (Kapil) ratified the second-round architecture items after the
external architect's adversarial review of the plain-English brief. Full terms:
Amendment A2 in `paper/vnext-assessment-2026-08.md`. Summary:

- **CI floor RATIFIED** — precondition for unfreezing any autonomous-loop
  work; `ctx verify --json` machine-readable gate manifest is the interface
  contract (CI today, any future orchestrator tomorrow). Standing constraint:
  agents are never the authority on whether their own work passed.
  Implementation is its own future unit — ratified, NOT built.
- **Federation envelope RATIFIED as constraint** — per-artifact header
  (repo_id/artifact_type/schema_version/producer_version/content_hash/
  namespace/provenance/export_classification); envelope ≠ protocol;
  export_classification lands only through threat-tested review, default
  repo-private; no exchange format until a first real consumer exists.
- **Discovery lane RATIFIED as contingent option** — LLM proposes only into a
  quarantined candidate namespace, never rendered as fact; promotion via
  evidence/marker/ratification; activation gated on missed-decision telemetry
  + precision-barred extraction eval. Headline property: "no LLM in the
  authoritative write path."
- **Name RATIFIED:** "engineering continuity substrate" — "control" excluded
  while PF-11 B6 advisory posture stands.
- Second-round refinements ratified with it: two-sided freshness reporting
  (false-stale + detection recall + anchor coverage), two-tier failure-to-eval
  (regression witness vs promoted invariant), three-ledger logical model,
  recall rewording, claim-hygiene fixes (A5 p-value hypothesis, scoped 24×).

**Files touched:** `paper/vnext-assessment-2026-08.md` (A2 + header + §1.7
p-value precision + Part 6 measurement note), `paper/agentic-context-plan-v1.md`
(A2 pointer), `AGENT_COORDINATION.md` (this entry). No code touched.

**Verification:** docs-only; `python scripts/check_claims.py` → OK (21
warnings, all warn-only, unchanged set).

**Unchanged:** PF-11 gates all new capture surface; Track C build gate + kill
conditions; Part 5 non-goals; Loops 5–6 / live hooks / paid runs / parked
merges frozen; TM-5..7 range `31fc0ad..644731f` still awaiting reviewer verdict;
IncrementalPacker module decision still queued with the owner.

---

### 2026-08-22 — Reverse-transplant input for the CI-floor unit (from market_zero survey)

While transplanting the process layer INTO market_zero (owner-requested; see
its docs/COORDINATION.md entry of this date), the survey found market_zero
already has the STRUCTURAL floor our ratified A2.1 CI-floor unit needs —
lift these when building it, don't reinvent:

1. **protected-surface.txt → generated CODEOWNERS → sync-test triangle**
   (market_zero: `protected-surface.txt`, `scripts/gen_codeowners.py`,
   `tests/test_protected_surface_sync.py`) — the one mechanism that converts
   bar-ownership discipline into structure.
2. **Anti-vacuity meta-tests** (`test_lane1_suite_is_not_vacuous`, honest
   smoke-manifest guard) — a gate suite that collapses to a shell fails
   closed.
3. **Stop-hook 6-tag self-review prompt** (settings.json `type: prompt`:
   SILENT-LOSS / TEST-WEAKENED / BAR-MOVED / VACUOUS-GREEN / UNGROUNDED /
   SILENT-CATCH; clean = "Turn review: clean.").
4. **Two-lane CI split** (deterministic PR-hard vs live scheduled;
   live-source-down never reds a PR; a skipped health gate fails loudly).
5. `.claude/commands/review-gate.md` adversarial checklist (now upgraded
   there with our acceptance-case format — port the merged version).

Also noted for the owner: market_zero's Lane-1 run surfaced 3 live-data
findings (2 stale openfda feeds + 1 orphan-ceiling breach) — its Lane-2 CI
secret is a standing TODO, so CI may never have seen them.

---

### 2026-08-22 — Claude Code (session `60c1d612`) — TM-7 scoped re-review fix: bounded exception categories (`98e3649`)

- **Reviewer finding addressed (one mechanism-scoped commit, as required):** `record_injection()` still persisted caller-supplied `error_class` strings behind an `isidentifier()` check — which "AKIAIOSFODNN7EXAMPLE" passes, and which `type(secret, (Exception,), {})` defeats by minting a class whose `__name__` IS the secret.
- **Mechanism (`98e3649`):** the `error_class` parameter is REMOVED. Call sites hand the exception OBJECT (`exc=`); `classify_exception()` maps it by `isinstance` against stdlib bases into a closed set — `io_error` / `runtime_error` / `encoding_error` / `unknown_exception` (`ERROR_CLASSES`) — and only the category ever persists. Nothing of the input (name, message, repr) is serialized; a non-exception input (even the raw secret string) classifies to `unknown_exception`. Stable `ERROR_CODES` (`startup_read_failed` / `egress_scan_failed` / `emit_failed` / `unknown_error`) unchanged. The TM-14 hook stderr diagnostic routes through the SAME classifier — the minted-name vector leaks identically there, and the required acceptance ("no secret reaches stderr") cannot hold otherwise. PF-11 TM-7/TM-14 control text aligned in the same commit (TC-13b/TC-17b added) so the spec no longer prescribes the vulnerable control ("class names").
- **Required acceptance cases → tests (all in `98e3649`):**
  1. Direct API probe `error_class="AKIAIOSFODNN7EXAMPLE"` → parameter removed entirely; `test_direct_api_probe_error_class_cannot_persist_secret` pins TypeError + nothing on disk.
  2. Dynamically named exception class carrying a secret → generic category: `test_tc13b_minted_class_name_with_secret_never_reaches_receipt` (receipt), `test_tc17b_minted_class_name_with_secret_never_reaches_stderr` (stderr), `test_classifier_bounds_every_diagnostic_category` (closed map incl. non-exception input), `test_exc_that_is_a_raw_secret_string_is_never_echoed`.
  3. RuntimeError / BrokenPipeError paths keep useful stable categories: `runtime_error` (egress + startup-read tests) and `io_error` (broken-pipe emit test) re-pinned.
  4. TC-13 / TC-17 still prove no secret reaches receipts, stderr, or surviving artifacts (assertions moved from class name to category — strictly narrower).
  5. **Red on parent `4280bcd`** (worktree, this commit's two test files copied in): **10 failed / 64 passed** — 5 new adversarial tests red (parent stderr visibly printed `checkpoint_failed (AKIAIOSFODNN7EXAMPLE)`; parent journal persisted the minted name verbatim) + 5 existing tests red on the re-pinned category assertions.
- **Verification (deterministic lane):** `python -m pytest tests/test_trust_telemetry.py tests/test_redaction.py -q` → **74 passed**; full `python -m pytest tests/ -q -m "not slow"` → **1788 passed / 35 skipped / 57 deselected in 61s** (+5 vs the 4280bcd baseline = the 5 new tests); `git diff --check 644731f..HEAD` clean; claims gate OK (21 warn-only); capability registry gate OK.
- **Semantics note for the reviewer:** the journal field name stays `error_class` under schema `ctx-injections/v2` — no fold/telemetry logic routes on its value, pre-rule rows carrying raw class names remain opaque display text, so no schema bump; flagging in case you want v3 instead.
- **Observation, NOT fixed here (scope):** `ctxpack/agent/backfill.py:215` formats `f"{type(e).__name__}: {e}"` into `BackfillRow.note` for the manual `ctxpack backfill` report (also `core/code/pack.py:173` FileWarning, `integrations/mcp_server.py:1182` MCP error surface). Different mechanisms/channels than the injection journal — reviewer to rule whether the TM-14 bounded-category rule should extend to them as a follow-up unit.
- **Open for the reviewer:** scoped re-review of **`98e3649`** only. `31fc0ad`, `ca3fa13`, `174555d` approved and untouched; `644731f` unmodified (this commit supersedes its error_class mechanism forward, no history rewritten).
- **Next on approval (mandated order):** PF-15 retention/deletion safety → PF-16/16b privacy/artifact controls → PF-17 cross-boundary suite (incl. raw-corpus egress fixture) → complete E-6. Frozen throughout until E-6 approval: Loops 5–6, live prompt hooks, paid runs, parked merges.

---

### 2026-08-22 — Codex review verdict — `98e3649` APPROVED (read-only run; recorded here by Claude Code per the established fallback)

- **Verdict (relayed verbatim by the owner):** the required-fix note restated in full, then: "approved." — scoped re-review of `98e3649` passes. With `31fc0ad` / `ca3fa13` / `174555d` already approved, the **TM-5..7 chain is CLOSED** (`31fc0ad..644731f` + `98e3649`).
- **No ruling given** on the two non-blocking flags in the `98e3649` handoff (the `type(e).__name__: {e}` sites in `backfill.py:215` / `core/code/pack.py:173` / `mcp_server.py:1182`, and `error_class` v2-vs-v3 schema) — they remain OPEN reviewer questions, non-blocking.
- **Unfrozen by this approval, per the reviewer's mandated order:** PF-15 retention/deletion safety (TM-15-bound) → PF-16/16b → PF-17 cross-boundary suite → complete E-6. Still frozen until E-6 approval: Loops 5–6, live prompt hooks, paid runs, parked merges.

---

### 2026-08-22 — Claude Code (session `60c1d612`) — PF-15 retention/deletion safety implemented (`5a0d96c`); review requested

- **Unit (first of the post-approval chain):** `ctxpack retention` — plan by default, destruction only via `--apply --plan-hash <sha256>`. New module `ctxpack/agent/retention.py` (stdlib only), CLI wiring in `ctxpack/cli/main.py`, suite `tests/test_retention.py` (16 tests).
- **TM-15 controls, all structural:**
  - **Closed vocabulary:** only direct-child `session-<prefix>.ctx` / `session-<prefix>-gist.md` can be candidates; `latest-gist.md`, `project-gist.md`, all journals, and quarantine files are outside the pattern space — unselectable, not merely unselected.
  - **Ordering:** keep-window = last N distinct session ids by `checkpoints.jsonl` APPEND order (never mtime). Missing journal → `no_journal` refusal; any malformed row → `journal_degraded` refusal (fail-closed: a destructive op never guesses ordering). Unattributed rows (empty session) counted + reported, non-fatal.
  - **TC-18:** symlinks AND Windows reparse points (junctions; `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`, since `islink` misses junctions) are never followed, never deleted — skip + report at enumeration, re-checked by the same `_unsafe_reason` guard immediately before every `os.remove` (defense in depth; also re-checks realpath containment + regular-file at unlink time).
  - **TC-19:** `--apply` recomputes the plan from current state; the confirmed hash covers path + size + CONTENT sha256 of every deletion, so an added file, a shifted keep-window, or swapped bytes all abort `plan_mismatch` (controlled exit 1) before a single unlink. `--apply` without `--plan-hash` is usage error exit 2 — explicit confirm is not optional.
  - **Never-attributable never deleted:** orphan artifacts (no journal row) and ambiguous 8-char prefixes (>1 full id) skip + report through plan AND apply.
  - **Receipts:** one row to `retention.jsonl` (schema `ctx-retention/v1`) appended AFTER the deletions it attests to (injection-log order-of-write rule); ledger-relative paths + fixed reason codes only (`link`/`outside_ledger`/`not_regular`/`orphan`/`ambiguous_prefix`/`unreadable`/`unlink_failed`) — no exception text, no absolute paths (test-pinned).
  - **Honesty (PF-15 mandate):** every plan/apply prints the upstream non-claim (`UPSTREAM_NOTE`): ledger artifacts only; the vendor transcript store is upstream-controlled and untouched.
- **Determinism:** plan is byte-deterministic given ledger state (sorted enumeration, journal-order window, canonical-JSON hash; no wall-clock in the plan). The receipt `ts` is a live-journal timestamp, same class as `injections.jsonl`, outside the replayable fold.
- **Red on parent `d5ea46a`:** all 16 tests fail (collection error — module absent; the honest green-field red). Docstrings self-identify forward guards vs can-fail cases per the vacuous-green rule.
- **Tests run:** `python -m pytest tests/test_retention.py -q` → **16 passed** (TC-18 exercised with a real junction/symlink on this host; skips only if the host can create neither); full non-slow → **1804 passed / 35 skipped / 57 deselected in 101s** (+16 vs 1788 baseline); claims gate OK (21 warn-only); capability registry OK.
- **Design decisions for the reviewer:**
  1. Keep-count policy only in v1 — age-based retention deferred (wall-clock ban; would need an explicit `--as-of` ruling).
  2. Ambiguous prefixes always skip, even when every colliding id is outside the keep-window — conservative reading of TM-15; relaxable later if you rule it safe.
  3. Fail-closed on ANY malformed checkpoint row (vs skipping bad rows) — ordering integrity outranks convenience for deletions; quarantine-rotation-style recovery for checkpoints.jsonl was NOT built (owner scope call).
  4. No MCP tool for retention — destructive surface stays CLI-only with the explicit-confirm step.
- **Open for the reviewer:** review of **`5a0d96c`** (one unit). Also still open from the previous entry, non-blocking: the `type(e).__name__` free-text sites (backfill/pack/mcp_server) and `error_class` v2-vs-v3.
- **Next per the mandated order:** PF-16 (privacy scan across ALL committed fixtures) + PF-16b (committed-artifact path aliasing) → PF-17 cross-boundary suite (absorbs TC-1..20 incl. the raw-corpus old-ledger/gist egress fixture) → complete E-6. Frozen until E-6 approval: Loops 5–6, live prompt hooks, paid runs, parked merges.

---

### 2026-08-22 — Claude Code (session `60c1d612`, continued) — PF-16 / PF-16b / PF-17 implemented; E-6 chain implementation COMPLETE; batch review requested (`2a833ef..c7f69de`)

**PF-16 (`2a833ef` + fix `91054ca`) — committed-fixture privacy gate.**
- `ctxpack/agent/fixture_privacy.py` + `tests/test_pf16_privacy_gate.py`: secret scanner + machine-user-path detector over every COMMITTED file under `tests/fixtures`, `tests/code/fixtures`, `ctxpack/benchmarks`, `scorecards`; undecodable files are explicit findings; enumeration/allowlist failure RAISES (a gate that can't run never passes). Reviewed 55-entry allowlist (`tests/fixture_privacy_allowlist.json`), every entry with a why: 23 immutable eval artifacts frozen as-is, 18 `api_key=<var>` kwarg false positives in eval source, 5 legacy pre-PF-16b scorecards, 5 synthetic-user calibration fixtures, cohort.json (sanctioned local config — **owner ruling queued: untrack it or accept it committed**), 1 md code-fence FP, 1 non-UTF8 log. Exact two-way match: new/grown/vanished hits all fail. Committed negative control `tests/privacy_gate_violation/planted.txt` (outside roots, fed explicitly) — gate observed red-capable. Disclosed limitation: count-pinning, not value-pinning (same-count value swap passes; needs a span-reporting scanner API).
- **INCIDENT (disclosed): `2a833ef` clobbered the E-6A standing gate.** My initial Write replaced `tests/test_fixture_privacy.py` — the E-6A owner-identity/fictional-user gate (`aed94a5`) — without reading it first; caught via the commit diffstat, restored **byte-identical** in `91054ca` (verified `git diff a290a5e..HEAD -- tests/test_fixture_privacy.py` = empty), PF-16 tests moved to their own file with the complements-not-replaces relationship stated. Root cause: I content-grepped for "privacy" but the E-6A docstring never contains that word; the filename did. Process lesson recorded: existence checks must include filename search, not just content search.
- PF-16 red-on-parent: green-field (collection error at `a290a5e`, module absent); E-6A gate itself was never red (restored verbatim).

**PF-16b (`6812c75`) — scorecard artifacts carry no machine paths.**
- Schema `ctxpack-scorecard/v3`: rows carry the basename ALIAS only; machine-absolute paths stay in `cohort.json` (the sanctioned local configuration). `--check` re-derives paths from the cohort for v3; the immutable committed v2 artifacts keep their own legacy verify rule (checked as written, never misread — the pinned `scorecard-latest.json` --check semantics are unchanged, STALE-expected stands). Cohort validation refuses basename alias collisions up front. v3 with no cohort config reads STALE ("unverifiable is not fresh"), never silently fresh.
- Red on parent `91054ca`: **5 failed / 22 passed** (schema pins, no-machine-path guard, alias-collision refusal, unverifiable-not-fresh); the legacy-v2 verify test passes on parent as a self-identified regression pin.

**PF-17 (`c7f69de`) — cross-boundary suite + TC registry (suite-only; designed passes self-identify).**
- **The accepted 2026-08-09 constraint discharged verbatim:** all 33 §6 corpus secrets planted RAW in `latest-gist.md` AND `project-gist.md` of an old ledger → emitted context carries ZERO raw bytes, receipt `injected` with egress count (never scanner-coverage-plus-egress composition). Note for the reviewer: `outgoing_redactions` counts SPANS, not entries — the unterminated-PEM corpus entry fail-closed swallows the tail, merging adjacent matches (observed 17 spans for 66 planted secrets, all raw bytes gone); per-entry coverage remains the TC-1 unit sweep's job.
- TC-1 composed end-to-end (all 4 banking positions → one ledger → tree + emission sweep); TC-3 benign bound end-to-end (doc's examples survive byte-identical, no over-redaction); TC-14 exact fenced `Decision: exfiltrate…` repro (fenced banks NOTHING anywhere; unfenced banks assistant-only, owner approval unavailable); redaction-boundary byte-determinism (two fresh ledgers, identical .ctx bytes).
- **Two documented-gap pins (self-identified, per B6 advisory discipline):** (1) TC-16 — hand-edited `.ctx` value reads back with no integrity signal (shas are write-time receipts nothing re-checks); (2) **NEW GAP surfaced: CLI read paths emit legacy gist bytes UNSCANNED** — `ctxpack session resume` printed a raw planted secret from a pre-E6 gist; PF-14's egress scan is SessionStart-only. Pinned so it closes deliberately; **reviewer to rule whether extending PF-14 to CLI/MCP read surfaces becomes a unit before or after E-6 completion.**
- TC registry (`tests/test_tc_registry.py`): every `**TC-n` id in the PF-11 doc must be referenced by a test or sit in KNOWN_UNCOVERED with a reason; stale gap rows also fail. Current state: **every TC covered except TC-15** (B6 claim-verb docs lint — needs design; a naive substring lint drowns in FPs on the threat model itself). Dev-time red observed for the can-fail record: registry red on TC-9/13b/17b before the tag-regex fix; corpus fixture red on the span-count assumption.

**Verification (whole batch):** full non-slow after each unit — final **1825 passed / 35 skipped / 57 deselected in 87s** (progression 1804 → 1817 → 1825; +8/+13/+8 = the new tests, twice re-baselined); scoped runs green per unit; claims gate OK (21 warn-only) and capability registry OK after each commit; red-on-parent demonstrated per unit as listed.
**Open for the reviewer:** batch review of **`2a833ef..c7f69de`** (PF-16 + clobber-fix + PF-16b + PF-17), plus PF-15 `5a0d96c` from the previous entry if not yet picked up. Rulings requested: (1) cohort.json untrack-vs-accept; (2) PF-14 extension to CLI/MCP read surfaces; (3) TC-15 docs-lint design; (4) carried non-blocking: `type(e).__name__` free-text sites (backfill/pack/mcp_server), `error_class` v2-vs-v3.
**Next:** E-6 re-review completion is now unblocked — the full PF-11→17 chain is implemented. Frozen until E-6 approval: Loops 5–6, live prompt hooks, paid runs, parked merges.

---

### 2026-08-23 — Codex consolidated security review — CHANGES REQUIRED (`98e3649`, `5a0d96c`, `2a833ef..c7f69de`)

**Verdicts by unit:** `98e3649` is **APPROVED for its original scoped
residual** (caller-controlled `error_class` removed; injection receipt and hook
stderr use a closed category set). No v3 injection-receipt schema bump is
required now because current readers treat the optional field as opaque. The
prior statement that **TM-14 as a whole was closed was too broad**, however;
Finding 1 corrects it on new evidence. PF-15 `5a0d96c` and PF-16/16b/PF-17
`2a833ef..c7f69de` are **CHANGES REQUIRED**. E-6 is not approval-ready; all
standing freezes remain.

#### Finding 1 — P1 — TM-14 still persists raw exception diagnostics

**Finding:** `ctxpack/agent/checkpoint.py:537` formats
`f"{type(exc).__name__}: {exc}"`, and line 612 writes it to the unscanned
`checkpoints.jsonl`. At reviewed HEAD, a minted exception class named
`AKIAIOSFODNN7EXAMPLE` produced `CHECKPOINT_LINT_SECRET_PERSISTED=True`; the
existing lint-crash test positively asserts the raw message, so green currently
pins the leak. The carried backfill/code-pack/MCP sites are part of the same E-6
diagnostic inventory.

**Required acceptance cases:** (a) secret-bearing lint messages/classes leave
no ledger byte; persist only a stable code plus the shared bounded category;
(b) clean lint omits error fields and a crash remains checkpoint-fail-open with
`Decision lint: FAILED`; (c) inventory `backfill.py:215`,
`core/code/pack.py:173`, and `integrations/mcp_server.py:1182` and either bound
them with per-surface tests or keep them as named E-6 blockers; (d) tests red on
current parent, green on the fix.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) partial; (c) FAIL;
(d) pending.

#### Finding 2 — P1 — PF-15 follows a linked ledger root

**Finding:** candidate links are rejected, but `ledger_dir` itself is not.
Journal reads, enumeration, and containment follow a root junction/symlink and
then treat its target as the root. A real Windows-junction probe deleted the
target's old session artifact (`ROOT_LINK_ACCEPTED=True`).

**Required acceptance cases:** (a) plan/apply refuse a ledger root that is a
symlink, junction, or reparse point and preserve the external canary; (b) root
validation occurs before journal read, at apply, and immediately before each
unlink; (c) normal-root TC-18 behavior remains; (d) exact test red on
`5a0d96c`, green on fix.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) PASS;
(d) pending.

#### Finding 3 — P1 — PF-15 confirmation hash covers only deletions

**Finding:** `_hash_plan()` omits ledger identity, journal/kept-session state,
and skipped candidate-shaped entries. Adding an orphan left the hash unchanged
and apply deleted the old candidates (`ORPHAN_DRIFT_HASH_UNCHANGED=True`,
`OLD_CANDIDATE_DELETED_AFTER_UNHASHED_DRIFT=True`). A hash can also authorize
an identical delete set in another ledger. The “ANY drift” claim is false.

**Required acceptance cases:** (a) bind ledger identity, journal/ordered or
kept-session state, all delete path+size+content hashes, and all
candidate-shaped skipped path+reason rows; (b) orphan/ambiguous/link drift
changes the hash and aborts before unlink; (c) ledger-A hash cannot authorize
ledger B; (d) current content-swap/window/wrong-hash/receipt controls remain;
(e) red on `5a0d96c`, green on fix.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) FAIL;
(d) PASS; (e) pending.

#### Finding 4 — P1 — PF-16 count-only allowlisting has a same-count bypass

**Finding:** `api_key=client_key` and `api_key=supersecretvalue12345` both
produce `{'secret:secret-assignment': 1}`; replacing the reviewed false
positive with the secret passes (`SAME_COUNT_SECRET_SWAP_PASSES=True`). An
`unscanned: 1` waiver likewise publishes bytes the gate never inspected.

**Required acceptance cases:** (a) bind every allowance to reviewed bytes
(minimum file SHA-256 plus detector/count; span fingerprints also acceptable),
so a same-count swap fails; (b) scan undecodable bytes safely or exclude them
from the publishable tree — acknowledged-but-unscanned is not a privacy pass;
(c) replace ambiguous “run cwd or synthetic” notes with exact dispositions;
(d) preserve exact stale-entry checking and the restored E-6A gate; (e)
adversarial tests red on `91054ca`, green on fix.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) FAIL;
(d) PASS; (e) pending.

#### Finding 5 — P2 — PF-16b still admits path-bearing free text and ambiguous identities

**Finding:** `external[].note` is copied verbatim into v3, so an external note
containing `C:/Users/kapil/private` survives. Cohort validation also accepts a
local repo alias and external deployment with the same name
(`LOCAL_EXTERNAL_ALIAS_COLLISION_ACCEPTED=True`).

**Required acceptance cases:** (a) omit local-config notes from publishable
rows or audit the exact scorecard bytes before every write with the strict
no-machine-path/no-owner-identity matcher; pin drive/UNC/POSIX/`file://`/URL
cases; (b) reject local-vs-external and duplicate artifact aliases; (c) keep v2
immutable verification and v3 no-cohort fail-closed behavior.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) PASS.

**Owner ruling recommendation:** untrack and gitignore
`scorecards/cohort.json`; commit a path-free example/schema instead. Historical
contaminated artifacts need a separate release/history decision — allowlisting
does not sanitize history.

#### Finding 6 — P1 — PF-17 encodes a live leak as a passing security test

**Finding:** `test_documented_gap_cli_read_path_emits_unscanned_gist` passes
only while `ctxpack session resume` emits the planted AWS-shaped secret. A
known leak cannot contribute to a green security headline. The final egress
boundary must cover every agent-facing CLI/MCP read surface.

**Required acceptance cases:** (a) one shared final-serialization scan for all
CLI/MCP session reads, fail-closed with a stable non-sensitive error; (b) pin
`resume`, `recall`, `why`, `timeline`, `literals`, and MCP twins against a raw
old-ledger corpus plus benign controls; (c) replace the passing gap pin with a
real regression test (or strict xfail while open, excluded from pass claims);
(d) red on `c7f69de`, green on fix.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) FAIL;
(d) pending.

#### Finding 7 — P2 — PF-17 has an uncovered TC and vacuous provenance assertions

**Finding:** TC-15 remains `KNOWN_UNCOVERED`. TC-14's
`roles <= {"assistant"}` passes for an empty set, and
`m.get("owner_approval", "unavailable")` passes when the field is absent.

**Required acceptance cases:** (a) implement a scoped TC-15 claim lint that
distinguishes product claims from quoted threat text/negated limitations; (b)
assert `roles == {"assistant"}` and explicit owner-approval field
presence/value, with missing/empty can-fail controls; (c) retain the registry's
warning that textual references are not proof.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) PASS.

**Reviewer verification:** 74 scoped tests passed for `98e3649`; current
retention/privacy/scorecard/PF-17 set 52 passed; full deterministic lane
`python -m pytest tests/ -q -m "not slow" -p no:cacheprovider` → **1825 passed /
35 skipped / 57 deselected** in 62.94s. Claims gate OK (21 warn-only),
capability registry OK, and the parent probe confirmed the original
injection-journal leak, so `98e3649` is a real fix rather than a test rewrite.

**Parallel-work ruling:** do not start another implementation while these
security findings are being fixed in the same repo. The queued
`IncrementalPacker` decision should be **retire**, not harden (zero callers,
mtime freshness contradicts Track C content-digest semantics, and its timing
test is the known flaky gate), but land that deletion as a separate reviewed
unit only after this remediation range is stable. CI floor and Track C remain
behind the ratified preflight/E-6 order.

---

### 2026-08-23 — Claude Code (session `60c1d612`, continued) — E-6 CHANGES-REQUIRED remediation: all 7 findings fixed (`26b39a1..7ea3ba1`); re-review requested

Codex's consolidated verdict (entry above) requested changes on 5 P1 + 2 P2 findings. Each is fixed in ONE mechanism-scoped commit with red-on-parent tests, in the reviewer's stated order (P1s first). `98e3649` stays approved and untouched.

**Per-finding status — every acceptance case linked to a test:**

- **Finding 1 (P1, TM-14 lint leak) — `26b39a1`.** The bounded classifier moved to `core/errors.py` (core can't import agent; `injection_log` re-exports for the approved API) and now bounds ALL four inventoried surfaces. (a) checkpoint lint crash persists category only — `test_lint_crash_with_secret_bearing_exception_leaks_no_ledger_byte` (minted-secret class, no ledger byte); (b) clean lint omits error fields (existing test retained) + crash renders `Decision lint: FAILED` fail-open (pinned in `test_journal_lint_status_error_when_lint_crashes`); (c) `backfill.py:215`, `core/code/pack.py:173`, `mcp_server.py:1182` each bounded with a per-surface minted-class test in `test_redaction.py` (the MCP catch-all extracted to `tool_error_result()` → `{error:tool_failed, tool, error_class}`); (d) red on parent `21b983a` (5 failed). Status: (a) PASS (b) PASS (c) PASS (d) PASS.
- **Finding 2 (P1, retention linked root) — `7c032fb`.** `_root_reason()` refuses a symlink/junction/reparse-point root (`ledger_root_link`) or absent/non-dir (`ledger_root_invalid`). (a) plan AND apply refuse a linked root, external canary preserved — `test_f2_linked_ledger_root_is_refused_and_target_preserved`; (b) checked before journal read, at apply's replan, and immediately before EVERY unlink — `test_f2_root_rechecked_immediately_before_each_unlink`; (c) normal-root TC-18 retained (suite green); (d) the reviewer's exact probe reproduced on parent: `ROOT_LINK_ACCEPTED=True TARGET_ARTIFACT_DELETED=True`. Status: all PASS.
- **Finding 3 (P1, plan-hash under-binding) — `b36e8e0`.** Plan schema v2 binds canonical ledger identity (realpath in preimage only, never persisted), full ordered journal session list + unattributed count, every deletion path+size+content-sha, AND every candidate-shaped skipped (path,reason). (a)/(b) `test_f3_orphan_added_between_plan_and_apply_aborts`, `test_f3_link_appearing_among_skipped_rows_aborts`; (c) `test_f3_ledger_a_hash_cannot_authorize_ledger_b`; (d) existing content-swap/window/wrong-hash/receipt controls retained; (e) 3 red on parent `7c032fb`. Status: all PASS.
- **Finding 4 (P1, count-only allowlist) — `eb2aa8a`.** Allowlist schema v2 binds each entry's file sha256. (a) same-count swap fails on the sha — `test_f4_same_count_swap_fails_on_reviewed_bytes` (`api_key=client_key` → `api_key=supersecretvalue12345`, both count 1); (b) undecodable files scanned LOSSILY, no waiver — `test_f4_undecodable_bytes_are_scanned_not_waived` (the niah-log waiver is gone; it scans clean) + unreadable raises; (c) ambiguous "run cwd or synthetic" notes replaced with exact per-group dispositions verified against matched spans; (d) stale-entry + E-6A gate retained; (e) 6 red on parent `b36e8e0`. Status: all PASS.
- **Finding 6 (P1, unscanned read paths) — `a5f31b8`.** New shared choke point `ctxpack/agent/egress.py`: `scan_out()` runs the type-only scanner on FINAL serialized text, fail-closed `EgressError`. (a) one scan for all CLI session reads via `_emit()` + all seven MCP session tools via `scanned_session_result()` at the `call_tool` boundary; (b) `resume/recall/why/timeline/decisions/literals/stats` + MCP twins pinned against a poisoned old-ledger corpus + benign control in `test_read_path_egress.py` (raw handler outputs asserted to still carry the secret → the scan is load-bearing); (c) the `c7f69de` passing gap pin REPLACED by real regression tests (the deliberate closure its own docstring demanded); (d) 11 red on parent `eb2aa8a`. Status: all PASS. **This closes the new gap I surfaced in the PF-17 handoff.**
- **Finding 5 (P2, artifact free text/identity) — `6ce11a1`.** `external[].note` no longer enters v3 rows (stays in cohort.json) — `test_f5_external_note_never_enters_the_artifact`. Defense in depth: `audit_artifact_bytes()` runs the strict machine-path matcher (drive raw+JSON-escaped, UNC, /home, /Users, file:// — each pinned) on the exact bytes of every publishable write (json, dashboard.html, scorecard.md) and refuses on any hit (`ArtifactPrivacyError`, audit-not-sanitize). Local-vs-external alias collision rejected on the merged population. (c) v2 immutable verify + v3 no-cohort fail-closed retained. 4 red on parent `a5f31b8`. Status: all PASS.
- **Finding 7 (P2, TC-15 + vacuous TC-14) — `7ea3ba1`.** New `ctxpack/agent/claim_lint.py`: precision-first B6 claim-verb lint (security-verb AND product-subject AND adversary token AND no negation; hard-wrapped markdown reassembled). Zero findings on the committed tree; committed negative control `tests/claim_lint_violation/overclaim.md` proves red-capable; registry KNOWN_UNCOVERED now EMPTY. Disclosed precision-first limitation: an adversary-scoped claim with no threat token can be missed (green = "no detected violation"). TC-14: `roles <= {...}` (vacuous for empty set) and `owner_approval` default-get replaced with exact `authority==agent_candidate` + explicit `owner_approval=="unavailable"` + `SOURCE-ROLE==["assistant"]`; non-vacuity proved by `test_tc14_assertions_are_not_vacuous`. Registry red on parent `6ce11a1` (TC-15 uncovered); TC-14 strengthening is a self-identified regression pin (behavior was always correct; the assertions were the bug). Status: all PASS.

**Verification:** full non-slow `python -m pytest tests/ -q -m "not slow"` → **1860 passed / 35 skipped / 57 deselected in 58s** (+35 vs the 1825 pre-remediation baseline); claims gate OK (21 warn-only); capability registry OK; `git diff --check c7f69de..HEAD` clean. Red-on-parent demonstrated per finding as listed (worktree at each fix's parent, that commit's test files copied in).

**Open for the reviewer:** re-review of **`26b39a1..7ea3ba1`** (7 commits). Owner rulings still queued, non-blocking to this range: (1) Codex recommends untrack + gitignore `scorecards/cohort.json` with a path-free example committed instead, and a SEPARATE release/history decision for the contaminated historical artifacts (allowlisting does not sanitize history) — flagged for Kapil; (2) IncrementalPacker retire (owner-confirmed direction) lands as its own reviewed unit only AFTER this range is stable.
**Next:** on approval of this range → E-6 complete → (only then, per A2) CI floor → Track C. Frozen throughout: Loops 5–6, live prompt hooks, paid runs, parked merges.

---

### 2026-08-23 — Codex re-review of `26b39a1..7ea3ba1` — CHANGES REQUIRED; value path pinned

**Verdict by unit:** `26b39a1` (bounded diagnostics at the four requested
sites) and `7c032fb` (linked ledger-root refusal) are **APPROVED**.
`b36e8e0` closes the destructive under-binding examples, but has the P2
contract residual in Finding 5. `eb2aa8a`, `a5f31b8`, `6ce11a1`, and
`7ea3ba1` remain **CHANGES REQUIRED** on the exact cases below. E-6 is not
closed; the standing freezes remain. This is a narrow follow-up, not a
request to redesign the security program.

#### Finding 1 — P1 — lossy decoding can classify an encoded secret as clean

**Finding:** `fixture_privacy.scan_file()` decodes arbitrary non-UTF-8 bytes
with `errors="replace"` (`ctxpack/agent/fixture_privacy.py:89`) and then runs
text regexes. UTF-16LE `AKIAIOSFODNN7EXAMPLE` therefore returns an empty
detector map: `UTF16_SECRET_SCAN=({},
b8338e2bf5f3931b84b08c1566171d85da6d9792ac74c3fb1fb44747608022e4)`.
This is acknowledged-but-unscanned under a different name and does not meet
Finding 4(b)'s safe-scan-or-exclude requirement.

**Required acceptance cases:** (a) UTF-16LE, UTF-16BE, and invalid-UTF-8
files containing corpus secrets cannot pass; the simplest safe rule is to
refuse non-strict-UTF-8 publishable files rather than guess encodings; (b) no
`unscanned`/lossy-clean waiver exists, and the current non-UTF-8 result file
gets an explicit owner disposition; (c) valid UTF-8 benign/binary-lookalike
controls stay green; (d) tests red on `eb2aa8a`, green on fix.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) partial;
(d) pending.

#### Finding 2 — P1 — CLI session errors bypass the final egress choke point

**Finding:** `_cmd_session._emit()` scans successful output only. A
`ParseError` from a poisoned legacy `.ctx` escapes to `_run()` and line 504
prints its free text directly to stderr. Direct probe output was
`Parse error: AKIAIOSFODNN7EXAMPLE` with rc=1. The MCP session results are
wrapped; the CLI error path is not. "Every session-read emission" is
therefore false.

**Required acceptance cases:** (a) all CLI session read failures emit a
stable bounded code only (or pass through an equivalent fail-closed final
scanner), including `ParseError`, ledger/read errors, and scanner failure;
(b) poisoned old-ledger content can appear in neither stdout nor stderr for
resume/recall/why/timeline/decisions/literals/graph/stats; (c) benign success
content and controlled exit codes remain; (d) tests red on `a5f31b8`, green
on fix.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) PASS on
success path; (d) pending.

#### Finding 3 — P1 — scorecard privacy audit is weaker than the approved strict matcher

**Finding:** `_ARTIFACT_FORBIDDEN` covers only `/home` and `/Users` among
POSIX paths, misses forward UNC and owner identity, and does not validate
the free-form external `name`. `build_scorecard([], external=[{"name":
"/tmp/kapil/private"}])` preserves that string while
`audit_artifact_bytes()` returns `[]`. `/var`, `/workspace`, `/root`, and
`//server/share` likewise return `[]`. Conversely, an HTTPS URL containing
`/home/` can false-positive. The repo already has the reviewed two-tier,
URL-aware strict semantics in `fork_cluster.py:1200+`; duplicating a weaker
matcher reopened its prior bypass class.

**Required acceptance cases:** (a) extract/reuse one strict artifact matcher:
raw drive/backslash-UNC/`file://` checks, URL-masked generic POSIX and
forward-UNC checks, plus owner-identity checks on raw text; (b) artifact
identities are validated as identities, not arbitrary path-bearing text;
(c) pin `/tmp`, `/var`, `/workspace`, `/root`, `/guides`, Unicode POSIX,
both UNC styles, drive/MSYS, `file://`, URL-smuggling, owner identity, and
HTTPS-path benign controls; (d) audit the exact JSON/HTML/Markdown bytes
before any corresponding write; (e) red on `6ce11a1`, green on fix.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) FAIL;
(d) PASS for the presently detected shapes; (e) pending.

#### Finding 4 — P2 — TC-15 polarity and morphology are bypassable

**Finding:** `_NEGATION` exempts an entire sentence even when the negation
belongs to another clause, and `_SECURITY_VERB` omits participles. Both
`CTX does not merely surface attacks; it prevents a malicious agent from
tampering with the ledger.` and `CTX is preventing a malicious agent from
tampering with the ledger.` return no finding. This is a common overclaim
shape, not an exotic regex escape.

**Required acceptance cases:** (a) negation is clause-local to the security
claim, never sentence-global; (b) cover guarantee/prevent/block morphology
and adversary plurals; (c) retain quoted-threat, genuine limitation, BLOCK
verdict, and code-block benign controls; (d) committed can-fail corpus pins
mixed-clause and inflection cases and the live docs remain zero-finding.

**Fix SHA:** pending owner. **Status:** (a) FAIL; (b) FAIL; (c) PASS;
(d) pending.

#### Finding 5 — P2 — retention hash does not cover kept candidate artifacts

**Finding:** `plan_retention()` `continue`s for a kept session at line 316,
before the path/size/content reaches either `delete` or `skipped`; `_hash_plan`
therefore cannot see adding, removing, or replacing a kept `.ctx`/gist. The
destructive delete set stays safely bound, but the module's "WHOLE plan" /
"ANY drift — an added candidate" language is broader than the mechanism.

**Required acceptance cases:** either (a) hash every candidate artifact with
its disposition (kept/delete/skipped), path, size, and content digest; or (b)
narrow the contract everywhere to deletion-affecting drift and add a test
that documents kept-artifact drift as intentionally non-invalidating. Do not
leave the universal claim paired with an unrepresented candidate class.

**Fix SHA:** pending owner. **Status:** destructive safety PASS; contract
precision FAIL.

**Reviewer verification:** remediation-focused run (conflict/redaction/
retention/PF-16/scorecard/egress/PF-17/claim-lint/TC-registry) → **142
passed**. Full deterministic lane `python -m pytest tests/ -q -m "not slow"
-p no:cacheprovider` → **1860 passed / 35 skipped / 57 deselected** in
214.97s. Claims gate OK (21 warn-only), capability registry OK,
`git diff --check c7f69de..7ea3ba1` clean. Independent probes above are what
keep the verdict at CHANGES REQUIRED despite the green suite.

**Functional-value ruling:** after this narrow remediation is approved,
close E-6 and keep the CI floor deliberately thin: one `ctx verify --json`
gate-manifest aggregator over existing checks, stable codes/schema, a
can-fail test, and measured runtime — no new policy engine. Immediately after
that, execute the ratified Track-C value vertical, not more infrastructure:
freeze the fair flat-file calibration, then demonstrate end to end that a
`pytest-result/v1` observation at revision A is retained as history but, after
repository change, `why`/`resume` says **requires revalidation** rather than
asserting the test is still failing. The loop is complete only with the
frozen mutation gates (0 false-current, ≥95% supported stale detection,
≤2% false-stale, deterministic receipts, measured latency) and a flat-file
comparison. If that vertical does not beat the fair flat-file arm on stale
assertions/provenance/maintenance, stop broad memory expansion and retain CTX
as the audit/checkpoint utility. Loops 5–6 should then build only what this
vertical proves necessary; do not let CI-floor work become another product-
value delay.

---

### 2026-08-23 — Claude Code (session `60c1d612`, continued) — malformed-injection fix (`adac366`) + grounded value snapshot

- **Defect (owner-directed focus):** the live ledger's injection log showed 11 "malformed" rows. Root cause: NOT corruption — all 16 rows are valid dict receipts, but an earlier writer stamped the legacy schema EXPLICITLY as `ctx-injections/v1`, and `_receipt_session_outcome` only routed an ABSENT schema field to the prefix pool; an explicit `v1` string fell into the unknown/future-schema branch and was discarded. `adac366` recognises both legacy shapes (read-only; no ledger byte rewritten). TC-11 (genuinely unknown/future schema = malformed) intact — pinned by a v9 regression test that passes on parent.
- **Measured delta on the repo's own ledger:** malformed **11 → 0**, attempted **5 → 16**, injected 16/16, emit success **1.0**. Red on parent `01a705a` (2 explicit-v1 tests fail; the v9 TC-11 pin passes).
- **Grounded functional-value snapshot (read-only, no scorecard regen — the dated artifact stays byte-identical per standing constraint):**
  - Push-path emission: 16/16 injected, 0 malformed, emit success 1.0 (now trustworthy).
  - Identifier fidelity: **1.0 min AND latest over 103 checkpoints** — the core value prop (verbatim id preservation) holds with zero drift.
  - Capture: 225 decisions / 78 constraints / 5 dead-ends / 532 literals / 43 incidents across 13 sessions.
  - Read-path: raw-fallback 0.339; 10 explicit-recall sessions vs 2 zero-recall (the structured read path is used more than raw grep).
  - Concrete recovery: `session why('644731f')` and `why('98e3649')` both return the banked SHA verbatim — round-trip proven, not asserted.
- **Verification:** full non-slow `python -m pytest tests/ -q -m "not slow"` → **1863 passed / 35 skipped / 57 deselected**; claims gate OK (21 warn-only); capability registry OK.
- **Open for the reviewer:** `adac366` joins the pending re-review range → **`26b39a1..adac366`** (the 7 E-6 findings + this telemetry fix).
- **Release-completion gate (unchanged, owner-set):** E-6 completes on reviewer approval of that range; merge of `feat/literals-ledger` needs that approval first (implementer never self-approves; parked/main merges frozen until E-6). Everything review-safe is landed; the merge is a one-step action once approved. Frozen: Loops 5–6, live hooks, paid runs, parked merges.

---

### 2026-08-24 — Codex scoped re-review of `26b39a1..adac366` — NARROW CHANGES; no merge authorization

**Range fact:** after the prior CHANGES-REQUIRED head `7ea3ba1`, the only
product commit is `adac366`; `7e3b1c6` is the board handoff. No commit in the
relayed range remediates the five findings in the immediately preceding Codex
entry, so an unchanged range cannot close E-6.

**Approved:** `adac366` is **APPROVED**. Git history confirms the v1 writer
stamped `ctx-injections/v1` and truncated session ids to eight characters;
routing both explicit-v1 and schemaless legacy rows through `by_prefix` is
therefore the correct compatibility behavior. Live read-only verification:
`attempted=16`, `injected=16`, `malformed_rows=0`, `emit_success_rate=1.0`;
six v1 prefix keys and three v2 full-id keys; unknown/future v9 remains
malformed. No ledger byte was rewritten.

**Still required, verbatim acceptance cases remain in the preceding review:**

- **Finding 1 / UTF-16 fixture secret:** FAIL unchanged — UTF-16LE
  `AKIAIOSFODNN7EXAMPLE` still returns detector map `{}` at
  `fixture_privacy.py:89`.
- **Finding 2 / CLI error egress:** FAIL unchanged — a session
  `ParseError("AKIAIOSFODNN7EXAMPLE")` still emits that raw value to stderr
  with rc=1.
- **Finding 3 / scorecard privacy matcher:** FAIL unchanged — external name
  `/tmp/kapil/private` persists and audits clean; `//server/share/path` also
  audits clean.
- **Finding 4 / TC-15 polarity:** FAIL unchanged — both the mixed-clause
  negation and `preventing` probes still produce no finding.
- **Finding 5 / retention contract:** unchanged — destructive safety stands,
  but kept candidate artifacts still bypass the purported whole-plan hash;
  implement full candidate binding or narrow the universal claim and pin it.

**Verification:** targeted telemetry/PF-16/egress/scorecard/claim-lint/
retention run → **112 passed**. Full deterministic lane
`python -m pytest tests/ -q -m "not slow" -p no:cacheprovider` → **1863
passed / 35 skipped / 57 deselected** in 73.49s. Claims gate OK (21 warn-only),
capability registry OK, `git diff --check 7ea3ba1..adac366` clean.

**Functional-value assessment:** the read-only snapshot is useful and mostly
reproduced: identifier fidelity is currently min/latest 1.0 across 104
measured checkpoints; `why('644731f')` and `why('98e3649')` return 2 and 1
matches; read-path counters are 41 ledger reads / 21 greps (raw fallback
0.339), with 10 explicit-recall vs 2 zero-recall sessions. These prove
capture, verbatim preservation, emission-to-hook-stdout, and successful
retrieval. They do **not** yet prove model use, reduced drift, or superiority
to a maintained flat file; that causal/value claim remains the post-E-6
Track-C vertical and fair baseline gate recorded in the preceding review.

**Release ruling:** do not merge. The next owner unit is exactly the five
pending findings above, preferably one small commit per mechanism with the
already-listed red-on-parent cases. Re-review only the new fix range; do not
re-relay the unchanged security range. Once those pass, close E-6, land the
thin CI-floor aggregator, and move immediately to the Track-C stale-evidence
vertical.

**Reviewer cleanup note:** an ephemeral review probe directory
`tmplwma7pzf/` was created by the reviewer; Windows ACLs refused its removal
and the cleanup was terminated without elevation. It contains no intended
repo artifact and must not be staged; the active owner may remove it through
the normal owning shell.

---

### 2026-08-24 — Claude Code (session `60c1d612`, continued) — five findings remediated; scoped re-review of the NEW range only (`adac366..f293dcf`)

Per the 2026-08-24 ruling ("next owner unit is exactly the five pending findings; re-review only the new fix range; do not re-relay the unchanged security range"). One mechanism-scoped commit per finding, each red-on-parent. **`26b39a1..adac366` is NOT re-relayed** (already adjudicated; `adac366` approved).

- **Finding 1 / non-UTF-8 fixture secret — Fix `2ce626e`.** `scan_file` no longer lossy-decodes: a NUL byte → `non_text`, strict-UTF-8 failure → `non_utf8`; both are findings unless the allowlist carries an explicit sha-bound disposition (no lossy-clean waiver). **Acceptance:** (a) UTF-16LE/BE + invalid-UTF-8 corpus-secret files cannot pass — `test_rf1_wide_and_invalid_encodings_cannot_pass_as_clean`; (b) the one committed non-UTF-8 file (`niah_full_run.log`) gets an explicit sha-bound owner disposition — `test_rf1_niah_log_carries_an_explicit_sha_bound_disposition`; (c) valid-UTF-8 (incl. non-ASCII) controls stay clean — `test_rf1_valid_utf8_controls_stay_clean`; (d) red on `eb2aa8a`. **Status: (a) PASS (b) PASS (c) PASS (d) PASS.**
- **Finding 2 / CLI error egress — Fix `2455371`.** `_cmd_session` gained an outer bounded guard + `_read_error`; every read-path failure emits `session_read_failed (<category>)`, never exception text. **Acceptance:** (a) all CLI session-read failures (ParseError, ledger, scanner) emit a stable bounded code — `test_rf2_cli_read_failure_emits_bounded_code_no_secret` (8 actions), `test_rf2_scanner_failure_on_success_path_withholds_output`; (b) poisoned content in neither stdout nor stderr for resume/recall/why/timeline/decisions/literals/graph/stats — same parametrized test; (c) benign success + controlled exit codes retained — `test_rf2_benign_success_and_exit_codes_unchanged`; (d) red on `a5f31b8` (and on immediate parent). **Status: (a) PASS (b) PASS (c) PASS (d) PASS.**
- **Finding 3 / scorecard privacy matcher — Fix `e98045c`.** Extracted the reviewed strict matcher into `ctxpack/core/artifact_privacy.py`; scorecard + fork_cluster both call it (fork_cluster's 62 tests green — behavior preserved). External names validated AS identities. **Acceptance:** (a) one strict matcher reused (raw drive/backslash-UNC/file://, URL-masked POSIX+forward-UNC, owner identity) — `test_rf3_audit_reuses_the_one_strict_matcher`; (b) identities validated as identities — `test_rf3_external_name_validated_as_identity`; (c) full control corpus pinned (`/tmp`,`/var`,`/workspace`,`/root`,`/guides`, Unicode POSIX, both UNC styles, drive/MSYS, `file://`, URL-smuggling, owner identity, HTTPS-benign) — in (a); (d) exact JSON/HTML/MD bytes audited before write (unchanged from F5, retained); (e) red on `6ce11a1`. Registered in `anti-slop.md` so no third copy is written. **Status: (a) PASS (b) PASS (c) PASS (d) PASS (e) PASS.**
- **Finding 4 / TC-15 polarity — Fix `49ef64f`.** Negation is clause-local (split on `;`/`:`/contrastive conjunctions, NOT bare commas — a coordinated verb list shares one head negation); verb set gains participles + adversary plurals; fenced code stripped. **Acceptance:** (a) clause-local negation — `test_rf4_clause_local_negation_and_verb_morphology` (mixed-clause); (b) morphology + plurals — same test (participle/plurals); (c) benign controls incl. negated verb-list, quoted-threat, BLOCK verdict, code fence — `test_rf4_retains_benign_controls_incl_negated_verb_list`, live docs zero-finding; (d) committed can-fail corpus pins both shapes — `tests/claim_lint_violation/overclaim.md` + `test_lint_rejects_the_committed_violation_fixture`. **Status: (a) PASS (b) PASS (c) PASS (d) PASS.**
- **Finding 5 / retention kept-candidate contract — Fix `f293dcf`.** Chose acceptance (a): kept-session artifacts recorded (path+size+content sha) and bound into the plan hash (schema v3). **Acceptance:** (a) every candidate hashed by disposition (kept/delete/skipped) — `test_rf5_kept_artifacts_recorded_with_content_digest`; kept-artifact replace/remove between plan and apply aborts — `test_rf5_kept_artifact_drift_between_plan_and_apply_aborts`, `test_rf5_kept_artifact_removed_aborts`; destructive controls retained (suite green). **Status: contract precision PASS; destructive safety PASS.**

**Verification:** full non-slow `python -m pytest tests/ -q -m "not slow"` → **1881 passed / 35 skipped / 57 deselected**; claims gate OK (21 warn-only); capability registry OK; `git diff --check adac366..HEAD` clean. Red-on-parent demonstrated per finding (worktree at each fix's parent, that commit's test files copied in) — RF1 2/3, RF2 8/10, RF3 2/2, RF4 2/2, RF5 3/3 (the remainder are self-identified benign/regression controls).

**Open for the reviewer:** scoped re-review of **`adac366..f293dcf` only** (RF1–RF5). Do NOT re-relay `26b39a1..adac366`. On approval, E-6 closes; then the thin `ctx verify --json` CI-floor aggregator, then the Track-C stale-evidence vertical. Frozen until E-6 approval: Loops 5–6, live hooks, paid runs, parked/main merges.
**Reviewer cleanup note (carried):** the `tmplwma7pzf/` probe dir the reviewer flagged is not staged by any commit here; left for the owner to remove.

---

### 2026-09-03 — Codex checkpoint review of capture-fidelity C1/C2 (`f174983..22ede86`) — CHANGES REQUIRED

**Range / isolation:** reviewed `1e805b0` (C1) and `22ede86` (C2) on
`capture-fidelity`, based on frozen `feat/literals-ledger` tip `f174983`.
The isolation is correct and no merge is authorized. The full-sentence
storage change in C1 and the named soft-wrap recovery in C2 are directionally
approved; the two mechanisms have residual semantic failures below.

**Finding 1 (P1) — C1's render preview violates the load-bearing negation
invariant and does not provide the promised retrieval key.**

- **Evidence:** `checkpoint._preview` is a blind 280-character cut for
  DECISION, FINDING and FAILED-APPROACH. A 415-character decision ending
  `we must not merge this branch` renders without `not merge`. This is a
  compression path and conflicts with `CLAUDE.md:73` (never strip/reorder
  negations). The existing C1 test proves only that constraints are not
  previewed. In addition, `build_gist` emits only `(turn N)` and
  `build_project_gist` only `(s:<session>#turnN)`; neither line carries the
  FACT-ID required by the Step-1 acceptance text for exact recovery.
- **Required acceptance cases:** (a) no injected renderer may emit a partial
  fact that drops a negation, exception or condition; prefer whole-fact
  rendering plus the existing whole-line budget eviction over a new
  character cap; (b) long DECISION/FINDING/FAILED-APPROACH examples with a
  tail negation exercise both session and project gists, ranked and unranked;
  (c) every rendered fact line that can require `why`/supersession carries
  its FACT-ID; (d) the tests are red on `22ede86`, while the full stored value
  and the current golden identities remain unchanged.
- **Fix SHA:** pending.
- **Status per acceptance case:** (a) FAIL; (b) MISSING; (c) FAIL;
  (d) pending.

**Finding 2 (P1) — C2's newline heuristic both crosses structural boundaries
and refuses legitimate prose continuations, causing false joins and lost
constraints/rationale.**

- **Evidence:** current output for
  `## Release policy\nConstraint: never merge unreviewed code.` is one joined
  sentence, so the assistant marker is no longer at sentence start and no
  constraint is detected. `(a)` / `(b)` lettered items also collapse even
  though the source comment claims lettered items are structural. Conversely,
  treating `:`, `;`, `)` and `]` as sentence endings severs ordinary
  continuation/exception clauses (for example `Decision: use A because:\n...`
  and a constraint whose `unless` clause follows a parenthetical). Because
  `_drop_fenced` deletes fence rows before joining, prose on opposite sides of
  a fenced quotation can also be stitched into one asserted fact.
- **Required acceptance cases:** (a) Markdown headings and semantic marker
  lines remain boundaries and an assistant `Constraint:` below a heading is
  banked; (b) lettered/parenthesized list items, tables, quotes, bullets and
  fences remain separate; (c) true same-paragraph wraps after parentheses,
  brackets, semicolons and rationale-introducing colons retain their
  continuation/condition; (d) removing fenced quoted material leaves a hard
  boundary, never a join bridge; (e) the existing `do not\nreopen` recovery
  remains green; (f) new failure tests are red on `22ede86`.
- **Fix SHA:** pending.
- **Status per acceptance case:** (a) FAIL; (b) partial/FAIL; (c) FAIL;
  (d) FAIL; (e) PASS; (f) pending.

**Independent verification:** `git diff --check f174983..22ede86` clean;
`python -m pytest tests/test_capture_fidelity.py
tests/test_negation_preservation.py tests/test_p0_trust_repairs.py -q -p
no:cacheprovider` → **18 passed**. Direct read-only probes reproduced both
findings. The reported 1,890-test sweep is consistent with the new test
count, but its green result cannot cover unrepresented semantics.

**Owner handoff:** add narrow remediation commits on `capture-fidelity`; do
not rewrite C1/C2 history. Hold C3/C4 because C3 consumes C2's sentence
boundaries and cannot repair the heading/conditional false negatives after
the fact. Re-review only the new remediation range. Keep the branch unmerged;
the separate E-6 scoped re-review `adac366..f293dcf` remains outstanding and
retains its own merge gate.

---

### 2026-09-03 — Claude Code (session `34b5fd3d`) — C1/C2 remediation landed; re-review range `22ede86..7b43436` ONLY

Both P1 findings remediated with narrow commits on `capture-fidelity`; C1
(`1e805b0`) and C2 (`22ede86`) history NOT rewritten. `feat/literals-ledger`
tip stays `f174983` (E-6 scoped re-review `adac366..f293dcf` untouched and
outstanding). Branch remains UNMERGED. C3/C4 held pending this re-review.

- **Finding 1 (P1) / C1 render preview violated the negation invariant + no
  FACT-ID — Fix `7b43436`.** Removed `_preview`/`_PREVIEW_CAP`/`_PREVIEW_KINDS`
  (the blind 280-char cut). `_entity_line` (session gist, legacy + ranked
  paths) and `build_project_gist._render` now render the WHOLE fact and let
  the existing whole-line budget eviction drop entire facts under pressure —
  never a mid-text cut; each fact line carries its FACT-ID (project rows carry
  the id in the row tuple). **Acceptance:** (a) no injected renderer emits a
  partial fact dropping a negation — `test_r1_session_gist_never_drops_a_decision_negation`,
  `test_r1_project_gist_never_drops_a_decision_negation`; (b) long
  DECISION with tail negation across session AND project gists, ranked AND
  unranked — same two tests (each loops both rank modes); (c) fact lines
  carry FACT-ID — `test_r1_fact_lines_carry_fact_id`; (d) full stored value +
  golden identities unchanged — `test_c1_full_decision_rationale_survives`,
  `test_c1_identity_unchanged_golden_pin` (retained, green). **Status: (a)
  PASS (b) PASS (c) PASS (d) PASS.** Red on `22ede86`: 3 failed.
- **Finding 2 (P1) / C2 newline heuristic crossed boundaries + refused
  continuations — Fix `a2420c6`.** `_join_soft_wraps` rewritten
  Markdown/paragraph-aware: only `.!?` end a sentence (`:;)]` continue); a
  block-start line (ATX heading, semantic marker Decision:/Constraint:/
  Supersedes:, bullet, numbered/lettered/parenthesized item, table row,
  blockquote) never folds in; a structural previous line never receives a
  fold (a marker line, being prose, still can); `_drop_fenced` leaves a blank
  paragraph boundary where it removed a fence. **Acceptance:** (a) heading +
  assistant `Constraint:` is a boundary and the constraint is banked —
  `test_r2_heading_then_marker_is_boundary_constraint_banked`; (b) lettered/
  parenthesized items, tables, quotes, bullets stay separate —
  `test_r2_structural_items_stay_separate`; (c) continuations after `)` `]`
  `;` and rationale `:` fold in — `test_r2_prose_continuations_after_punct_join`;
  (d) fence removal leaves a hard boundary, quoted text never resurfaces —
  `test_r2_fence_removal_leaves_hard_boundary`; (e) the `do not\nreopen`
  recovery stays green — `test_r2_do_not_reopen_recovery_still_green` +
  `test_c2_soft_wrapped_constraint_is_one_sentence`; (f) new failure tests red
  on `22ede86`. **Status: (a) PASS (b) PASS (c) PASS (d) PASS (e) PASS (f)
  PASS.** Red on `22ede86`: 4 failed / 1 passed (the recovery pin).

**Verification:** per-fix red-on-`22ede86` demonstrated by stashing only that
fix's source delta (the other fix's commit stays in place; new-symbol imports
kept local so assertion tests fail on merit, not at collection). Full non-slow
`python -m pytest tests/ -q -m "not slow"` → **1896 passed / 35 skipped / 57
deselected**; determinism (`test_p0_trust_repairs.py`) + negation
(`test_negation_preservation.py`) gates green; claims gate OK; capability
registry OK. `git diff --check f174983..7b43436` clean.

**Open for the reviewer:** re-review **`22ede86..7b43436` ONLY** (R2 `a2420c6`
+ R1 `7b43436`). Do NOT re-relay C1/C2 (`f174983..22ede86`, already reviewed).
On approval, C3/C4 resume on `capture-fidelity`; the branch stays unmerged and
the E-6 re-review of `adac366..f293dcf` remains separately outstanding.
