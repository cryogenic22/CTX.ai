# Using an old CtxPack (≤ v0.4)? Do this.

*For repo teams that adopted an early ctxpack — a vendored `ctxpack/`
folder committed in your repo, or an old version pip-installed in your
venv — and now also want session memory. Two independent tracks: fix
Track A today (5 minutes); do Track B when convenient.*

## First, find out what you have

```bash
python -c "import ctxpack; print(ctxpack.__version__, ctxpack.__file__)"
```

Run this in the same terminal/venv you launch Claude Code from.

- **`0.5.0rc1` (the current pre-release), or a later 0.5.x, + a path into
  a `CTX_mod` checkout** → you're on the candidate; just run Track A step 2
  onward.
- **`0.3.x`/`0.4.x` (anything older than `0.5.0rc1`), or a path inside YOUR
  repo or YOUR venv** → you have an old copy; follow both tracks.

## Track A — session memory on your repo (do now, 5 min)

1. **Make sure the `python` that launches your Claude Code sessions has
   ctxpack ≥ 0.5.0rc1** — note that `0.5.0rc1` *precedes* the final
   `0.5.0` under PEP 440, so pin the `rc1` explicitly (a bare `>=0.5.0`
   would exclude the current pre-release). If your venv has an old
   ctxpack, upgrade it *in the venv*:
   ```bash
   # from a local checkout of CTX_mod (substitute your own path):
   pip install -e /path/to/CTX_mod
   # or install the tagged pre-release directly:
   pip install "ctxpack @ git+https://github.com/cryogenic22/CTX.ai@v0.5.0-rc1"
   ```
   This matters because hooks run whatever `python` is on PATH: an old
   ctxpack there means no `hook` command, and (before v0.5) that could
   even block compaction.
2. In your repo: `ctxpack onboard` — **re-run it even if you onboarded
   before.** It's idempotent and picks up two fixes you need: the Stop
   hook (crash protection) and shadow-proof `python -P` hook commands
   (your vendored copy can no longer hijack hook execution). The `-P`
   flag needs **Python >= 3.11**; on 3.10 onboarding emits plain
   `python -m`, which is *not* shadow-proof (onboard says so, and
   `ctxpack onboard --check` fails loud) — use 3.11+ for shadow-proof
   commands.
3. Restart Claude Code in the repo; approve hooks + MCP server.
4. Sanity check: `ctxpack onboard --check` (verifies hooks + MCP both
   resolve to one shadow-proof ctxpack), then `ctxpack session stats`
   after your next session.

**Note for vendored-copy repos:** you do NOT need to delete your
`ctxpack/` folder for session memory to work — the `-P` flag (Python
3.11+) makes hooks ignore it. Your code keeps importing your copy
exactly as before.

## Track B — your code that imports ctxpack (when convenient)

**Good news: every 0.3-era public API still exists in 0.5.0** —
`pack`, `parse`, `validate`, `serialize`, the hydrator, and all the
modules (`grounding`, `keywords`, `guard`, `catalog_queries`,
`analytics`). The upgrade is import-compatible; what changed is
*behavior*, and every change is a correctness fix:

| Change since 0.3/0.4 | What you may notice | What to do |
|---|---|---|
| **Negations preserved** (0.3 could turn "do not force-push" into "force-push") | packs slightly larger, safer | nothing — this alone justifies upgrading |
| &nbsp;&nbsp;↳ *Field-confirmed 2026-07-04 (market_zero probe): 3/3 pharma negations invert under vendored 0.3.0 ("did not meet its primary endpoint" → "meet endpoint") and survive under 0.5.0. The inverting path is `md_parser._compress_prose` (markdown/prose sources); 0.3.0's YAML value path preserves negations. If you keep a vendored 0.3.0 for now: add a canary test that packs a known negation and asserts it survives, or CI-block prose/markdown sources from your corpus dir — 0.3.0 has no guard of its own.* | | |
| **Deterministic dates** — headers use `--as-of` / `CTXPACK_AS_OF`, never wall clock | header dates differ | pass `as_of=` where you need pinned output |
| **Temporal supersession** — same-key revisions collapse to latest + audit chain | fewer duplicate keys | opt-in via `resolve_entities(supersede_by_recency=True)` |
| **BPE-first metrics** (word-count ratios were misleading) | compression numbers look different | re-baseline; don't compare to old ratios |
| **Smaller L3 index** | L3 ~304 BPE vs old bloat | nothing |

Upgrade recipe:

1. Upgrade the package in your environment (Track A step 1).
2. If you have a **vendored `ctxpack/` folder**: delete it, run your
   test suite against the installed 0.5.0. If green, commit the
   deletion. If something breaks, keep the vendored copy for now (hooks
   are already safe) and tell the CTX team what broke.
3. **Re-pack your corpora** with 0.5.0. Do not byte-diff new packs
   against old ones — output changed by design. If you have golden-file
   tests asserting old pack bytes, regenerate the goldens.
4. Never run two ctxpack versions for the same purpose in one repo.

## TL;DR to paste in your team channel

> If your repo uses an old ctxpack (vendored folder or old venv
> install): (1) upgrade the package in the environment you launch
> Claude Code from, (2) re-run `ctxpack onboard` in the repo, (3)
> restart Claude Code and approve the prompts. Your existing code keeps
> working — all old APIs exist in 0.5.0 — but re-pack your corpora and
> re-baseline any pack-output assertions when you upgrade the code
> path. Session memory works even if you keep your vendored copy.
