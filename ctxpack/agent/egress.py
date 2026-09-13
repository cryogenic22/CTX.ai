"""Final-serialization egress scan for agent-facing read surfaces.

PF-14 gave the SessionStart hook an egress scan; Finding 6 (2026-08-23)
showed that was not the final boundary — `ctxpack session resume`
printed a raw legacy-gist secret because CLI and MCP read surfaces
emitted unscanned bytes. This module is the ONE shared choke point:
every session-read emission (CLI `session resume|recall|why|timeline|
decisions|literals|graph|stats` and the MCP twins) passes its FINAL
serialized text through :func:`scan_out` immediately before leaving
the process.

Fail-closed with a stable, non-sensitive error: if the scanner cannot
run, nothing is emitted and the caller reports
:data:`EGRESS_SCAN_FAILED` — an unscanned byte never reaches the agent
because the scan "probably would have passed".

Scope note (honest boundary): this covers the SESSION-LEDGER read
surfaces the threat model names. Corpus-packing tools (ctx/pack,
ctx/format, code-pack) serialize caller-chosen source content, a
different trust boundary tracked separately in E-6.
"""

from __future__ import annotations

EGRESS_SCAN_FAILED = "egress_scan_failed"


class EgressError(Exception):
    """The final output could not be scanned; the caller must emit
    NOTHING except the stable code. Deliberately carries no message —
    there is nothing safe to say beyond the code."""

    code = EGRESS_SCAN_FAILED

    def __init__(self):
        super().__init__(EGRESS_SCAN_FAILED)


def scan_out(text: str) -> str:
    """Redact the final serialized output, or raise :class:`EgressError`.

    Same scanner, same type-only replacement as every other boundary
    (one vocabulary, PF-12/PF-14); a scanner crash raises rather than
    letting the unscanned bytes through."""
    try:
        from ..core.redaction import redact
        safe, _counts = redact(text)
        return safe
    except Exception:  # noqa: BLE001 — fail closed, emit nothing
        raise EgressError()
