# CtxPack

**Deterministic session memory for long-running agents — and a
zero-dependency knowledge packer with progressive hydration.**

> **"Compaction is a commit, not a loss event."**

When a Claude Code session compacts (or ends, or you `/clear`), the
decisions, constraints, and dead ends it contained normally dissolve into
a lossy LLM summary. CtxPack instead **packs the session transcript into a
deterministic, git-committable ledger** — every fact with provenance to
the exact turn — and re-injects a ~2K-token gist at the next session
start. Mid-session, agents query the ledger instead of grepping megabytes
of transcript.

```
 session transcript (L0, never deleted)
        │  PreCompact / SessionEnd hook  (zero LLM, no network, fail-open)
        ▼
 .claude/ctx/session-<id>.ctx      ← decisions, constraints, failed
 .claude/ctx/session-<id>-gist.md    approaches, errors, files, tasks —
 .claude/ctx/checkpoints.jsonl       each with turn provenance
        │  SessionStart hook
        ▼
 next session begins knowing what was decided and why
```

No LLM ever writes to memory: same transcript → byte-identical ledger.
That single property is what the incumbent memory systems (Mem0, Zep,
Letta, LangMem) structurally lack — their LLM-in-the-write-path designs
are nondeterministic, unauditable, and subject to documented context
collapse (ACE, ICLR 2026).

| | Native compaction | Claude auto-memory | LLM memory products | **CtxPack ledger** |
|---|:---:|:---:|:---:|:---:|
| Deterministic writes (no LLM scribe) | ✗ | ✗ | ✗ | ✓ |
| Versioned with the repo (PR-reviewable) | ✗ | ✗ | ✗ | ✓ |
| Provenance to the exact turn | ✗ | ✗ | ✗ | ✓ |
| Survives `/clear` & machine switches | ✗ | partial | ✓ | ✓ |

## Quick start — session memory

```bash
pip install "git+https://github.com/cryogenic22/CTX.ai"   # zero deps
cd your-repo
ctxpack onboard
```

`onboard` idempotently wires: Claude Code **hooks** (PreCompact /
SessionStart / SessionEnd), the **MCP server** entry in `.mcp.json`, the
**conventions block** in `CLAUDE.md`, and the ledger dir. Then restart
Claude Code and approve the hooks + server (config is snapshotted at
startup — nothing fires until you restart).

Use it:

```bash
ctxpack session resume                 # one call: gist + decisions + constraints + exact ids
ctxpack session decisions              # decisions/constraints/failed approaches, with turns
ctxpack session timeline --kinds DECISION,ERROR --limit 20
ctxpack session recall "backoff"       # index → hydrate, the L3 routing pattern
ctxpack session why "pool_size"        # provenance + supersession chain
ctxpack session literals               # every verbatim identifier banked (shas, versions, paths)
ctxpack session stats                  # adoption + capture metrics (see below)
ctxpack checkpoint                     # bank the live session NOW (auto-resolves the transcript)
```

The same operations are MCP tools. The **default agent surface is five
operations** — `ctx/resume`, `ctx/session_recall`, `ctx/why`,
`ctx/session_literals`, `ctx/checkpoint` (the agent-invokable write
path) — with `ctx/session_timeline`, `ctx/session_decisions`, and
`ctx/graph_query` available as advanced tools when those aren't enough.

**The one habit that matters:** state decisions explicitly —
`Decision: use exponential backoff with base 750ms because the vendor
limit is 40 req/min.` Structured signals extract deterministically
(measured 100% on the convention); free-prose decision mining measured
~0% recall on real transcripts, so the convention is load-bearing.
Agent-stated operating rules the same way, sentence-leading:
`Constraint: eval results are immutable — never overwrite results files.`

### Built-in measurement (is it earning its keep?)

Adoption telemetry is computed **from the transcript itself** at
checkpoint time — deterministic, automatic, un-gameable. Per session,
`checkpoints.jsonl` records ledger reads vs raw-transcript fallbacks,
capture counts, gist size, and checkpoint latency. `ctxpack session
stats` aggregates it; the headline is **`raw_fallback_rate`** — if agents
keep grepping the transcript instead of using the ledger, the format
isn't paying rent and the numbers will say so.

## Measured results (read the caveats)

**Agentic NIAH** (synthetic coding-agent trajectories, 12 probes incl.
updated-value chains and adversarials; Sonnet answerer, GPT-4o judge):
fidelity saturates for *all* conditions at ≤64K — the differentiator is
cost. CtxPack answers from a flat **~400 BPE per query regardless of
session length** (166x less context than raw stuffing at 64K), and the
packed structure answers whole-corpus aggregation questions that
budget-bounded top-k retrieval structurally misses.

**GraphWalks-adapted** (service-dependency graphs, exact set-F1):
in-context reasoning degrades on reverse-dependency questions even at
11K BPE (RAW 0.78–0.82); the deterministic traversal over packed edges
(`ctx/graph_query`) is exact — **F1 = 1.000 at every scale** — with zero
model tokens spent on traversal. Packing preserved 100% of edges.

**Document QA** (92K-BPE synthetic enterprise corpus, 30 questions,
cross-model judge): hydrated **86.7%** vs raw stuffing **83.3%** on
Opus-class models, tying embedding-RAG at ~24x fewer context tokens per
query (full-loop accounting pending; likely 10–15x).

**Caveats, stated plainly:** n=30 self-authored questions carries a
±13–18pp CI — treat the fidelity deltas as directional, not definitive.
Single synthetic corpus; no closed-book contamination control yet; on
Haiku-class models raw stuffing wins; sub-Haiku routers collapse. A
decision-recall-across-compaction benchmark (CompactBench, DR@K) with
grep-over-transcript as the null-hypothesis arm is in progress —
current honest numbers live in
[`paper/status-and-value-v0.5.md`](paper/status-and-value-v0.5.md).

## The knowledge packer (the original engine)

The same deterministic pipeline packs domain corpora (YAML, Markdown,
JSON, TOML, CSV) into an indexed knowledge base served by progressive
hydration:

```bash
ctxpack pack path/to/corpus/ --layers L2,L3
ctxpack hydrate output.ctx --section ENTITY-CUSTOMER
ctxpack hydrate output.ctx --query "retention policy PII"
```

1. **Pack** (encoder): discover → parse → entity resolution → conflict
   detection → salience scoring → compress. Same input = byte-identical
   output. No LLM, no ML, no network.
2. **Progressive hydration** (decoder): a ~1.8K-BPE **L3 directory
   index** sits in the system prompt; the **LLM routes** (no embeddings,
   no vector DB); requested sections (~3.5K BPE avg) are injected as
   focused, low-interference context.
3. **Temporal semantics**: same-key revisions supersede
   (`SUPERSEDED-<KEY>: 250@step-0 -> 500@step-2 -> 750@step-4`) — the
   latest value wins, history stays auditable. Negations are never
   stripped or reordered (CI-gated).

The `.ctx` format is a multi-resolution layer system (L0 raw → L3 index)
with a formal [PEG grammar](spec/ctx.peg); spec:
[`spec/CTXPACK-SPEC.md`](spec/CTXPACK-SPEC.md) (CC-BY-SA 4.0).

## MCP server — 20 tools

```bash
pip install "ctxpack[mcp] @ git+https://github.com/cryogenic22/CTX.ai"
python -m ctxpack.integrations.mcp_server
```

| Group | Tools |
|---|---|
| Session memory — default surface | `ctx/resume`, `ctx/session_recall`, `ctx/why`, `ctx/session_literals`, `ctx/checkpoint` |
| Session memory — advanced | `ctx/session_timeline`, `ctx/session_decisions`, `ctx/graph_query` |
| Documents | `ctx/pack`, `ctx/parse`, `ctx/validate`, `ctx/format`, `ctx/hydrate` |
| Code packer (`[code]` extra) | `ctx/code_pack`, `ctx/code_version`, `ctx/code_list_symbols`, `ctx/code_hydrate_symbol`, `ctx/code_search_symbols`, `ctx/code_raw_file`, `ctx/code_telemetry` |

## Install matrix

```bash
pip install "git+https://github.com/cryogenic22/CTX.ai"                    # core: hooks + session CLI (zero deps)
pip install "ctxpack[mcp] @ git+https://github.com/cryogenic22/CTX.ai"     # + MCP server
pip install "ctxpack[all] @ git+https://github.com/cryogenic22/CTX.ai"     # + code packer (tree-sitter, tiktoken)
```

Python 3.10+. The core is and stays **zero-dependency** — hooks, the
checkpoint engine, and `ctxpack session` need nothing but the stdlib.

Team rollout guide (setup, usage habits, two-week measurement protocol,
troubleshooting):
[`docs/session-memory-onboarding.md`](docs/session-memory-onboarding.md).

## Project structure

```
ctxpack/
  core/              # Parser, serializer, validator, packer (zero deps)
    packer/          # Entity extraction, resolution, supersession, compression
    hydrator.py      # Section hydration + layer/confidence/expiry filtering
    entity_graph.py  # Directed entity graph (parents/bfs/path + query API)
    telemetry.py     # Append-only JSONL hydration telemetry
  agent/             # Session-memory substrate
    transcript_parser.py  # Claude Code JSONL → IR (structured signals, turn provenance)
    checkpoint.py         # Pack-on-compact engine + gist builder
    session_reader.py     # Read path: resume/recall/timeline/decisions/why/literals/stats
  modules/           # Experimental / legacy prototypes — not product (see registry)
  integrations/      # MCP server (20 tools)
  cli/               # ctxpack CLI (pack, hydrate, checkpoint, hook, onboard, session, ...)
  benchmarks/        # Eval framework, agentic NIAH + graph generators, metrics
spec/                # CTXPACK-SPEC, PEG grammar
paper/               # Whitepaper, status-and-value (current honest numbers), plan
docs/                # Team onboarding guide
tests/               # 1,323 tests; core suite deterministic, no API keys
```

Every module is classified **core / eval / experimental /
legacy-deprecation-candidate** in the machine-checked
[capability registry](docs/capability-registry.md) — anything not
labelled core is not validated product capability.

## Tests & rigor

```bash
python -m pytest tests/ -q        # full suite (~35 min); scope to touched files first
```

1,323 tests including CI gates that exist because each caught a real
past failure: negation preservation (a compressor once turned "do not
force-push" into "force-push"), byte-determinism (two packs → identical
SHA-256), metric sanity guards (BPE vs word-count gaming, judge
rate-limit failures scored as INCORRECT), and extraction regression
tests from dogfooding this repo on its own ledger.

Standing eval policy: BPE tokens as the primary metric, cross-model
judging, retry with transient-error classification (429/529/…),
immutable versioned results, retracted claims never re-cited.

## Research context

- **Wang & Sun (ICML 2025)** — proactive interference: recall of the
  *latest* value degrades log-linearly with prior updates. CtxPack's
  supersession chains collapse update-noise at pack time.
- **ConstraintRot (arXiv 2606.22528)** — constraint violations go
  0% → 30–59% after compaction; the published fix ("constraint pinning")
  is what a deterministic re-injected RULES gist implements.
- **ACE (ICLR 2026)** — LLM-rewrite memory collapses (18,282 → 122
  tokens); their prescription (delta updates, non-LLM merge) is CtxPack's
  write path.
- **RLM (Zhang/Kraska/Khattab)** — never summarize destructively; keep
  context externally addressable and pull slices on demand. The `.ctx`
  ledger is that external variable; `graph_query` is their
  "programmatic access beats in-context reasoning" argument, measured.
- **Letta filesystem baseline** — grep-over-files at 74% on LoCoMo beats
  dedicated memory products; accordingly, grep-over-transcript is the
  mandatory null-hypothesis arm in our benchmark plan, and the telemetry
  measures fallback to it in production use.

## Limitations

- Fidelity results are n=30 / single synthetic corpus — directional, not
  definitive (±13–18pp CI); no closed-book contamination control yet.
- LLM-as-router needs Haiku-class capability or better; on small models
  raw stuffing can win.
- Decision extraction is deterministic *given the convention*
  (`Decision: ...` lines); unmarked free-prose decisions are often
  missed by design — we chose a convention over an LLM extractor.
- Hooks require a Claude Code restart after install (config snapshots at
  process startup); the ledger is per-repo, per-machine unless committed
  to git.
- Format schism (spec v1.1 pending): layer/confidence/expiry annotations
  have no surface syntax yet; supersession chains use positional `->`
  encoding rather than stable fact IDs.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Key policies: zero external
dependencies in `ctxpack/core/` and `ctxpack/agent/`; all tests pass
before merge; BPE tokens for all compression/cost claims; never strip
negations; results files are immutable.

## Disclaimer

CtxPack is a research tool provided as-is. It is not a substitute for
professional judgment in regulated industries. Users are responsible for
validating output against source material before production use. See
[NOTICE](NOTICE) for trademark attributions. Benchmark results reference
commercial LLM products by name for factual comparison purposes only.

## License

Apache-2.0. See [LICENSE](LICENSE). The `.ctx` format specification is
CC-BY-SA 4.0.
