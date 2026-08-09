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
    """The SOURCE-PROVENANCE axis of a fact's standing.

    PF-11 v2.1 (approved 2026-08-09): authority is four SEPARATE axes
    — source provenance (this enum), local intent marker
    (ratification events; ``LOCAL_RATIFIED``), owner approval
    (UNSATISFIABLE in v1 — no trusted human channel exists; no value
    on any other axis substitutes for it), and tool evidence/
    freshness (evidence about the world, never authority about
    intent). There is deliberately NO total ordering across axes and
    no ``user_ratified`` member: the local CLI is not a human, so a
    ratification event carries no security standing beyond
    ``AGENT_CANDIDATE`` (the same actor can mint both). Under trust
    assumption TA-1, ``USER_STATED`` means user-per-transcript.
    """

    USER_STATED = "user_stated"          # user-authored text (per TA-1)
    TOOL_OBSERVED = "tool_observed"      # tool-emitted content
    AGENT_CANDIDATE = "agent_candidate"  # assistant-authored
    LEGACY_UNKNOWN = "legacy_unknown"    # no source_role recorded


# The local-intent-marker axis (ratification events). A bookkeeping
# signal, never security evidence — see ``ctxpack.agent.ratification``.
LOCAL_RATIFIED = "local_ratified"

# The owner-approval axis has exactly one value in v1. Gates that
# require owner approval must report it rather than accept a proxy.
OWNER_APPROVAL_UNAVAILABLE = "unavailable"


def derive_authority(source_role: str) -> Authority:
    """Deterministic source-provenance axis from the stamped role.

    Ratification is a DIFFERENT axis and deliberately not a parameter:
    folding it in here rebuilt the total ordering PF-11 forbids.
    """
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
