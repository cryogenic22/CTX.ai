"""Recursive descent parser for .ctx files.

Line-oriented: splits input into lines, then classifies and consumes them.
Supports three conformance levels:
  Level 1 — header only
  Level 2 — header + body structure (sections, KV, lists, quoted blocks)
  Level 3 — Level 2 + operator extraction + cross-ref parsing
"""

from __future__ import annotations

import re
from typing import Optional, Union

from .errors import ParseError, Span
from .model import (
    BodyElement,
    CTXDocument,
    Header,
    InlineList,
    KeyValue,
    Layer,
    NumberedItem,
    PlainLine,
    Provenance,
    QuotedBlock,
    Section,
)

# ── Regex patterns ──

_MAGIC_RE = re.compile(r"^(§CTX|\$CTX)\s+")
_VERSION_RE = re.compile(r"^v(\d+\.\d+)")
_LAYER_RE = re.compile(r"^(L[0-3]|MANIFEST)(?:\s|$)")
_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.+)$")
_SECTION_RE = re.compile(r"^(\s*)(±|##)(\d+\s+)?([A-Z][A-Z0-9_-]*)(.*)$")
_NUMBERED_RE = re.compile(r"^(\d+)\.(.+)$")
_PROVENANCE_RE = re.compile(r"^SRC:(.+)$")
_TRIPLE_BACKTICK = "```"


def parse(
    text: str,
    *,
    level: int = 2,
    filename: Optional[str] = None,
) -> CTXDocument:
    """Parse a .ctx file into a CTXDocument AST.

    Args:
        text: The .ctx file contents.
        level: Conformance level (1=header-only, 2=structural, 3=full).
        filename: Optional filename for error messages.

    Returns:
        A CTXDocument with header and (if level >= 2) body.
    """
    if level not in (1, 2, 3):
        raise ValueError(f"level must be 1, 2, or 3, got {level}")

    parser = _Parser(text, level=level, filename=filename)
    doc = parser.parse()
    # Store warnings on the document for validator to pick up
    object.__setattr__(doc, "_parser_warnings", parser.warnings)
    return doc


class _Parser:
    """Internal parser state machine."""

    def __init__(
        self,
        text: str,
        *,
        level: int = 2,
        filename: Optional[str] = None,
    ):
        self._text = text
        self._level = level
        self._filename = filename
        self._lines: list[str] = text.split("\n")
        if self._lines and self._lines[-1] == "":
            self._lines.pop()
        self._pos = 0
        self.warnings: list[str] = []  # non-fatal parse warnings

    @property
    def _lineno(self) -> int:
        return self._pos + 1

    def _peek(self) -> Optional[str]:
        if self._pos < len(self._lines):
            return self._lines[self._pos]
        return None

    def _advance(self) -> str:
        line = self._lines[self._pos]
        self._pos += 1
        return line

    def _at_end(self) -> bool:
        return self._pos >= len(self._lines)

    def _is_blank(self, line: str) -> bool:
        return line.strip() == ""

    def _error(self, msg: str, line: Optional[int] = None) -> ParseError:
        span = Span.at(line or self._lineno)
        return ParseError(msg, span=span, filename=self._filename)

    # ── Public entry ──

    def parse(self) -> CTXDocument:
        header = self._parse_header()
        body: tuple[Union[Section, BodyElement], ...] = ()
        if self._level >= 2 and not self._at_end():
            body = tuple(self._parse_body(owner_indent=-1))
        return CTXDocument(header=header, body=body, source_text=self._text)

    # ── Header parsing (Level 1) ──

    def _parse_header(self) -> Header:
        if self._at_end():
            raise self._error("Empty file")

        status_line = self._advance()
        magic, version, layer, status_fields = self._parse_status_line(
            status_line, lineno=1
        )

        metadata: list[KeyValue] = []
        header_end = 1
        while not self._at_end():
            line = self._peek()
            assert line is not None
            if self._is_blank(line):
                self._advance()
                break
            raw = self._advance()
            header_end = self._lineno
            kvs = self._parse_header_line(raw, lineno=self._lineno - 1)
            metadata.extend(kvs)

        return Header(
            magic=magic,
            version=version,
            layer=layer,
            status_fields=tuple(status_fields),
            metadata=tuple(metadata),
            span=Span.lines(1, header_end),
        )

    def _parse_status_line(
        self, line: str, lineno: int
    ) -> tuple[str, str, Layer, list[KeyValue]]:
        m = _MAGIC_RE.match(line)
        if not m:
            raise self._error(
                f"Expected §CTX or $CTX magic, got: {line!r}", lineno
            )
        magic = m.group(1)
        rest = line[m.end():]

        m = _VERSION_RE.match(rest)
        if not m:
            raise self._error(
                f"Expected version (e.g. v1.0), got: {rest!r}", lineno
            )
        version = m.group(1)
        rest = rest[m.end():].lstrip()

        m = _LAYER_RE.match(rest)
        if not m:
            raise self._error(
                f"Expected layer (L0-L3 or MANIFEST), got: {rest!r}", lineno
            )
        layer_str = m.group(1)
        try:
            layer = Layer(layer_str)
        except ValueError:
            raise self._error(f"Invalid layer: {layer_str!r}", lineno)
        rest = rest[m.end():].lstrip()

        status_fields: list[KeyValue] = []
        if rest:
            for token in rest.split():
                kv = self._parse_kv_token(token, lineno)
                if kv:
                    status_fields.append(kv)

        return magic, version, layer, status_fields

    def _parse_kv_token(self, token: str, lineno: int) -> Optional[KeyValue]:
        idx = token.find(":")
        if idx <= 0:
            return None
        return KeyValue(key=token[:idx], value=token[idx + 1:], span=Span.at(lineno))

    def _parse_header_line(self, line: str, lineno: int) -> list[KeyValue]:
        results: list[KeyValue] = []
        tokens = line.split()
        all_kv = all(":" in t and t.index(":") > 0 for t in tokens)

        if all_kv and len(tokens) > 1:
            for token in tokens:
                kv = self._parse_kv_token(token, lineno)
                if kv:
                    results.append(kv)
        else:
            m = _KV_RE.match(line)
            if m:
                results.append(
                    KeyValue(key=m.group(1), value=m.group(2), span=Span.at(lineno))
                )
            else:
                results.append(
                    KeyValue(key="_RAW", value=line, span=Span.at(lineno))
                )

        return results

    # ── Body parsing (Level 2) ──

    def _parse_body(
        self, owner_indent: int
    ) -> list[Union[Section, BodyElement]]:
        """Parse body elements owned by a section at owner_indent.

        A section at indent N owns:
        - All non-section lines until the next section at indent <= N
        - All subsections at indent > N (which recursively own their children)

        owner_indent=-1 means top-level (owns everything).
        """
        elements: list[Union[Section, BodyElement]] = []

        while not self._at_end():
            line = self._peek()
            assert line is not None

            if self._is_blank(line):
                self._advance()
                continue

            # Check for section marker
            sm = _SECTION_RE.match(line)
            if sm:
                sec_indent = len(sm.group(1))
                if sec_indent <= owner_indent:
                    # Section at same or lesser indent — belongs to parent
                    break
                section = self._parse_section(sm)
                elements.append(section)
                continue

            # Non-section line: belongs to current owner unless it's
            # dedented past our content level.
            # For a section at indent N, content lines are at indent >= N.
            # For top-level (owner_indent=-1), all lines belong here.
            stripped = line.lstrip()
            line_indent = len(line) - len(stripped)
            if owner_indent >= 0 and line_indent < owner_indent:
                # Dedented past section — belongs to parent
                break

            self._advance()
            lineno = self._lineno - 1
            elem = self._classify_line(stripped, lineno)
            elements.append(elem)

        return elements

    def _parse_section(self, match: re.Match) -> Section:
        indent_str = match.group(1)
        indent = len(indent_str)
        depth_marker = match.group(3)  # e.g. "2 " or None
        name = match.group(4)
        subtitle_str = match.group(5).strip()
        subtitles = tuple(subtitle_str.split()) if subtitle_str else ()

        start_line = self._lineno
        self._advance()  # consume section marker line

        # Parse children — this section owns everything indented deeper
        children = self._parse_body(owner_indent=indent)

        # Use explicit depth marker if present, otherwise infer from indent
        if depth_marker:
            depth = int(depth_marker.strip())
        else:
            depth = indent // 2

        return Section(
            name=name,
            subtitles=subtitles,
            indent=indent,
            depth=depth,
            children=tuple(children),
            span=Span.lines(start_line, self._lineno),
        )

    def _classify_line(self, line: str, lineno: int) -> BodyElement:
        # Triple-backtick quoted block
        if line.startswith(_TRIPLE_BACKTICK):
            return self._parse_quoted_block(line, lineno)

        # Provenance
        m = _PROVENANCE_RE.match(line)
        if m:
            return self._parse_provenance(m, lineno)

        # Numbered item: {n}.text
        m = _NUMBERED_RE.match(line)
        if m:
            return NumberedItem(
                number=int(m.group(1)),
                text=m.group(2),
                span=Span.at(lineno),
            )

        # Key-value pair (with multi-line bracket balancing)
        m = _KV_RE.match(line)
        if m:
            key = m.group(1)
            value = m.group(2)
            value = self._balance_brackets(value)
            return KeyValue(key=key, value=value, span=Span.at(lineno))

        # Sequence list: KEY[ ... ] spanning multiple lines (no colon)
        seq_m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\[(.*)$", line)
        if seq_m:
            key = seq_m.group(1)
            rest = "[" + seq_m.group(2)
            rest = self._balance_brackets(rest)
            return KeyValue(key=key, value=rest, span=Span.at(lineno))

        # Inline list: [item, item, ...]
        if line.startswith("[") and line.endswith("]"):
            inner = line[1:-1]
            items = tuple(item.strip() for item in inner.split(",") if item.strip())
            return InlineList(items=items, span=Span.at(lineno))

        # Plain line (fallback)
        return PlainLine(text=line, span=Span.at(lineno))

    def _parse_quoted_block(self, first_line: str, lineno: int) -> QuotedBlock:
        lang = first_line[3:].strip()
        lines: list[str] = []
        closed = False
        while not self._at_end():
            line = self._advance()
            if line.strip().startswith(_TRIPLE_BACKTICK):
                closed = True
                break
            lines.append(line)
        if not closed:
            self.warnings.append(
                f"W005:line {lineno}: Unclosed triple-backtick block (consumed to EOF)"
            )
        return QuotedBlock(
            content="\n".join(lines),
            lang=lang,
            span=Span.lines(lineno, self._lineno),
        )

    def _parse_provenance(self, match: re.Match, lineno: int) -> Provenance:
        ref = match.group(1)
        path = ref
        line_range = ""
        if "#" in ref:
            path, line_range = ref.split("#", 1)
        return Provenance(
            source=ref, path=path, line_range=line_range, span=Span.at(lineno)
        )

    def _balance_brackets(self, value: str) -> str:
        start_line = self._lineno
        depth = 0
        in_backtick = False
        for ch in value:
            if ch == "`":
                in_backtick = not in_backtick
            elif not in_backtick:
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1

        if depth <= 0:
            return value

        parts = [value]
        while depth > 0 and not self._at_end():
            line = self._advance()
            parts.append(line)
            for ch in line:
                if ch == "`":
                    in_backtick = not in_backtick
                elif not in_backtick:
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1

        if depth > 0:
            self.warnings.append(
                f"W004:line {start_line}: Unclosed brackets in value"
            )

        return "\n".join(parts)
