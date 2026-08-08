# PF-11 — CTX Memory-Boundary Threat Model (v1, design-only)

Status: **draft for reviewer approval, 2026-08-08**. Mandated
design-only: no code accompanies this document. It incorporates all
seven findings of the 2026-08-08 review as named threats with concrete
adversarial acceptance cases, and it validates or amends the
already-committed Loop 3/4a/4b units (`6768b74`, `d2747d5`, `7d389e0`)
against the boundary it defines — the schema landed before the model;
this document is the model catching up, on the record.

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
`user_ratified` retired before anything consumes it). `LOCAL_RATIFIED`
is elevated above `AGENT_CANDIDATE` for eligibility ordering but is
NEVER rendered as human approval. A genuine `USER_RATIFIED` may exist
only when a trusted human channel exists; candidate channels (design
options, uncommitted): a human-edited ratification file whose git
commit carries the owner's identity; an interactive confirmation
outside the agent's process; vendor attestation. Until one is built and
reviewed, human attribution is an explicit non-capability.

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
- **TC-4:** an agent-invoked ratification yields authority
  `local_ratified`; no rendering path anywhere prints it as user
  approval; the enum value `user_ratified` is unreachable from the
  CLI.
- **TC-5:** eligibility ordering: `USER_STATED` > `LOCAL_RATIFIED` >
  `TOOL_OBSERVED` (evidence, not approval) > `AGENT_CANDIDATE` >
  `LEGACY_UNKNOWN`; a `LOCAL_RATIFIED` fact never satisfies a gate
  that requires owner authority.

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

### TM-8 · Poisoned marker facts (T-B, pre-existing class)
Injected content induces the agent to emit `Decision:`/`Constraint:`
markers, or a pasted document carries marker-shaped lines.
**Controls (existing, validated):** pasted-content threshold and
fenced-block exclusion in the parser; basis ≠ authority (an
assistant marker is only ever `agent_candidate`); PF-13 eligibility
(candidates are never authoritative); PF-24 rendering classes.
- **TC-14:** a marker-shaped line inside a pasted document / fenced
  block does not extract; the agent-restated version banks as
  `agent_candidate` and cannot render as a current directive.

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

## 5. Loop 3/4a/4b validation summary (the schema judged against the model)

| Committed unit | Verdict under this model |
|---|---|
| Type-only redaction, single ingest choke point, fail-closed crash (4a) | **Validated** (scanner corpus amendment required — TM-1) |
| Egress no-emit-on-crash + receipt counts (4b) | **Validated** (error-text finding TM-7 amends the receipt row) |
| basis ≠ authority; SOURCE-ROLE stamping; explicit-event ratification (3) | **Validated in structure; two amendments:** `USER_RATIFIED` → `LOCAL_RATIFIED` (TM-2); role-evidence set instead of first-wins role (TM-4) |
| Ratification journal reader (3) | **Amendment required:** integrity degradation, fail-closed (TM-3) |

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

## 7. Post-review fix ordering (restates the reviewer's instruction)

1. Authority + scanner P1s (TM-1..4) — after this document is
   reviewed.
2. Receipt-schema + scoped-why P2s (TM-5, TM-6) and error-code TM-7.
3. Remaining E-6 units: retention (containment + symlink checks,
   dry-run + confirm), PF-16/16b, PF-17 security regression suite
   (which absorbs every TC above).
4. E-6 re-review.
5. Only then: eligibility (PF-13) and matcher (PF-21) — Loops 5–6 stay
   held. No live hook, no paid run, no parked merge.
