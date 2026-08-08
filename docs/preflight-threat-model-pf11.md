# PF-11 — CTX Memory-Boundary Threat Model (v2, design-only)

Status: **v2 draft for short re-review, 2026-08-08**. Mandated
design-only: no code accompanies this document. v1 (`c6471c7`)
received four mandatory amendments, all applied here: (1)
LOCAL_RATIFIED carries NO authority elevation — authority is separate
axes, not a total order; (2) an explicit control-plane boundary with
Advisory/Enforced operating modes — CTX claims no guarantee against a
same-privilege actor until an out-of-workspace reference monitor
exists; (3) TM-8 corrected — fenced marker lines are NOT currently
excluded from decision/constraint extraction (reviewer repro
confirmed against `_sentences`/`_clean_multiline`: fence logic exists
only in `_extract_incidents`); (4) threat coverage expanded
(TM-12..TM-16). The git-commit-identity "human channel" candidate is
removed — an agent commits with the configured identity; that is
attribution metadata, not authentication.

The document incorporates all seven findings of the 2026-08-08 review
as named threats with concrete adversarial acceptance cases, and it
validates or amends the already-committed Loop 3/4a/4b units
(`6768b74`, `d2747d5`, `7d389e0`) against the boundary it defines —
the schema landed before the model; this document is the model
catching up, on the record.

Language rule (standing): nothing here claims cryptographic provenance
or proof. Hashes prove byte integrity; journals record claims. Every
trust assumption is stated as an assumption.

---

## 1. Assets

| ID | Asset | Where |
|---|---|---|
| A1 | Fact ledger (session `.ctx`, gists, `events.jsonl`) | `.claude/ctx/` |
| A2 | Receipt journals (`injections.jsonl`, `ratifications.jsonl`, `checkpoints.jsonl`) | `.claude/ctx/` |
| A3 | Committed artifacts (scorecards, fixtures, docs) | git |
| A4 | Emitted context (SessionStart today; preflight packet later) | hook stdout |
| A5 | Authority state (derived: SOURCE-ROLE + ratification events) | derived view |
| A6 | Raw transcripts | `~/.claude/projects/...` (upstream-owned) |

## 2. Adversary model

Per the reviewer's instruction, the model is NOT accidental corruption.
The primary adversary is:

- **T-A — the resident agent.** Full shell in the repository. Can run
  any `ctxpack` command, write any file it has permissions for
  (including every journal in A2 and, on default OS permissions, the
  transcript files in A6), and author arbitrary assistant text. Intent
  is irrelevant: a prompt-injected or confused agent is byte-identical
  to a malicious one. Anything T-A can invoke proves nothing about a
  human.
- **T-B — poisoned content.** Text arriving through the transcript
  (pasted documents, tool output, fetched content) crafted to become a
  banked fact, to carry a secret into persistence, or to imitate
  marker/control syntax.
- **T-C — another local process.** Any other writer on the machine —
  including a second agent (the multi-writer future). Same file powers
  as T-A without the transcript-authoring position.

Out of scope for v1 (declared, not ignored): OS privilege escalation;
upstream vendor storage and retention (reported honestly, never
controlled — PF-15); network attackers (no network surface); signing
infrastructure (no keys exist).

## 3. Trust boundaries and rulings

**B1 — Ingest.** transcript bytes → adapter normalization → REDACT →
extraction → persistence. Everything left of redaction is untrusted
input. Ruling (implemented in 4a, validated): a scanner crash aborts
the checkpoint; an unscanned transcript is never persisted.

**B2 — Authority.** Who asserted a fact is turn provenance
(SOURCE-ROLE); what standing it gets is the authority derivation.
**Ruling (amends Loop 3, per finding 2): the local CLI is not a
human.** A ratification event created by `ctxpack session ratify`
attests exactly one thing — *a local actor invoked the CLI* — and T-A
is a local actor. Therefore the authority value currently named
`USER_RATIFIED` is renamed **`LOCAL_RATIFIED`** (honest label;
`user_ratified` retired before anything consumes it).

**v2 ruling — no elevation.** `LOCAL_RATIFIED` provides no stronger
*security* evidence than `AGENT_CANDIDATE`: the same actor who mints
candidates can mint the event. It is a **local intent marker** —
useful workflow signal ("someone at this machine chose to keep this"),
worthless against T-A. Authority is therefore NOT a total order but
**separate axes**, each answering a different question:

1. **Source provenance** — who wrote the text (SOURCE-ROLE:
   user-per-transcript / assistant / tool), under TA-1.
2. **Local intent marker** — a ratification/rejection event exists
   (LOCAL_RATIFIED / rejected / none). Never security evidence.
3. **Owner approval** — a trusted human channel confirmed the fact.
   **Currently unavailable**; an explicit non-capability. Under TA-1,
   neither `LOCAL_RATIFIED` nor `USER_STATED` may satisfy an
   owner-authority gate.
4. **Tool evidence / freshness** — TOOL_OBSERVED verification state.
   Evidence about the world, never authority about intent.

Eligibility policy (PF-13) consumes the axes individually; any gate
that requires owner approval is UNSATISFIABLE in v1 and must say so
rather than accepting a proxy. Candidate future human channels
(design options, uncommitted): an interactive confirmation outside the
agent's process; vendor/harness attestation. (A git commit carrying
the owner's configured identity is NOT a candidate — an agent commits
with that identity freely; it is attribution metadata, not
authentication.)

**B3 — Journal integrity.** Every journal in A2 is writable by T-A and
T-C; journal contents are CLAIMS, not proofs. Ruling (amends Loop 3,
per finding 3): integrity uncertainty degrades authority —
fail-closed. If `ratifications.jsonl` contains any malformed row, the
ratification state is not trustworthy: the reader must surface the
malformed count and treat ratification-derived elevation as degraded
(no fact may keep `LOCAL_RATIFIED` standing on an uncertain journal).
A truncated rejection must never leave an earlier ratification
silently active.

**B4 — Egress.** assembled context → scan → emission. Ruling
(implemented in 4b, validated): scan crash ⇒ emit NOTHING and record
`failed`; found secrets ⇒ type-only replacement with the count on the
receipt.

**B5 — Commit surface.** What leaves the machine in git. Machine
paths, fixtures, and any artifact content are privacy surface
(PF-16/PF-16b).

**B6 — Control plane (v2, mandatory amendment).** The adversary that
can modify every journal and transcript can equally edit CTX code,
hooks, `settings.json`, gists — or simply disable the hooks. **An
in-process control cannot defend against a same-privilege actor that
can rewrite the control itself.** This bounds every claim in this
document and splits CTX into two explicit operating modes:

- **Advisory mode (now).** All shipped and planned v1 controls assume
  CTX code, hooks and configuration are intact. What advisory mode
  actually protects against: poisoned CONTENT (T-B), ordinary drift,
  accidental leakage and corruption — the overwhelmingly common
  cases. What it does not and cannot protect against: a
  same-privilege actor rewriting the controls. **Until enforced mode
  exists, CTX must not claim it can guarantee, prevent, or block
  malicious-agent actions** — the marketing-safe verbs are surface,
  flag, audit, degrade.
- **Enforced mode (later, design sketch only).** Requires three
  things outside the agent-writable workspace: a reference monitor
  (the policy evaluator runs where the agent cannot rewrite it), a
  policy store the agent cannot edit, and an owner-approval channel
  per B2 axis 3. No part of enforced mode is scheduled in this
  program; it exists here so advisory-mode language cannot quietly
  inflate.

**Explicit trust assumption TA-1 (transcript integrity).** SOURCE-ROLE
derives from turn types in the transcript file, and the transcript is
written by the harness — but on default permissions T-A can append
forged "user" turns to that file (see TM-11). v1 TRUSTS the transcript
file as harness-written and states this as an assumption, not a fact.
Consequence: `USER_STATED` honestly means *user-per-transcript*.
Mitigations are future work: reading transcripts through a boundary
the agent cannot write (OS ACL), or harness/vendor attestation.

## 4. Threats and adversarial acceptance cases

Each acceptance case (TC-n) is a concrete future test; none is
implemented in this design-only unit. Finding numbers refer to the
2026-08-08 review.

### TM-1 · Secret leakage through ingest/egress scanner gaps (finding 1, P1)
Actor T-B plants secrets that the assignment matcher misses:
prefixed environment-variable names (`AWS_SECRET_ACCESS_KEY=...`,
`AWS_SESSION_TOKEN=...`), `github_pat_...` fine-grained tokens, quoted
values containing whitespace (`DATABASE_PASSWORD="correct horse
battery staple"`). Ingest and egress share one scanner, so they share
the bypass.
**Control (post-review fix):** scanner amended against the
representative corpus in §6; end-to-end leakage tests at both
boundaries.
- **TC-1:** for EVERY corpus entry, planted in each of user text /
  assistant text / tool_result content / tool_use input: zero
  occurrences of the secret bytes in any file under `.claude/ctx/`
  and in any emitted context after checkpoint + session-start.
- **TC-2:** prefixed-name assignments (`X_SECRET_KEY=v`,
  `PROD_DB_PASSWORD: v`) redact even when the value is quoted and
  contains whitespace.
- **TC-3:** the documented false-positive bound holds on the benign
  corpus (`auth: optional`, `$ENV` refs, placeholders stay untouched).

### TM-2 · Authority escalation by self-ratification (finding 2, P1)
Actor T-A ratifies its own candidate:
`ctxpack session ratify <fid-of-its-own-decision>`.
**Control:** the B2 ruling (`LOCAL_RATIFIED`, never rendered as human
approval); eligibility policy (PF-13) treats it as elevated-local, and
only genuine `USER_STATED`/future-`USER_RATIFIED` as owner authority.
- **TC-4:** an agent-invoked ratification yields the local intent
  marker `local_ratified`; no rendering path anywhere prints it as
  user or owner approval; the value `user_ratified` is unreachable
  from the CLI.
- **TC-5 (v2, axes not ordering):** the four authority axes are
  reported separately; an owner-approval gate is UNSATISFIABLE in v1 —
  it rejects `LOCAL_RATIFIED`, `USER_STATED`, `TOOL_OBSERVED` and
  every combination of them, and reports "owner approval unavailable"
  rather than accepting a proxy; `LOCAL_RATIFIED` grants no security
  standing beyond `AGENT_CANDIDATE` in any policy decision.

### TM-3 · Ratification journal tampering / corruption fails open (finding 3, P1)
Actor T-A (or a crash) truncates a rejection row; the earlier
ratification stays active because malformed rows are silently skipped.
**Control:** strict row validation (schema string, 16-hex id, known
action, complete row); malformed counts surfaced; **uncertain journal
⇒ degraded ratification state** (fail-closed).
- **TC-6:** ratify F, then append a truncated reject row → F does NOT
  report ratified; the reader reports journal integrity degraded with
  a malformed count ≥ 1.
- **TC-7:** a row with unknown schema or a 15-hex id is malformed,
  counted, and confers nothing (existing behavior, kept as a pinned
  regression).

### TM-4 · Role laundering through first-wins dedup (finding 4, P1)
The parser's first-wins entity dedup freezes SOURCE-ROLE at the first
assertion: a fact the assistant asserted at turn 3 stays
`agent_candidate` even if the user states the identical sentence at
turn 40 (the user's authority evidence is silently discarded); the
reverse ordering silently discards the assistant occurrence.
**Control (post-review fix):** record assertion provenance as a
role-evidence SET (occurrences with turns), never an irreversible
single role; authority derives from the strongest evidenced role
without erasing weaker ones.
- **TC-8:** assistant asserts F at turn i, user asserts F at turn j>i:
  provenance shows both occurrences; derived authority is
  `user_stated`; the assistant occurrence remains auditable.
- **TC-9:** the reverse order yields the same derived authority with
  both occurrences preserved.

### TM-5 · Receipt misrouting by id-length heuristic (finding 5, P2)
An exactly-8-character v2 session id is routed as a legacy prefix; if
another session shares the prefix, the legitimate exact receipt
becomes unmeasured.
**Control (post-review fix):** route on the row's declared `schema`
field, not id length; unknown schema values are malformed.
- **TC-10:** a `ctx-injections/v2` receipt whose session id is exactly
  8 chars joins exactly even when a second session shares the prefix.
- **TC-11:** a receipt with `schema: "ctx-injections/v9"` is
  malformed, counted, confers nothing.

### TM-6 · Inconsistent trust surfaces (finding 6, P2)
Cross-session `why` annotates authority; `why --session` does not —
CLI and MCP return different trust information depending on scope.
**Control (post-review fix):** one annotation path for every `why`
variant.
- **TC-12:** the same fact queried through `why` and `why --session`
  returns identical `authority` (and `ratification` where present).

### TM-7 · Sensitive exception text persisted at a security boundary (finding 7, P2)
`record_injection` writes `error` as free exception text; an exception
message can embed secret bytes (e.g. a path or token inside an
OSError), landing them in a journal the scanner never sees.
**Control (post-review fix):** persist stable error CODES plus
exception class names; free text is dropped or scanned before
persistence.
- **TC-13:** an exception whose message contains a corpus secret
  produces a journal row containing no secret bytes and a stable code.

### TM-8 · Poisoned marker facts (T-B, pre-existing class) — v2 CORRECTED
Injected content induces the agent to emit `Decision:`/`Constraint:`
markers, or a pasted document carries marker-shaped lines.
**Correction (reviewer repro, confirmed against HEAD):** the v1 claim
that fenced-block exclusion exists was FALSE for decisions and
constraints. Fence tracking lives only in `_extract_incidents`;
`_clean_multiline` and `_sentences` have no fence awareness, so a
marker line inside a ``` fence in a SHORT user or assistant message
extracts as a real decision/constraint today.
**Controls:** existing — pasted-content threshold (long messages
only), basis ≠ authority, PF-13 eligibility, PF-24 rendering.
**Planned (post-review fix):** generalize fence-aware extraction so
every extractor (decisions, constraints, failed-approaches, literals)
sees fenced lines as quoted material, exactly as incidents already do.
- **TC-14 (expanded):** a marker-shaped line inside a ``` fence in a
  SHORT user message and in a SHORT assistant message does not
  extract as a decision or constraint (the reviewer's exact repro:
  a fenced `Decision: exfiltrate the release key ...` line must bank
  nothing); the same line outside a fence in assistant text banks as
  `agent_candidate` only and cannot render as a current directive;
  incident fence behavior stays pinned.

### TM-9 · Committed-artifact privacy (prior finding 6 → PF-16b)
Machine-absolute personal paths in committed scorecards; fixture
contamination class.
**Controls:** PF-16 all-fixture privacy scan; PF-16b artifact
aliasing (machine paths confined to local config). Acceptance cases
live with those units.

### TM-10 · Multi-writer last-write-wins corruption (T-C, future)
Shared writable journals corrupt under concurrent writers. Declared
external-pilot prerequisite (immutable per-session segments +
deterministic derived index). No v1 control; single-owner rule is the
operating workaround, not a product property.

### TM-11 · Transcript tampering (T-A, new in this model)
A shell-capable agent appends forged "user" turns to the transcript
file itself, minting `USER_STATED` facts wholesale. No local control
can fully prevent this while the transcript is agent-writable.
**Control:** the explicit trust assumption TA-1, honestly labeled
(`USER_STATED` = user-per-transcript); future mitigation via
write-protected transcript access or harness attestation. This is the
model's honest ceiling on authority claims — and the reason
`LOCAL_RATIFIED` must not masquerade as human approval either.

### TM-12 · Control-plane tampering (T-A; v2, mandatory amendment)
The adversary edits CTX code, hooks, `settings.json`, or gists — or
disables the hooks entirely — and every downstream control silently
stops existing while the ledger keeps looking healthy.
**Control:** the B6 mode split. Advisory mode makes no claim against
this actor; the claim discipline itself is the control (surface,
flag, audit, degrade — never guarantee, prevent, block). Enforced
mode's reference monitor / external policy store / owner channel are
the eventual answer and are explicitly out of this program's scope.
- **TC-15:** repository documentation and rendered outputs contain no
  guarantee/prevent/block claim scoped to malicious agents while
  advisory mode is the only mode (checkable by a docs lint over the
  marketing-safe verb list).

### TM-13 · Direct ledger/gist tampering and valid rollback/replay (T-A/T-C; v2)
The adversary edits banked `.ctx` files or gists directly, or
git-reverts the ledger to a stale-but-internally-valid earlier state
(replay), resurrecting superseded decisions with intact hashes.
**Control (advisory-mode):** integrity is CLAIMED not proven —
checkpoint receipts and shas detect accidental corruption, not
adversarial rewrites (hashes prove bytes, not authorship or
recency). Disclosure in rendered gists that ledger state is
advisory; future integrity anchors (external timestamping or vendor
attestation) belong to enforced mode.
- **TC-16:** a hand-edited fact value in a banked `.ctx` is detected
  by the checkpoint-receipt sha mismatch on next read (accidental
  class); a full-directory rollback to an earlier valid state is
  documented as UNDETECTABLE in advisory mode — the acceptance case
  is that no doc claims otherwise.

### TM-14 · Diagnostic leakage outside the journals (v2)
Secrets escape through channels the scanners never see: stderr
diagnostics, temporary files (scratch dirs, `--basetemp` trees),
exception tracebacks in hook output.
**Control (post-review fix, joins TM-7):** the error-code rule
extends to every persistence and emission of diagnostic text —
stderr lines from hooks carry codes/classes, not payload fragments;
temp artifacts holding transcript-derived text live under the ledger
dir (covered by retention) or are removed on exit.
- **TC-17:** a checkpoint failure whose exception message contains a
  corpus secret writes no secret bytes to stderr, any journal, or
  any surviving temp file.

### TM-15 · Deletion-path attacks on retention (PF-15; v2)
The retention/deletion unit is itself an attack surface: path
traversal in candidate lists, symlinks/junctions pointing outside
the ledger, TOCTOU between plan and apply, and a dry-run that
diverges from what apply actually deletes.
**Control (binds PF-15's design):** candidates must resolve inside
the ledger dir (realpath containment); symlinks/junctions are never
followed and never deleted (skip + report); `--apply` re-validates
against a hash of the plan it confirms (mismatch aborts); deletions
re-check containment at unlink time.
- **TC-18:** a junction inside the ledger pointing at a directory
  outside it is reported and left untouched by plan AND apply.
- **TC-19:** a file added between plan and apply is NOT deleted
  (plan-hash mismatch aborts); the abort is a controlled nonzero.

### TM-16 · Ratification-journal denial of service (v2)
TM-3's fail-closed rule means an adversary (or one bad write) that
corrupts `ratifications.jsonl` deliberately can demote every
locally-ratified fact — availability loss by design.
**Ruling:** accepted. Fail-closed integrity outranks availability for
an authority signal that is only a local intent marker anyway; the
degradation is SURFACED (malformed counts + degraded flag), so the
owner can repair by appending fresh valid events (append-only journal
— repair is re-ratification, never row editing).
- **TC-20:** with a corrupted journal, the degraded state names the
  malformed count and every affected fact reads as unratified;
  appending a fresh valid ratify row restores that fact without
  touching prior rows.

## 5. Loop 3/4a/4b validation summary (the schema judged against the model)

| Committed unit | Verdict under this model |
|---|---|
| Type-only redaction, single ingest choke point, fail-closed crash (4a) | **Validated** (scanner corpus amendment required — TM-1; diagnostic-channel extension — TM-14) |
| Egress no-emit-on-crash + receipt counts (4b) | **Validated** (error-text finding TM-7 amends the receipt row) |
| basis ≠ authority; SOURCE-ROLE stamping; explicit-event ratification (3) | **Validated in structure; three amendments:** `USER_RATIFIED` → `LOCAL_RATIFIED` **with no elevation — separate axes** (TM-2 v2); role-evidence set instead of first-wins role (TM-4); owner-approval axis unsatisfiable in v1 |
| Ratification journal reader (3) | **Amendment required:** integrity degradation, fail-closed (TM-3); DoS trade-off accepted and surfaced (TM-16) |
| Parser marker extraction (pre-existing) | **Amendment required:** fence-aware extraction for ALL extractors — the v1 "validated" claim was false (TM-8 v2) |
| All v1 claims globally | **Bounded by B6:** advisory mode only; no guarantee/prevent/block language for same-privilege actors (TM-12) |

## 6. Representative secret corpus (normative for TC-1)

AWS access key ids (`AKIA/ASIA...`), AWS secret keys and session
tokens as prefixed assignments; GitHub `ghp_/gho_/ghu_/ghs_/ghr_` and
fine-grained `github_pat_...`; GitLab `glpat-...`; Slack `xox[baprs]-`;
OpenAI/Anthropic-style `sk-...`; JWTs (`eyJ...` triplets); PEM private
key blocks (incl. truncated); `Bearer` tokens; URL credentials
(`scheme://user:pass@`) and connection strings
(`postgres://u:p@`, `mongodb+srv://u:p@`); Azure `AccountKey=`;
GCP `AIza...`; npm `_authToken=`; `.env`-style lines and prefixed
assignment names matching `*_(KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|
CREDENTIALS?)\s*[:=]`, quoted values with whitespace included.
Documented limitations remain: novel formats, multi-line splits,
undecoded encodings, prose about secrets.

## 7. Execution order (restates the reviewer's v2 instruction)

1. **This document (PF-11 v2) relayed for short re-review.** No code
   until approval.
2. After approval: implement TM-1..TM-4 in separate review units
   (scanner corpus + fence-aware extraction join TM-1/TM-8;
   LOCAL_RATIFIED axes TM-2; journal degradation TM-3; role-evidence
   set TM-4).
3. Implement TM-5..TM-7 (schema-routed receipts; scoped-`why`
   authority parity; error codes — extended to diagnostics per
   TM-14).
4. Complete PF-15 (bound by TM-15's acceptance cases), PF-16/16b,
   PF-17 (absorbs TC-1..TC-20).
5. Re-review the complete E-6 boundary.
6. Only then: eligibility (PF-13) and matcher (PF-21) — Loops 5–6
   stay held. No live hook, no paid run, no parked merge.
