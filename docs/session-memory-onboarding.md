# CtxPack Session Memory — Team Onboarding

*Share this doc with any repo team (Scriptiva, analytics, pharma, …) that
wants durable, auditable session memory for Claude Code.*

## What you get

**"Compaction is a commit, not a loss event."** Every compaction and
session end, a hook deterministically packs your Claude Code session
transcript into a ledger at `.claude/ctx/` — decisions, constraints,
failed approaches, errors, files changed, tasks, and **exact identifiers**
(commit SHAs, PR numbers, UUIDs, versions, file paths, domain ids —
verbatim), each with turn-level provenance. Every session start re-injects
a compact gist (~2K tokens) of the previous session. Mid-session, the agent
can query the ledger instead of re-deriving or grepping megabytes of
transcript.

**Identifier fidelity across folds.** The literals ledger is why an exact
id survives a compaction: `508e5733-…`, `b1dda66`, `#305`, `v0.5.0`,
`services/llm.py:42` are extracted verbatim (never truncated or
paraphrased) so a resumed session writes the *correct* id from the gist
rather than reconstructing a plausible-but-wrong one. `ctxpack session why
"<id>"` resolves any of them to its origin turn.

Why this beats the alternatives you already have:

| | Native compaction | Claude auto-memory | CtxPack ledger |
|---|---|---|---|
| Deterministic (no LLM rewrites your memory) | ✗ | ✗ | ✓ |
| Versioned with the repo (PR-reviewable, branch-scoped) | ✗ | ✗ (machine-local) | ✓ |
| Provenance to the exact turn | ✗ | ✗ | ✓ |
| Survives `/clear` and machine switches | ✗ | partially | ✓ |

The raw transcript is never deleted — the ledger is a lossless-by-
construction index over it, not a replacement.

## Setup (one command + one restart)

Prerequisite: `ctxpack` importable (`pip install -e <path-to-CTX_mod>`;
already true machine-wide on shared dev machines).

```bash
cd your-repo
python -m ctxpack.cli.main onboard
```

This idempotently wires four things:

1. **Hooks** into `.claude/settings.json` — PreCompact / SessionStart /
   SessionEnd / Stop run the checkpoint engine (fail-open: a broken
   ledger never breaks your session). The **Stop hook checkpoints every
   ~10 turns** (debounced; `CTXPACK_STOP_DEBOUNCE_TURNS` to tune), so
   even a hard crash — VS Code killed, power loss — costs at most a few
   turns of ledger staleness, recoverable from the raw transcript.
2. **MCP server** into `.mcp.json` — the read-path tools
   (`ctx/resume`, `ctx/session_recall`, `ctx/session_timeline`,
   `ctx/session_decisions`, `ctx/session_literals`, `ctx/why`,
   `ctx/graph_query`), the agent-invokable write path (`ctx/checkpoint`),
   plus the doc/code packer tools.
3. **CLAUDE.md conventions** (marker-guarded, versioned block) — tells
   every session to state decisions as `Decision: ...` lines (and its own
   operating rules as `Constraint: ...`) and to use the ledger read path
   before grepping the transcript.
4. **`.claude/ctx/` ledger dir** — commit it to git if you want the
   memory shared across machines and reviewable in PRs (recommended).

Then **restart Claude Code in that repo** and approve the hooks + MCP
server when prompted. This step is not optional: Claude Code snapshots
hook/MCP config at process startup, so until you restart, nothing fires
(`/clear` is not a restart).

**Already onboarded before?** Re-run `ctxpack onboard` after ctxpack
upgrades — it's idempotent: it picks up new hook entries (e.g. the Stop
hook) and **refreshes an older CLAUDE.md conventions block in place**
(the block is versioned; v1 repos taught agents a read path missing
`resume`/`literals`/`checkpoint`). Improvements *inside* existing hooks
and MCP tools arrive with the package upgrade automatically.

### Multi-day memory: the project gist

`latest-gist.md` covers the last session; **`project-gist.md`** rolls up
decisions, constraints, and failed approaches across *all* earlier
sessions (deduplicated, oldest first, each tagged `s:<session>#turn<n>`).
Both are injected automatically at session start once the repo has more
than one checkpointed session — so a brand-new agent (a frontend
specialist, a teammate, a fresh machine after a crash) starts with the
project's accumulated decisions, not just yesterday's.

## How to get max power

- **State decisions explicitly.** The parser extracts *structured*
  signals deterministically. `Decision: use X because Y` at the start of
  a sentence is extracted with turn provenance; the same content buried
  in prose is often missed (measured: ~0 recall on free prose, 100% on
  the convention). Same for dead ends: "The X approach didn't work
  because ...".
- **Constraints live in user messages.** When you (the human) type "do
  not touch the auth service", that's extracted verbatim as a CONSTRAINT
  — negations are never compressed away (CI-gated).
- **Resume with the ledger, not your memory.** New session? The gist is
  already injected. Need more? `ctxpack session resume` (or MCP
  `ctx/resume`) returns gist + decisions + constraints + failed
  approaches + every exact identifier in one call;
  `ctxpack session why "<value>"` traces where a value came from and its
  revision chain; `ctxpack session literals` lists every banked id so you
  write shas/versions/paths verbatim instead of reconstructing them;
  `--session <id>` reaches older sessions.
- **Agents can state constraints too.** A sentence-leading
  `Constraint: ...` in an assistant reply banks as a CONSTRAINT with turn
  provenance — use it for operating rules the agent sets for itself
  (review gates, immutability rules, "do not merge until X").
- **Commit `.claude/ctx/`.** That's what makes memory branch-scoped,
  cross-machine, and reviewable — the properties nothing native has.
- **Checkpoint before you `/clear` — every team, every session.** The
  Stop hook keeps the ledger within ~10 turns of live automatically, but
  banking explicitly before you wrap costs nothing and guarantees zero gap:
  the agent calls the `ctx/checkpoint` MCP tool, or anyone runs bare
  `ctxpack checkpoint` — both auto-resolve the live transcript under
  `~/.claude/projects/<project>/` (pass `--transcript` only to override).
  Pair it with whatever curated
  notes your repo keeps (e.g. a `CLAUDE.md` / memory file): the curated notes
  are the *narrative*, the ctx ledger is the deterministic *receipts* layer
  (decisions, constraints, failed approaches, verbatim identifiers — every one
  with turn provenance). This is a shared convention, not one person's habit —
  any teammate resuming your branch reads the same gist.

## How we measure whether it's working (built-in)

Telemetry is automatic and deterministic — it's computed from the
transcript itself at checkpoint time and accumulates in
`.claude/ctx/checkpoints.jsonl`. Pull the report anytime:

```bash
ctxpack session stats
```

Key metrics and how to read them:

- **`read_path.raw_fallback_rate`** — of all attempts to recall
  past-session detail, what fraction fell back to grepping the raw
  transcript instead of using the ledger? **This is the honest
  value signal**: trending to 0 means the ledger answers the questions
  agents actually have; staying high means the format adds nothing over
  a file-retention convention (and we want to know that).
- **`captured.decisions` / `captured.constraints`** — how much
  load-bearing state each session banks. If decisions ≈ 0, the team
  isn't using the `Decision:` convention — fix the habit, not the tool.
  **`captured.literals`** counts the exact identifiers banked (auto-extracted,
  no convention needed) — the raw material for identifier fidelity across folds.
- **`gist_bpe` vs `turns_packed`** — what a session costs to resume
  (~2K tokens) vs what it contains (hundreds of turns). The compression
  is the point: resuming from a gist is ~100x cheaper than re-reading
  the transcript.
- **`checkpoint_latency_ms`** — should stay well under 5s; it's the tax
  on every compaction.

### The two-week protocol (per repo)

1. Onboard, work normally for 2 weeks.
2. Run `ctxpack session stats`; record fallback rate + capture counts.
3. Run the **resume probe**: in a fresh session, ask "what did we decide
   about <topic from last week> and why?" — grade whether the answer
   cites the ledger (turn provenance) or hallucinates/greps. Do the same
   in a repo *without* the ledger for the baseline.
4. Send the stats JSON + probe results back to the CTX team.

### The full measurement stack (central — your repo does nothing extra)

| Layer | Instrument | Claim it supports |
|---|---|---|
| 1 · observational | `ctxpack scorecard` — cross-repo rollup of every ledger's telemetry + static HTML dashboard | adoption, token economics |
| 2 · quasi-experimental | `run_resume_probe.py` — fresh-session recall of your repo's own history under budget-parity arms (CTX vs grep-over-transcript vs closed-book), rule-based grading | recall accuracy per repo |
| 3 · controlled | CompactBench — decision recall across K forced compaction cycles, 6 arms, pre-registered (`ctxpack/benchmarks/compactbench/PREREGISTRATION.md`) | causal, benchmark-grade |

Repo teams only work normally and commit `.claude/ctx/`; the CTX team
runs the instruments centrally.

## Troubleshooting

- **"Compaction blocked by PreCompact hook … invalid choice: 'hook'"** →
  the repo resolved a stale/vendored ctxpack copy (a `ctxpack/` dir in
  the repo root shadows the installed package under `python -m`).
  Fix: re-run `ctxpack onboard` — hook commands now use `python -P`
  (safe path), and hook invocations are fail-open (they can no longer
  exit non-zero, so nothing can block compaction again).
- **Gist never appears at session start** → you didn't restart Claude
  Code after onboarding, or didn't approve the hooks (`/hooks` menu).
- **`ctxpack session ...` says no ledger** → no checkpoint has run yet.
  Force one: `ctxpack checkpoint --transcript <path-to-session.jsonl>`
  (transcripts live under `~/.claude/projects/<project>/`).
- **MCP tools missing** → check `.mcp.json` exists and the server was
  approved; the CLI twins work regardless.
- **Something broke mid-session?** The hooks are fail-open by design —
  they can never block or break your session. Worst case you lose a
  checkpoint, never work.
- **Uninstall** — delete the three ctxpack entries from
  `.claude/settings.json`, the `ctxpack` entry from `.mcp.json`, and the
  marked block from `CLAUDE.md`. The ledger dir is yours to keep.
