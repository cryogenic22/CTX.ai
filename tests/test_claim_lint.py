"""TC-15 (TM-12/B6): the claim-verb lint.

Green-field unit — the module and fixture are absent on the parent.
The live-tree test is the GATE; the violation fixture is the committed
negative control the gate discipline requires."""

import os

import pytest

from ctxpack.agent.claim_lint import lint_text, run_lint

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIOLATION = os.path.join(REPO_ROOT, "tests", "claim_lint_violation",
                         "overclaim.md")


def test_committed_docs_carry_no_detected_b6_violation():
    """THE gate (TC-15): no committed doc makes an affirmative
    guarantee/prevent/block claim scoped to a malicious/same-privilege
    actor while advisory mode is the only mode. Forward guard freezing
    the reviewed 2026-08-23 state."""
    findings = run_lint(REPO_ROOT)
    assert findings == [], "\n".join(findings)


def test_lint_rejects_the_committed_violation_fixture():
    """Can-fail: the planted overclaim (outside the linted roots) is
    caught — proof the lint is red-capable."""
    text = open(VIOLATION, encoding="utf-8").read()
    hits = lint_text(text)
    assert hits, "the negative control must trip the lint"


def test_lint_flags_affirmative_adversary_scoped_product_claims():
    for claim in (
        "Our redaction prevents a malicious agent from exfiltrating keys.",
        "CTX guarantees the ledger blocks a same-privilege attacker.",
        "ctxpack prevents a prompt-injected agent from tampering with "
        "the ledger.",
    ):
        assert lint_text(claim), claim


def test_lint_exempts_negations_quotes_and_non_security_senses():
    """The reviewer's exact distinction: quoted threat text, negated
    limitations, and non-security noun senses all pass."""
    for ok in (
        "CTX claims no guarantee against a malicious agent.",
        "surface, flag, audit, degrade, never guarantee, prevent, block",
        "No local control can prevent a malicious agent while the "
        "transcript is agent-writable.",
        "rendered outputs contain no\nguarantee/prevent/block claim "
        "scoped to malicious agents",           # wrapped negation
        "adversarial review agents returning a BLOCK verdict",
        "hardened against harness-injected blocks; each guard is "
        "adversarial",
        "the redaction scanner replaces a secret with a type-only "
        "marker",                                # product, no adversary
    ):
        assert lint_text(ok) == [], ok


def test_rf4_clause_local_negation_and_verb_morphology(tmp_path):
    """RF4 (Codex Finding 4, P2): negation is clause-local, not
    sentence-global, and the verb set covers participles + adversary
    plurals. Both reviewer probes were bypasses on the parent. RED on
    7ea3ba1."""
    # (a) mixed-clause: the negation belongs to a DIFFERENT clause
    assert lint_text(
        "CTX does not merely surface attacks; it prevents a malicious "
        "agent from tampering with the ledger.")
    # (b) participle morphology + adversary plural
    assert lint_text("CTX is preventing a malicious agent from tampering.")
    assert lint_text("CTX blocks malicious attackers from rewriting it.")
    assert lint_text("CTX is guaranteeing adversaries cannot... it "
                     "blocks adversaries from the ledger.")


def test_rf4_retains_benign_controls_incl_negated_verb_list(tmp_path):
    """RF4 (c): a coordinated verb LIST shares one head negation and
    must NOT be split into an affirmative clause — plus quoted-threat,
    genuine-limitation, BLOCK-verdict, and code-fence controls stay
    clean, and the LIVE docs remain zero-finding."""
    for ok in (
        # the exact live-doc shape the naive comma-split would trip
        "Until enforced mode exists, CTX must not claim it can "
        "guarantee, prevent, or block malicious-agent actions.",
        "CTX claims no guarantee against a malicious agent.",
        "No control in CTX can prevent a malicious agent while the "
        "transcript is writable.",
        "```\nCTX prevents a malicious agent\n```",   # code fence
        "adversarial review agents returning a BLOCK verdict",
    ):
        assert lint_text(ok) == [], ok
    assert run_lint(REPO_ROOT) == []                  # live docs clean


def test_enumeration_failure_raises_never_reports_clean(tmp_path):
    with pytest.raises(RuntimeError):
        run_lint(str(tmp_path))
