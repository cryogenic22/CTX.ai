"""AST diff engine for .ctx documents.

Walks two CTXDocuments in parallel, reporting added/removed/changed
sections and key-values. Output uses .ctx-flavored diff format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from .model import (
    BodyElement,
    CTXDocument,
    KeyValue,
    PlainLine,
    Provenance,
    Section,
)


@dataclass
class DiffEntry:
    """A single diff entry."""
    kind: str  # "added", "removed", "changed"
    path: str  # e.g. "±ENTITY-CUSTOMER/IDENTIFIER"
    old_value: str = ""
    new_value: str = ""


@dataclass
class DiffResult:
    """Result of comparing two CTXDocuments."""
    entries: list[DiffEntry] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return len(self.entries) > 0

    @property
    def added_count(self) -> int:
        return sum(1 for e in self.entries if e.kind == "added")

    @property
    def removed_count(self) -> int:
        return sum(1 for e in self.entries if e.kind == "removed")

    @property
    def changed_count(self) -> int:
        return sum(1 for e in self.entries if e.kind == "changed")


def diff_documents(old: CTXDocument, new: CTXDocument) -> DiffResult:
    """Compare two CTXDocuments and return a DiffResult."""
    result = DiffResult()

    # Compare headers
    _diff_headers(old, new, result)

    # Compare body sections
    _diff_bodies(old.body, new.body, "", result)

    return result


def _diff_headers(old: CTXDocument, new: CTXDocument, result: DiffResult) -> None:
    """Compare header fields."""
    old_fields = {kv.key: kv.value for kv in old.header.all_fields}
    new_fields = {kv.key: kv.value for kv in new.header.all_fields}

    for key in sorted(set(old_fields) | set(new_fields)):
        old_val = old_fields.get(key)
        new_val = new_fields.get(key)
        if old_val is None:
            result.entries.append(DiffEntry(
                kind="added", path=f"HEADER/{key}", new_value=new_val or "",
            ))
        elif new_val is None:
            result.entries.append(DiffEntry(
                kind="removed", path=f"HEADER/{key}", old_value=old_val,
            ))
        elif old_val != new_val:
            result.entries.append(DiffEntry(
                kind="changed", path=f"HEADER/{key}",
                old_value=old_val, new_value=new_val,
            ))


def _diff_bodies(
    old_elems: tuple[Union[Section, BodyElement], ...],
    new_elems: tuple[Union[Section, BodyElement], ...],
    prefix: str,
    result: DiffResult,
) -> None:
    """Compare body elements, matching sections by name."""
    old_sections: dict[str, Section] = {}
    old_kvs: dict[str, str] = {}
    old_lines: list[str] = []

    for elem in old_elems:
        if isinstance(elem, Section):
            old_sections[elem.name] = elem
        elif isinstance(elem, KeyValue):
            old_kvs[elem.key] = elem.value
        elif isinstance(elem, PlainLine):
            old_lines.append(elem.text)

    new_sections: dict[str, Section] = {}
    new_kvs: dict[str, str] = {}
    new_lines: list[str] = []

    for elem in new_elems:
        if isinstance(elem, Section):
            new_sections[elem.name] = elem
        elif isinstance(elem, KeyValue):
            new_kvs[elem.key] = elem.value
        elif isinstance(elem, PlainLine):
            new_lines.append(elem.text)

    # Compare sections
    for name in sorted(set(old_sections) | set(new_sections)):
        path = f"{prefix}±{name}" if prefix else f"±{name}"
        if name not in old_sections:
            result.entries.append(DiffEntry(kind="added", path=path))
        elif name not in new_sections:
            result.entries.append(DiffEntry(kind="removed", path=path))
        else:
            _diff_bodies(
                old_sections[name].children,
                new_sections[name].children,
                path + "/",
                result,
            )

    # Compare key-values
    for key in sorted(set(old_kvs) | set(new_kvs)):
        path = f"{prefix}{key}" if prefix else key
        old_val = old_kvs.get(key)
        new_val = new_kvs.get(key)
        if old_val is None:
            result.entries.append(DiffEntry(
                kind="added", path=path, new_value=new_val or "",
            ))
        elif new_val is None:
            result.entries.append(DiffEntry(
                kind="removed", path=path, old_value=old_val,
            ))
        elif old_val != new_val:
            result.entries.append(DiffEntry(
                kind="changed", path=path,
                old_value=old_val, new_value=new_val,
            ))

    # Compare plain lines (set-based)
    old_set = set(old_lines)
    new_set = set(new_lines)
    for line in sorted(old_set - new_set):
        result.entries.append(DiffEntry(
            kind="removed", path=f"{prefix}(line)", old_value=line,
        ))
    for line in sorted(new_set - old_set):
        result.entries.append(DiffEntry(
            kind="added", path=f"{prefix}(line)", new_value=line,
        ))


def format_diff(result: DiffResult) -> str:
    """Format a DiffResult as .ctx-flavored diff text."""
    lines: list[str] = []

    for entry in result.entries:
        if entry.kind == "added":
            if entry.new_value:
                lines.append(f"+ {entry.path}:{entry.new_value}")
            else:
                lines.append(f"+ {entry.path}")
        elif entry.kind == "removed":
            if entry.old_value:
                lines.append(f"- {entry.path}:{entry.old_value}")
            else:
                lines.append(f"- {entry.path}")
        elif entry.kind == "changed":
            lines.append(f"~ {entry.path}:{entry.old_value} → {entry.new_value}")

    if not lines:
        lines.append("(no changes)")

    return "\n".join(lines)
