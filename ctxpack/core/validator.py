"""Validation rules for .ctx documents.

Returns a list of Diagnostics, never raises.
"""

from __future__ import annotations

import re

from .errors import Diagnostic, DiagnosticLevel, Span
from .model import CTXDocument, Layer, Section

_REQUIRED_HEADER_FIELDS = {"DOMAIN", "COMPRESSED", "SOURCE_TOKENS"}
_KNOWN_HEADER_FIELDS = _REQUIRED_HEADER_FIELDS | {
    "SCOPE",
    "AUTHOR",
    "CTX_TOKENS",
    "SOURCE",
    "RATIO",
    "GEN",
    "HASH",
    "PROVENANCE",
    "SCHEMA",
    "TURNS",
}
_L3_REQUIRED_SECTIONS = {"ENTITIES", "PATTERNS", "CONSTRAINTS", "WARNINGS"}


def validate(doc: CTXDocument, *, level: int = 2) -> list[Diagnostic]:
    """Validate a CTXDocument and return diagnostics."""
    diags: list[Diagnostic] = []
    h = doc.header

    # E002: Invalid magic
    if h.magic not in ("§CTX", "$CTX"):
        diags.append(
            Diagnostic(
                DiagnosticLevel.ERROR,
                f"Invalid magic: {h.magic!r}, expected §CTX or $CTX",
                h.span,
                "E002",
            )
        )

    # E003: Invalid version format
    parts = h.version.split(".")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        diags.append(
            Diagnostic(
                DiagnosticLevel.ERROR,
                f"Invalid version format: {h.version!r}, expected M.m",
                h.span,
                "E003",
            )
        )

    # E004: Invalid layer — already validated by parser, but check anyway
    if not isinstance(h.layer, Layer):
        diags.append(
            Diagnostic(
                DiagnosticLevel.ERROR,
                f"Invalid layer value: {h.layer!r}",
                h.span,
                "E004",
            )
        )

    # E001: Missing required header fields
    present = {kv.key.upper() for kv in h.all_fields}
    for field in _REQUIRED_HEADER_FIELDS:
        if field not in present:
            diags.append(
                Diagnostic(
                    DiagnosticLevel.ERROR,
                    f"Missing required header field: {field}",
                    h.span,
                    "E001",
                )
            )

    # W001: Unknown header fields
    for kv in h.all_fields:
        if kv.key.upper() not in _KNOWN_HEADER_FIELDS and kv.key != "_RAW":
            diags.append(
                Diagnostic(
                    DiagnosticLevel.WARNING,
                    f"Unknown header field: {kv.key}",
                    kv.span,
                    "W001",
                )
            )

    # W004/W005: Parser warnings (unclosed brackets, unclosed backtick blocks)
    parser_warnings = getattr(doc, "_parser_warnings", [])
    for pw in parser_warnings:
        code = pw.split(":")[0] if ":" in pw else "W004"
        msg = pw.split(":", 2)[-1].strip() if ":" in pw else pw
        # Extract line number if present
        line_match = re.search(r"line (\d+)", pw)
        span = Span.at(int(line_match.group(1))) if line_match else None
        diags.append(
            Diagnostic(DiagnosticLevel.WARNING, msg, span, code)
        )

    if level < 2:
        return diags

    # E005: Missing header/body separator (blank line)
    # If the parser got here, the blank line was present (or file is header-only)
    # We check if the source text has the blank line
    if doc.body and doc.source_text:
        lines = doc.source_text.split("\n")
        found_blank = False
        for line in lines[1:]:  # skip status line
            if line.strip() == "":
                found_blank = True
                break
            # Check if it's a body line (section marker)
            if line.lstrip().startswith("±") or line.lstrip().startswith("##"):
                break
        if not found_blank:
            diags.append(
                Diagnostic(
                    DiagnosticLevel.ERROR,
                    "Missing blank line between header and body",
                    Span.at(1),
                    "E005",
                )
            )

    # W002: Section names with underscores
    _check_sections(doc.body, diags)

    # W003: Non-canonical field ordering
    field_keys = [kv.key.upper() for kv in h.all_fields]
    canonical_order = _canonical_order(field_keys)
    if field_keys != canonical_order:
        diags.append(
            Diagnostic(
                DiagnosticLevel.WARNING,
                "Header fields not in canonical order (required → recommended → custom)",
                h.span,
                "W003",
            )
        )

    # E010: L3 missing required sections
    if h.layer == Layer.L3:
        section_names = _collect_section_names(doc.body)
        for slot in _L3_REQUIRED_SECTIONS:
            if slot not in section_names:
                diags.append(
                    Diagnostic(
                        DiagnosticLevel.ERROR,
                        f"L3 file missing required section: ±{slot}",
                        None,
                        "E010",
                    )
                )

    return diags


def _check_sections(elements, diags: list[Diagnostic]) -> None:
    """Recursively check section naming conventions."""
    for elem in elements:
        if isinstance(elem, Section):
            if "_" in elem.name:
                diags.append(
                    Diagnostic(
                        DiagnosticLevel.WARNING,
                        f"Section name '{elem.name}' uses underscore (prefer hyphens)",
                        elem.span,
                        "W002",
                    )
                )
            _check_sections(elem.children, diags)


def _collect_section_names(elements) -> set[str]:
    """Collect all section names recursively."""
    names: set[str] = set()
    for elem in elements:
        if isinstance(elem, Section):
            names.add(elem.name)
            names.update(_collect_section_names(elem.children))
    return names


def _canonical_order(keys: list[str]) -> list[str]:
    """Return keys in canonical order."""
    required = [k for k in keys if k in _REQUIRED_HEADER_FIELDS]
    recommended = [k for k in keys if k in _KNOWN_HEADER_FIELDS and k not in _REQUIRED_HEADER_FIELDS]
    custom = [k for k in keys if k not in _KNOWN_HEADER_FIELDS]
    return required + recommended + custom
