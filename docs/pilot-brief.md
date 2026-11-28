# CtxPack Pilot Brief: Auditable Session Memory for Coding Agents

*One page. Recruiting now. Onboarding starts after the security review
in "Timing" is finished. Transcripts do not go through a tool whose
threat model is not finished.*

## The problem

When a Claude Code session compacts, or you clear the session, that
context is no longer in the model window. This brief does not claim a
recall number for native compaction, and it does not claim higher
recall than grep over the transcript.

## What CtxPack does

Packs a session transcript into a ledger you can commit. No model runs
on the write path. A stored fact can point at the turn it came from.
The next session start re-injects the budgeted brief from
`ctxpack.agent.brief`, not a fixed-size gist. Decisions and constraints
are captured from sentence-leading `Decision:` and `Constraint:` lines.
Unmarked prose is not the capture contract. The ledger is files in the
repo. You can read them and diff them.

## What a pilot gets

- Help with install: `ctxpack onboard`, then a Claude Code restart.
  This brief does not state a setup time.
- A ledger that remains in the repo across compaction, `/clear`, and a
  clone on another machine, when `.claude/ctx/` is committed.
- Adoption counters from `ctxpack session stats`, including how often a
  recall attempt used the raw transcript. That counter is not a recall
  result.
- A direct line to the maintainer.

## What we ask (two weeks)

- Use Claude Code normally on a real repo — no workflow changes beyond
  one convention: state decisions as `Decision: ...` lines.
- Let us collect **derived telemetry only**: adoption counters, capture
  counts, gist sizes, checkpoint latency. Raw transcripts and ledger
  content stay on your machines unless you choose to share an excerpt.
- A 30-minute exit conversation: what helped, what didn't, would you
  keep it.

## What a pilot would measure

Ledger-read vs raw-fallback rate · time-to-resume after compaction ·
stale-decision incidents · repeated-mistake incidents · identifier
fidelity · user-rated usefulness. Results feed a public benchmark
program with preregistered analyses; negative results are reported.

## Honest status

The deterministic write path, turn provenance, and the resume and recall
commands are in the tree. This brief does not claim higher recall than
grep over the transcript, or higher recall than native compaction.
Third-party ergonomics are what a pilot would observe. Notes under
`paper/status-and-value-v0.5.md` are research records, not product claims.

## Timing

Recruiting now. Onboarding begins once our security/threat-model review
(secret redaction in transcripts, project isolation) and the
installation-hardening pass are complete. Both documents go to pilots
before onboarding starts. This brief does not give a calendar date.

**Contact:** Kapil Pant, kapilpant@gmail.com,
https://github.com/cryogenic22/CTX.ai
