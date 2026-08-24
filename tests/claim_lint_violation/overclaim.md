# B6 claim-lint negative control — DO NOT "fix" this file.

This document lives OUTSIDE the linted doc roots and is fed to the
claim lint explicitly by tests/test_claim_lint.py, which REQUIRES the
lint to reject it — a lint never observed failing is not a lint. The
sentence below is a deliberate B6 violation: an affirmative,
adversary-scoped product claim while CTX is advisory-mode only.

CTX guarantees that redaction prevents a malicious agent from ever
reading a banked secret, and the ledger blocks a same-privilege
attacker from rewriting a decision.

RF4 mixed-clause overclaim (the negation belongs to another clause):
CTX does not merely surface attacks; it prevents a malicious agent
from tampering with the ledger.

RF4 participle overclaim (inflected verb): CTX is preventing a
malicious agent from exfiltrating the banked secret, and it is
blocking attackers from rewriting decisions.
