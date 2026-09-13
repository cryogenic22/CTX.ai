# CtxPack Pilot Brief — Auditable Session Memory for Coding Agents

*One page. Recruiting now; onboarding starts after our security review
completes (see "Timing" — we won't put your transcripts through a tool
whose threat model isn't finished).*

## The problem

When a Claude Code session compacts (or you `/clear`), the decisions,
constraints, and dead ends it contained dissolve into a lossy LLM
summary. In our sentinel benchmark, decision recall through native
compaction was **zero after the first compaction** — the agent re-asks,
re-decides, and re-makes mistakes you already paid for.

## What CtxPack does

Packs every session transcript into a **deterministic, git-committable
ledger** — no LLM in the write path, every fact carrying provenance to
the exact turn — and re-injects a ~2K-token gist at the next session
start. Mid-session, the agent queries the ledger (`resume`, `recall`,
`why`, `literals`) instead of grepping megabytes of transcript. Memory
you can read, diff, and PR-review, not an opaque vendor database.

## What a pilot gets

- Install + onboarding support (target: under ten minutes to first
  checkpoint; one command, one Claude Code restart).
- Session continuity across compactions, `/clear`, and machine switches.
- Built-in adoption telemetry so *you* can see whether it's earning its
  keep — the headline metric is how often the agent still falls back to
  raw-transcript grepping.
- Direct line to the maintainer; fixes on real friction land fast (the
  current backlog was built entirely from real agent-consumer feedback).

## What we ask (two weeks)

- Use Claude Code normally on a real repo — no workflow changes beyond
  one convention: state decisions as `Decision: ...` lines.
- Let us collect **derived telemetry only**: adoption counters, capture
  counts, gist sizes, checkpoint latency. Raw transcripts and ledger
  content stay on your machines unless you choose to share an excerpt.
- A 30-minute exit conversation: what helped, what didn't, would you
  keep it.

## What we measure (and publish, win or lose)

Ledger-read vs raw-fallback rate · time-to-resume after compaction ·
stale-decision incidents · repeated-mistake incidents · identifier
fidelity · user-rated usefulness. Results feed a public benchmark
program with preregistered analyses; negative results are reported.

## Honest status

Deterministic write path, provenance, and resume/recall surfaces are
solid and dogfooded daily on our own repos. What's *not* proven yet:
superiority over grep-over-transcript at statistical power (benchmark in
progress, preregistered), and third-party ergonomics — that's what the
pilot exists to test. Current evidence and caveats:
`paper/status-and-value-v0.5.md`.

## Timing

Recruiting now. Onboarding begins once our security/threat-model review
(secret redaction in transcripts, project isolation) and the
installation-hardening pass are complete — we'll share both documents
with pilots. Expected: weeks, not months.

**Contact:** Kapil Pant — kapilpant@gmail.com ·
https://github.com/cryogenic22/CTX.ai
