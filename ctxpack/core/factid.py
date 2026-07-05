"""Fact identity and extraction basis — the v1.1 substrate primitives.

Contract: docs/spec-v1.1-fact-substrate.md. Zero dependencies, pure
functions — same inputs, same id, forever.

Identity is canonical content: (scope, kind, key, normalized value).
The extractor rule/version is deliberately NOT part of identity — it is
provenance (``BASIS`` / ``EXTRACTOR`` on the source record). Hashing it
would mint new ids for identical facts on every parser release and
silently break cross-session dedup and supersession chains.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum

# Unit separator: cannot appear in normalized text, so field boundaries
# can never be forged by crafted values ("a|b" tricks).
_SEP = "\x1f"
_WS_RE = re.compile(r"\s+")
# trimmed from the ENDS of values only — interior punctuation is meaning
_EDGE_PUNCT = " \t\r\n.,:;!?\"'`*_-—"

# Stamped into per-source provenance, never into fact_id.
EXTRACTOR_VERSION = "tp/1.1"

# rank = fold(events, policy); v0 is today's behavior — static
# extraction-time priors, no updates. Recorded in every checkpoint
# journal row so future folds are A/B-testable against the same log.
RANK_POLICY = "rank/v0-static-priors"

EVENTS_SCHEMA = "ctx-events/v1"


class FactBasis(str, Enum):
    """How a fact was extracted — an auditable enum, never a float.

    ``inferred`` is the only basis allowed to be wrong about whether
    this is a fact at all (best-effort verb patterns); every other
    basis is structurally anchored.
    """

    MARKER_STATED = "marker_stated"        # Decision:/Constraint:/ctx-incident:
    USER_IMPERATIVE = "user_imperative"    # user-turn constraint patterns
    LITERAL_EXTRACTOR = "literal_extractor"
    TOOL_OBSERVED = "tool_observed"        # reserved: no v1.1 producer
    STRUCTURAL = "structural"              # files, tasks, errors, tool runs
    INFERRED = "inferred"                  # decision verb patterns


def normalize_value(value: str) -> str:
    """Lowercase, collapse whitespace, trim edge punctuation."""
    text = _WS_RE.sub(" ", str(value)).strip().lower()
    return text.strip(_EDGE_PUNCT)


def fact_id(kind: str, value: str, key: str = "", scope: str = "") -> str:
    """Stable 16-hex identity for a fact.

    scope: reserved for cross-repo identity — empty for repo-local
    facts (a ledger lives inside its repo, so cross-repo collision is
    impossible within one ledger). A revised value is a NEW fact; the
    key chains versions for the future supersession DAG.
    """
    canon = _SEP.join((
        str(scope),
        str(kind).strip().upper(),
        normalize_value(key),
        normalize_value(value),
    ))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]
