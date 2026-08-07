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
# 1.2: facts additionally carry SOURCE-ROLE (who wrote the text the
# fact was extracted from). Provenance change only — identities of
# previously extracted facts are unchanged by construction.
EXTRACTOR_VERSION = "tp/1.2"

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

    Basis is EXTRACTION MECHANICS, never authority: ``marker_stated``
    says a ``Decision:`` marker matched, not who wrote it — an
    assistant emits those markers routinely. Who wrote the text is
    :class:`SourceRole`; what standing that gives the fact is
    :class:`Authority`.
    """

    MARKER_STATED = "marker_stated"        # Decision:/Constraint:/ctx-incident:
    USER_IMPERATIVE = "user_imperative"    # user-turn constraint patterns
    LITERAL_EXTRACTOR = "literal_extractor"
    TOOL_OBSERVED = "tool_observed"        # reserved: no v1.1 producer
    STRUCTURAL = "structural"              # files, tasks, errors, tool runs
    INFERRED = "inferred"                  # decision verb patterns


class SourceRole(str, Enum):
    """Who authored the text a fact was extracted from.

    Stamped by the transcript parser (extractor tp/1.2+) from the turn
    type it is reading — never guessed from content. Facts extracted
    before stamping existed carry no role and must be treated as
    :attr:`UNKNOWN`.
    """

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"            # tool_result content (errors, outputs)
    UNKNOWN = "unknown"      # legacy rows predate stamping


class Authority(str, Enum):
    """What standing a fact has for automatic use.

    Derived deterministically from :class:`SourceRole` plus explicit
    ratification events — never from extraction basis, git presence,
    or a marker. ``USER_RATIFIED`` is reachable ONLY through a
    recorded ratification event referencing the fact_id.
    """

    USER_STATED = "user_stated"          # user-authored text
    USER_RATIFIED = "user_ratified"      # explicit ratification event
    TOOL_OBSERVED = "tool_observed"      # tool-emitted content
    AGENT_CANDIDATE = "agent_candidate"  # assistant-authored
    LEGACY_UNKNOWN = "legacy_unknown"    # no source_role recorded


def derive_authority(source_role: str, ratified: bool = False) -> Authority:
    """Deterministic authority from provenance.

    ``ratified`` must come from an explicit ratification event (see
    ``ctxpack.agent.ratification``); passing ``True`` from anywhere
    else — a merge, a marker, a hunch — is a policy violation, not a
    shortcut. Rejection is not an authority level: a rejected fact
    keeps its derived authority and is excluded by eligibility policy.
    """
    if ratified:
        return Authority.USER_RATIFIED
    role = str(source_role or "")
    if role == SourceRole.USER.value:
        return Authority.USER_STATED
    if role == SourceRole.ASSISTANT.value:
        return Authority.AGENT_CANDIDATE
    if role == SourceRole.TOOL.value:
        return Authority.TOOL_OBSERVED
    return Authority.LEGACY_UNKNOWN


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
