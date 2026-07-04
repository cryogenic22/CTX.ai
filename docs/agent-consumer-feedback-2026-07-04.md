# Feedback to the CtxPack dev team — from an agent consumer

*Written 2026-07-04 by a Claude Code agent that (a) dogfooded ctxpack session
memory on a long, multi-agent session and (b) implemented the literals ledger
(`feat/literals-ledger`). These are concrete features that would make the module
materially more useful **to an agent consumer** — ranked by the friction I
actually hit, with the observed evidence.*

## P0 — highest leverage

### 1. `ctx_why` must rank EXACT matches above substring hits
**Observed:** `ctx_why "0308e87"` (a commit sha that IS a clean `LITERAL`
entity) returned a huge serialized blob, because the sha also appears as a
substring inside a `TOOL-BASH` `COMMAND` field and `session_why`'s match order
(`section_name → field_key → value_substring`) hit that command entity first.
The clean `ENTITY-LITERAL VALUE:0308e87 KIND:git_sha TURN:763` answer was buried.
**Ask:** add an **exact-value tier** to the match order — an entity whose `VALUE`
field *equals* the needle (i.e. a LITERAL) should win over any substring hit —
and **scope/paginate** the returned field text so one bash-command value can't
dump kilobytes. This is *the* read path an agent uses to recover an exact id;
noise defeats the whole point of the literals ledger.

### 2. An MCP `ctx_checkpoint` write tool (agent-invokable)
**Observed:** to bank the ledger mid-session I had to shell out with
`PYTHONSAFEPATH=1 PYTHONPATH=<repo> python -P -m ctxpack.cli.main checkpoint
--transcript <path>` — brittle (must pick the right transcript, the right
ctxpack build, the right cwd for `.claude/ctx`). The MCP server already knows
its ledger dir and can resolve the live transcript.
**Ask:** expose a `ctx_checkpoint` MCP tool that checkpoints the current session
in one call. This makes "dual-write memory before `/clear`" a single agent
action instead of a shell incantation — and makes the checkpoint-before-clear
convention reliable for every team, not just those who remember the CLI flags.

## P1 — strong resume affordances

### 3. `ctx_resume` — the one-call "first thing to read on resume"
Today an agent resuming chains `recall` → `decisions` → `why`. Give it one tool
that returns **gist + latest decisions + constraints + literals** together. The
onboarding says "the gist is already injected", but after a `/clear` where
injection didn't land (or mid-session), an agent wants to *pull* it on demand.

### 4. Bulk literals read: `ctx_literals` (or `--kind LITERAL` on timeline)
With the literals ledger, the natural resume question is "give me **every exact
id** banked" (commit shas, PRs, versions, paths, domain ids) so I write correct
identifiers instead of reconstructing them. `why` is per-id; a bulk view is the
missing complement. (`session_timeline` already supports `kinds=` — surfacing
`LITERAL` there + a thin CLI/MCP alias would cover it.)

### 5. Capture key SUBAGENT / workflow verdicts as decisions
**Observed:** my sessions run large multi-agent workflows (a 58-agent audit; two
adversarial review agents returning `APPROVE_WITH_NITS`; a `BLOCK` verdict).
These verdicts are load-bearing decisions, but they arrive as subagent results
and/or are `isSidechain`-filtered, so they **don't bank**. For agent-heavy
sessions this is the highest-value memory being dropped.
**Ask:** an opt-in path to capture a subagent's final verdict (e.g. a review
`VERDICT: …`, a workflow's returned summary) as a `DECISION`/`FINDING` with
provenance — either by not filtering the final line of a sidechain, or a
`Finding:`/`Verdict:` marker convention mirroring `Decision:`.

## P2 — completeness & trust

### 6. Cross-session `why` + identifier continuity
The ledger is per-session; a `/clear` breaks the chain. Let `why` trace a value
or id **across sessions** (its revision chain spanning the boundary) so "where
did commit X / decision Y originate" survives a resume. The literals ledger
makes this especially valuable — an id minted in session A should be traceable
from session B.

### 7. Surface the identifier-fidelity axis in `ctx session stats`
`raw_fallback_rate` tells you *recall*; it says nothing about whether the ledger
**corrupted an id**. Now that `captured.literals` exists and the
identifier-fidelity-across-fold benchmark axis is in the test suite, expose a
periodic fidelity number in `session stats` — that's the honest "the ledger is
lossless for ids" signal, complementary to fallback rate.

### 8. A `Constraint:` marker for agent-stated operating rules
**Observed (owner's own note):** a 607-turn seed yielded 9 decisions but **0
constraints** — constraints only extract from clearly-phrased *user* imperatives.
But in agent-driven sessions the load-bearing constraints are often stated by the
*agent* (conservation rules, DoD, review gates, "do not merge until reviewed").
Consider an opt-in `Constraint:` sentence-leading marker (mirroring `Decision:`)
so an agent can bank its own operating constraints deterministically.

---

**Net:** the substrate is excellent — deterministic, verbatim, provenance-to-turn,
zero-dep, and now identifier-faithful. The gaps are all on the **agent read/write
ergonomics**: make `why` return the clean literal (1), let the agent checkpoint
in one MCP call (2), give it a one-call resume + a bulk literals view (3,4), and
stop dropping the verdicts that multi-agent sessions produce (5). Those five turn
"a great ledger" into "the thing an agent reaches for first on every resume."
