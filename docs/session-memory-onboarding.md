# CtxPack Session Memory: Team Onboarding

*Share this doc with any repo team (Scriptiva, analytics, pharma, …) that
wants durable, auditable session memory for Claude Code.*

## What you get

On compaction and on session end, a hook packs the Claude Code session
transcript into a ledger at `.claude/ctx/`. The packer stores decisions,
constraints, failed approaches, errors, files changed, tasks, and exact
identifiers (commit SHAs, PR numbers, UUIDs, versions, file paths, domain
ids), each with turn-level provenance. A decision or constraint from the
assistant is stored when the line starts with `Decision:` or `Constraint:`.
Unmarked prose is not the capture contract. Session start re-injects the
budgeted brief from `ctxpack.agent.brief` (the same text as `ctxpack brief`
and MCP `ctx/brief`). It does not inject the gist files themselves. The
agent can also query the ledger during the session. This page does not
claim that the ledger uses fewer tokens than the transcript, or that it
recalls more than grep.

**Identifier fidelity across folds.** The literals ledger keeps an exact
id through packing. Values such as `508e5733-…`, `b1dda66`, `#305`,
`v0.5.0`, and `services/llm.py:42` are stored verbatim. They are not
truncated or paraphrased. `ctxpack session why "<id>"` resolves one of
them to its origin turn. This page does not claim that the model will
copy the id correctly.

The ledger is written without a model call. You can commit `.claude/ctx/`
with the repo and read each fact back to a turn. That is a difference in
mechanism from native compaction and from Claude auto-memory. It is not a
recall result, and it is not a claim that the ledger replaces grep.

The checkpoint does not delete the transcript. The ledger stores extracted
facts, not a copy of every line.

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
2. **MCP server** into `.mcp.json` — the **default agent surface is
   five operations**: `ctx/resume`, `ctx/session_recall`, `ctx/why`,
   `ctx/session_literals`, and the agent-invokable write path
   `ctx/checkpoint`. Advanced tools (`ctx/session_timeline`,
   `ctx/session_decisions`, `ctx/graph_query`) and the doc/code packer
   tools are there when the five defaults aren't enough.
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

### Multi-day memory

Checkpoint still writes `latest-gist.md` and `project-gist.md` as ledger
artifacts. Session start does not inject those files. It injects the
budgeted brief composed by `ctxpack.agent.brief` from the live set
(`ctxpack.agent.live_set`). Superseded and retracted facts leave that
set and stay in the ledger. A fact is stale only when every milestone
scope in its text is in `done_milestones`. An empty list drops nothing
for staleness. The brief can still name a replacement
or a withdrawal. It does not restate the old fact as the current decision.

## Habits the parser reads

- **State decisions explicitly.** A sentence-leading `Decision: use X because Y`
  is extracted with turn provenance. The same content with no marker is
  not part of the capture contract. Dead ends use the same kind of
  explicit line (`Rejected:` or `Dead end:`).
- **Constraints live in user messages.** When you (the human) type "do
  not touch the auth service", that's extracted verbatim as a CONSTRAINT
  — negations are never compressed away (CI-gated).
- **Resume with the ledger, not your memory.** New session? The SessionStart
  hook injects `ctxpack brief` (default 12000 characters). The same text
  is `ctxpack brief`, `ctxpack.brief()`, and MCP `ctx/brief`. Order is
  conflicts and changed choices, open constraints, decisions, dead ends,
  plan progress when `plan.md` or `plan.json` is in the ledger, then file
  names. A fact that does not fit is omitted whole, and the last line
  names how many of each kind were omitted. Set `[brief]` `budget`,
  `unit` (`chars` or `tokens`), and `priority` in `ctxpack.toml`.
  `ctxpack brief --ack` adds a `CTX-Ack:` line to echo back;
  `ctxpack ack check --token T` reports whether a later transcript turn
  or commit body contains it. Need the full ledger? `ctxpack session resume` (or MCP
  `ctx/resume`) returns the brief plus decisions, constraints, failed
  approaches, and every exact identifier in one call;
  `ctxpack session why "<value>"` traces where a value came from and its
  revision chain; `ctxpack session literals` lists every banked id so you
  write shas/versions/paths verbatim instead of reconstructing them;
  `--session <id>` reaches older sessions.
- **Agents can state constraints too.** A sentence-leading
  `Constraint: ...` in an assistant reply banks as a CONSTRAINT with turn
  provenance — use it for operating rules the agent sets for itself
  (review gates, immutability rules, "do not merge until X").
- **Revising a prior decision? Declare it with `Supersedes:`.** When a new
  `Decision:` knowingly changes a banked fact, follow it with a
  sentence-leading `Supersedes: <fact_id> — <reason>` line (recover the id
  via `ctxpack session why "<value>"`). `session why` then reports that
  fact's supersession state — current vs superseded, what it supersedes or
  is superseded by, and an unresolved **fork** when two decisions
  independently replaced the same fact. Operational status today: the
  supersession DAG is **dormant until this convention is used** (a fresh
  repo has zero edges); the producer records **one superseded target per
  decision**, so parallel-session **forks** are real but **diamonds** (one
  decision reconciling two) are synthetic-test-only; gist surfacing and
  top-of-gist conflict warnings stay gated until real ledgers produce edges.
- **Commit `.claude/ctx/`.** A committed ledger is what other clones of
  the branch can read.
- **Checkpoint before you `/clear`.** The Stop hook packs again after the
  transcript grows by the debounce interval (default 10 turns,
  `STOP_DEBOUNCE_TURNS_DEFAULT` in `ctxpack/agent/checkpoint.py`). It does
  not close that gap to zero. To pack the current transcript now, call MCP
  `ctx/checkpoint`, or run `ctxpack checkpoint`. Both resolve the live
  transcript under `~/.claude/projects/<project>/` unless you pass
  `--transcript`. Pair that with whatever curated notes the repo already
  keeps, such as `CLAUDE.md`. The notes are narrative. The ledger is the
  extracted facts, each with turn provenance. A teammate who resumes the
  branch reads the brief built from that ledger, not a promise that the
  gist file itself was injected.

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
- **`gist_bpe`** and **`turns_packed`** are fields on the checkpoint
  journal. This page does not turn them into a token-savings figure.
- **`checkpoint_latency_ms`** is recorded on the same journal. This page
  does not state a latency bound.

### The two-week protocol (per repo)

1. Onboard, work normally for 2 weeks.
2. Run `ctxpack session stats`; record fallback rate + capture counts.
3. Run the **resume probe**: in a fresh session, ask "what did we decide
   about <topic from last week> and why?" — grade whether the answer
   cites the ledger (turn provenance) or hallucinates/greps. Do the same
   in a repo *without* the ledger for the baseline.
4. Send the stats JSON + probe results back to the CTX team.

### The full measurement stack (central — your repo does nothing extra)

| Layer | Instrument | What it records |
|---|---|---|
| 1 · observational | `ctxpack scorecard` rolls up ledger telemetry and writes a static HTML page | adoption counters already on the ledger |
| 2 · quasi-experimental | `run_resume_probe.py` recalls a repo's own history under budget-parity arms (CTX, grep over the transcript, closed book), with rule-based grading | a per-repo recall run, when someone runs it |
| 3 · controlled | CompactBench: decision recall across K forced compaction cycles, 6 arms, pre-registered (`ctxpack/benchmarks/compactbench/PREREGISTRATION.md`) | a pre-registered experiment, not a result quoted here |

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
