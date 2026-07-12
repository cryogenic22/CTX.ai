# Token-calibration fixtures (frozen — do not edit)

Immutable calibration corpus for `ctxpack.core.tokens` (reviewer
finding Q2-4, 2026-07-11: the previous gate ran on live-mutable
dogfood ledgers and silently skipped without tiktoken).

Every file here is FROZEN: its cl100k token count and sha256 are
committed in `expected_cl100k.json`, so the drift gate runs in every
environment — tiktoken is only needed to re-verify fixture integrity,
never to enforce the kill threshold. Editing any fixture requires
re-measuring with `tiktoken cl100k_base` and re-committing the JSON in
the same change (the sha256 check fails loudly otherwise).

Provenance:

| File | Kind | Source |
|---|---|---|
| `ctx_spec_frozen.ctx` | ctx | `spec/CTXPACK-SPEC.L2.ctx` at commit `af542a2` |
| `ctx_session_frozen.ctx` | ctx | `.claude/ctx/session-eca3f61c.ctx` at commit `af542a2` (committed state, not the live file) |
| `ctx_cohort_synth_frozen.ctx` | ctx | authored 2026-07-12 — SYNTHETIC unrelated-repo session ledger (fictional `meridian-etl` repo, fictional user, deterministic generator). Replaces the withdrawn KP_SDLC cohort fixture, which carried raw user/session history and personal paths (reviewer privacy finding, Q2-4 re-check). Calibration on the replacement: chars/3 lands −4.3% vs cl100k |
| `prose_readme_frozen.md` | prose | `README.md` at commit `af542a2` |
| `prose_unicode_frozen.md` | prose | authored 2026-07-11 — English-dominant prose salted with CJK/Cyrillic/emoji/typographic characters |

Privacy note (2026-07-12): fixtures must never carry raw cohort/user
session content — the unrelated-repo sample is synthetic by policy.
The withdrawn KP_SDLC fixture remains in git history; purging it needs
a history rewrite, which is the owner's call.

Disclosed limitation: the divisors are calibrated for
English-dominant repository content. Pure non-Latin text (e.g. a
CJK-only document) is outside the calibration domain and would exceed
the kill threshold — the Unicode fixture pins the realistic mixed case
(measured -6.7%), not that extreme.
