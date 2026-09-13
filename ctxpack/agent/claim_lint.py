"""B6 claim-verb lint (TC-15, TM-12).

While CTX runs in advisory mode only, no product claim may promise it
can **guarantee / prevent / block** a malicious or same-privilege
actor — the B6 discipline is surface / flag / audit / degrade, never
guarantee / prevent / block. This lint is the executable form of
TC-15.

Precision-first, like every other gate here: a naive substring search
drowns in the threat model's own text (which says "never guarantee,
prevent, block" dozens of times). A sentence is flagged ONLY when all
four hold:

1. a security verb in claim form (guarantee/prevent/block + inflections);
2. a PRODUCT-SUBJECT token (CTX, ctxpack, redaction, the scanner, the
   gate, the ledger, …) — the sentence is the SYSTEM asserting a
   capability, not prose that merely mentions "a block verdict" or
   "injected blocks";
3. an adversary/threat token (malicious, attacker, adversary,
   same-privilege, tamper, prompt-injected, …) — the claim is scoped
   to an actor B6 makes no promise against;
4. NO negation in the sentence (no / never / not / cannot / must not /
   "claims no" / "makes no") — a stated LIMITATION is the opposite of
   a violation.

So "CTX claims no guarantee against a malicious agent" passes (negated)
and "our redaction prevents a malicious agent from exfiltrating keys"
fails (affirmative, adversary-scoped, product subject). Quoted threat
text describing what NO control can do is negated by construction and
passes; the verb-list definition itself ("never guarantee, prevent,
block") is negated and passes; "a BLOCK verdict" / "harness-injected
blocks" carry no product subject and pass.

Sentences are reassembled from hard-wrapped markdown (single newlines
become spaces) so a negation one line above its verb still exempts.

The heuristic is deliberately conservative — it can MISS an
adversary-scoped claim phrased without a threat token; the registry
records that textual references are not proof. It is tuned to never
FALSE-POSITIVE on the current doc set, so a green lint means "no
detected violation", not "proven claim-safe".
"""

from __future__ import annotations

import os
import re
import subprocess

# The product-claim surface: rendered docs an external reader treats as
# claims. Source code and tests are out of scope (they carry the verbs
# as identifiers and test strings).
DOC_ROOTS = ("README.md", "docs", "paper")

# Full guarantee/prevent/block morphology incl. participles (RF4:
# "preventing" slipped through) — a claim inflection is still a claim.
_SECURITY_VERB = re.compile(
    r"\b(guarantee|guarantees|guaranteed|guaranteeing|"
    r"prevent|prevents|prevented|preventing|"
    r"block|blocks|blocked|blocking)\b", re.IGNORECASE)

# The system asserting the capability — without this the verbs fire on
# prose that merely mentions them ("a BLOCK verdict", "injected blocks").
# Checked at SENTENCE level (the subject may be "CTX" in one clause and
# "it" in the claim clause).
_PRODUCT = re.compile(
    r"\b(ctx|ctxpack|redaction|redact|the scanner|the gate|the ledger|"
    r"the checkpoint|the packer|hydration|the receipt|the memory)\b",
    re.IGNORECASE)

# "block" also has innocent noun senses (code block, key block,
# conventions block); the adversary + product tokens filter those out
# without POS tagging. Adversary plurals covered (RF4).
_ADVERSARY = re.compile(
    r"\b(malicious|attackers?|adversar(?:y|ies|ial)|same-privilege|"
    r"prompt-inject(?:ed|ion)|tamper(?:ing|ed|s)?|exfiltrat(?:e|es|ion)|"
    r"threat actors?|hostile)\b", re.IGNORECASE)

_NEGATION = re.compile(
    r"\b(no|not|never|cannot|can't|without|neither|nor|none)\b"
    r"|\bmust not\b|\bdo(?:es)? not\b|\bmakes no\b|\bclaims no\b"
    r"|\bno longer\b", re.IGNORECASE)

# Clause boundaries: `;` `:` and contrastive / coordinating
# conjunctions — deliberately NOT bare commas. Negation is evaluated
# per-CLAUSE (RF4: `_NEGATION` was sentence-global, so a "not" in one
# clause exempted a claim in another — "CTX does not merely surface
# attacks; it prevents a malicious agent ..."). Commas are excluded
# because a coordinated verb LIST shares one head negation ("CTX must
# not claim it can guarantee, prevent, or block malicious-agent
# actions") — splitting on the commas there would strand "or block
# <adversary>" from its governing "must not".
_CLAUSE_SPLIT = re.compile(
    r"[;:]|\b(?:but|however|yet|whereas|while|although|though)\b",
    re.IGNORECASE)

_FENCED_CODE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)


def _sentences(text: str):
    """Sentence/segment split over hard-wrapped markdown: single
    newlines become spaces (so a wrapped sentence stays one window),
    splitting on blank lines, sentence punctuation, and markdown table
    cell borders. Fenced code blocks are removed first — a code example
    is not a product claim (RF4 benign control)."""
    text = _FENCED_CODE.sub(" ", text)
    for para in re.split(r"\n\s*\n", text):
        joined = re.sub(r"\s*\n\s*", " ", para)
        for seg in re.split(r"(?<=[.!?])\s+|\s\|\s", joined):
            seg = seg.strip()
            if seg:
                yield seg


def lint_text(text: str) -> "list[str]":
    """Offending sentences in one document's text; empty = clean.

    A sentence is flagged when it (1) names the product AND (2) contains
    a CLAUSE with a security verb + an adversary token + NO clause-local
    negation. Product is sentence-scoped (the subject can be a pronoun
    in the claim clause); negation is clause-scoped (RF4)."""
    hits: "list[str]" = []
    for seg in _sentences(text):
        if not _PRODUCT.search(seg):
            continue
        for clause in _CLAUSE_SPLIT.split(seg):
            if not clause:
                continue
            if (_SECURITY_VERB.search(clause)
                    and _ADVERSARY.search(clause)
                    and not _NEGATION.search(clause)):
                hits.append(seg)
                break
    return hits


def _doc_files(repo_root: str, roots=DOC_ROOTS) -> "list[str]":
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--", *roots],
            cwd=repo_root, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"doc enumeration failed: {type(e).__name__}")
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files exited {proc.returncode}")
    return sorted(n for n in proc.stdout.decode("utf-8").split("\0")
                  if n.endswith(".md"))


def run_lint(repo_root: str, roots=DOC_ROOTS) -> "list[str]":
    """``["<relpath>: <offending sentence>", …]``; empty = no detected
    B6 claim-verb violation. Enumeration failure raises — a lint that
    could not run must never report clean."""
    findings: "list[str]" = []
    for rel in _doc_files(repo_root, roots):
        try:
            with open(os.path.join(repo_root, rel), encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            raise RuntimeError(f"doc unreadable: {rel}")
        for seg in lint_text(text):
            findings.append(f"{rel}: {seg}")
    return findings
