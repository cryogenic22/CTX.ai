"""Per-task contract schema for ``ctxpack verify``.

A contract is a JSON or TOML document. Loading is stdlib-only:
``json`` plus ``tomllib`` (3.11+), ``tomli`` when it is already
installed, or a deterministic subset parser on Python 3.10. Malformed
contracts raise ``ContractError`` and the verifier does not run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ContractError(ValueError):
    """The contract document is missing, unreadable, or invalid."""


# Stable finding codes the verifier can emit. Blocking lists may name
# only these; an unknown code is a contract error, not a silent no-op.
FINDING_CODES = frozenset({
    "ATTESTATION_SHA_MISMATCH",
    "CONSTRAINT_CONFLICT",
    "CONTRACT_RULE_VIOLATION",
    "STALE_IDENTIFIER",
    "SUPERSEDED_STILL_IN_CODE",
    "UNRECORDED_MARKER",
    "UNVERIFIED_CLAIM",
    "VERSION_PIN_DRIFT",
})

_CONTRACT_KEYS = frozenset({
    "allowed_paths",
    "attestation_sha_patterns",
    "blocking_codes",
    "flag_off_invariants",
    "forbidden_paths",
    "forbidden_vocabulary",
    "name",
    "pinned_versions",
    "require_attestation_sha",
    "require_test_evidence",
    "required_vocabulary",
})

_FLAG_KEYS = frozenset({"config_globs", "flag", "guarded_globs"})


@dataclass(frozen=True)
class FlagOffInvariant:
    """A feature flag that must stay off, and the files it guards."""

    flag: str
    config_globs: tuple[str, ...]
    guarded_globs: tuple[str, ...]


@dataclass(frozen=True)
class TaskContract:
    """Typed task contract. Every field is read by ``ctxpack verify``."""

    name: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    pinned_versions: tuple[tuple[str, str], ...]
    forbidden_vocabulary: tuple[tuple[str, tuple[str, ...]], ...]
    required_vocabulary: tuple[tuple[str, tuple[str, ...]], ...]
    flag_off_invariants: tuple[FlagOffInvariant, ...]
    require_attestation_sha: bool
    require_test_evidence: bool
    blocking_codes: tuple[str, ...]
    attestation_sha_patterns: tuple[str, ...]

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> "TaskContract":
        """Validate ``data`` and return a contract. Fail closed."""
        if not isinstance(data, Mapping):
            raise ContractError("contract root must be a table")
        unknown = sorted(set(data) - _CONTRACT_KEYS)
        if unknown:
            raise ContractError(
                "unknown contract field: " + ", ".join(unknown))
        name = _string(data.get("name", ""), "name")
        return TaskContract(
            name=name,
            allowed_paths=_str_tuple(data.get("allowed_paths", []),
                                     "allowed_paths"),
            forbidden_paths=_str_tuple(data.get("forbidden_paths", []),
                                       "forbidden_paths"),
            pinned_versions=_pin_pairs(data.get("pinned_versions", {})),
            forbidden_vocabulary=_vocab(data.get("forbidden_vocabulary", {}),
                                        "forbidden_vocabulary"),
            required_vocabulary=_vocab(data.get("required_vocabulary", {}),
                                       "required_vocabulary"),
            flag_off_invariants=_flags(data.get("flag_off_invariants", [])),
            require_attestation_sha=_bool(
                data.get("require_attestation_sha", False),
                "require_attestation_sha"),
            require_test_evidence=_bool(
                data.get("require_test_evidence", False),
                "require_test_evidence"),
            blocking_codes=_codes(data.get("blocking_codes", [])),
            attestation_sha_patterns=_sha_patterns(
                data.get("attestation_sha_patterns", [])),
        )


def load_contract(path: str | Path) -> TaskContract:
    """Load a ``.json`` or ``.toml`` contract. Fail closed on any defect."""
    src = Path(path)
    try:
        text = src.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read contract: {src.name}") from exc
    suffix = src.suffix.lower()
    try:
        if suffix == ".json":
            data = json.loads(text)
        elif suffix == ".toml":
            data = load_toml_mapping(text)
        else:
            raise ContractError(
                "contract file must be .json or .toml, "
                f"got {suffix or 'no suffix'}")
    except ContractError:
        raise
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ContractError(f"contract parse error: {exc}") from exc
    return TaskContract.from_mapping(data)


def load_toml_mapping(text: str) -> dict[str, Any]:
    """Parse TOML into a dict. Stdlib ``tomllib``, else ``tomli``, else
    the subset parser. The subset result matches ``tomllib`` on the
    contract documents this module accepts."""
    try:
        import tomllib
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception as exc:  # tomllib.TOMLDecodeError
            raise ContractError(f"TOML parse error: {exc}") from exc
        if not isinstance(data, dict):
            raise ContractError("TOML root must be a table")
        return data
    try:
        import tomli
    except ModuleNotFoundError:
        tomli = None  # type: ignore[assignment]
    if tomli is not None:
        try:
            data = tomli.loads(text)
        except Exception as exc:
            raise ContractError(f"TOML parse error: {exc}") from exc
        if not isinstance(data, dict):
            raise ContractError("TOML root must be a table")
        return data
    return _fallback_toml(text)


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a string")
    if "\x00" in value:
        raise ContractError(f"{field} must not contain NUL")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field} must be a boolean")
    return value


def _str_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractError(f"{field} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise ContractError(f"{field} must be a list of non-empty strings")
        out.append(item.replace("\\", "/"))
    return tuple(out)


def _pin_pairs(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise ContractError("pinned_versions must be a table of strings")
    pairs: list[tuple[str, str]] = []
    for key in sorted(value):
        if not isinstance(key, str) or not key:
            raise ContractError("pinned_versions keys must be non-empty strings")
        pin = value[key]
        if not isinstance(pin, str) or not pin:
            raise ContractError(
                f"pinned_versions[{key}] must be a non-empty string")
        pairs.append((key.replace("\\", "/"), pin))
    return tuple(pairs)


def _vocab(value: Any, field: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be a table of glob to term list")
    rows: list[tuple[str, tuple[str, ...]]] = []
    for key in sorted(value):
        if not isinstance(key, str) or not key:
            raise ContractError(f"{field} globs must be non-empty strings")
        terms = value[key]
        if not isinstance(terms, list) or not terms:
            raise ContractError(f"{field}[{key}] must be a non-empty list")
        cleaned: list[str] = []
        for term in terms:
            if not isinstance(term, str) or not term:
                raise ContractError(
                    f"{field}[{key}] terms must be non-empty strings")
            cleaned.append(term)
        rows.append((key.replace("\\", "/"), tuple(sorted(set(cleaned)))))
    return tuple(rows)


def _flags(value: Any) -> tuple[FlagOffInvariant, ...]:
    if not isinstance(value, list):
        raise ContractError("flag_off_invariants must be a list")
    out: list[FlagOffInvariant] = []
    for index, item in enumerate(value):
        where = f"flag_off_invariants[{index}]"
        if not isinstance(item, Mapping):
            raise ContractError(f"{where} must be a table")
        unknown = sorted(set(item) - _FLAG_KEYS)
        if unknown:
            raise ContractError(
                f"{where} has unknown field: " + ", ".join(unknown))
        flag = _string(item.get("flag", ""), "flag").strip()
        if not flag or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", flag):
            raise ContractError(f"{where}.flag must be an identifier")
        config = _str_tuple(item.get("config_globs", []), f"{where}.config_globs")
        guarded = _str_tuple(item.get("guarded_globs", []),
                             f"{where}.guarded_globs")
        if not config and not guarded:
            raise ContractError(
                f"{where} needs config_globs or guarded_globs")
        out.append(FlagOffInvariant(flag, config, guarded))
    out.sort(key=lambda row: (row.flag, row.config_globs, row.guarded_globs))
    return tuple(out)


def _codes(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractError("blocking_codes must be a list of strings")
    codes: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ContractError("blocking_codes must be non-empty strings")
        if item not in FINDING_CODES:
            raise ContractError(f"unknown blocking code: {item}")
        codes.append(item)
    return tuple(sorted(set(codes)))


def _sha_patterns(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractError("attestation_sha_patterns must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ContractError(
                "attestation_sha_patterns must be non-empty strings")
        try:
            compiled = re.compile(item)
        except re.error as exc:
            raise ContractError(
                f"attestation_sha_patterns invalid regex: {exc}") from exc
        if compiled.groups < 1:
            raise ContractError(
                "attestation_sha_patterns entries need one capture group")
        out.append(item)
    return tuple(out)


# ── Python 3.10 TOML subset (no tomllib, no third-party install) ──


def _fallback_toml(text: str) -> dict[str, Any]:
    """Subset used when neither tomllib nor tomli is importable.

    Supports comments, quoted and bare keys, strings, booleans, integers,
    arrays of those scalars, ``[tables]``, dotted tables, and
    ``[[array-of-tables]]``. Enough for a task contract; not a general
    TOML implementation.
    """
    root: dict[str, Any] = {}
    current: dict[str, Any] = root
    array_parent: dict[str, Any] | None = None
    array_key: str | None = None

    def open_table(parts: list[str], *, array: bool) -> None:
        nonlocal current, array_parent, array_key
        cursor = root
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        leaf = parts[-1]
        if array:
            bucket = cursor.get(leaf)
            if not isinstance(bucket, list):
                bucket = []
                cursor[leaf] = bucket
            row: dict[str, Any] = {}
            bucket.append(row)
            array_parent = cursor
            array_key = leaf
            current = row
        else:
            nxt = cursor.get(leaf)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[leaf] = nxt
            array_parent = None
            array_key = None
            current = nxt

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[[") and line.endswith("]]"):
            name = line[2:-2].strip()
            open_table(_table_parts(name, lineno), array=True)
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            open_table(_table_parts(name, lineno), array=False)
            continue
        if "=" not in line:
            raise ContractError(f"TOML parse error: line {lineno}")
        key_raw, _, val_raw = line.partition("=")
        key = _parse_key(key_raw.strip(), lineno)
        try:
            current[key] = _parse_value(val_raw.strip(), lineno)
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(f"TOML parse error: line {lineno}: {exc}") from exc
    return root


def _table_parts(name: str, lineno: int) -> list[str]:
    if not name:
        raise ContractError(f"TOML parse error: line {lineno}")
    return [_parse_key(part.strip(), lineno) for part in name.split(".")]


def _parse_key(text: str, lineno: int) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    if re.fullmatch(r"[A-Za-z0-9_-]+", text):
        return text
    raise ContractError(f"TOML parse error: bad key on line {lineno}")


def _strip_comment(text: str) -> str:
    in_quote = ""
    for index, ch in enumerate(text):
        if ch in {'"', "'"}:
            if in_quote == ch:
                in_quote = ""
            elif not in_quote:
                in_quote = ch
        elif ch == "#" and not in_quote:
            return text[:index]
    return text


def _parse_value(text: str, lineno: int) -> Any:
    if not text:
        raise ContractError(f"TOML parse error: line {lineno}")
    if text in {"true", "false"}:
        return text == "true"
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(part.strip(), lineno)
                for part in _split_array(inner)]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    raise ContractError(f"TOML parse error: line {lineno}")


def _split_array(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_quote = ""
    for ch in text:
        if ch in {'"', "'"}:
            if in_quote == ch:
                in_quote = ""
            elif not in_quote:
                in_quote = ch
            buf.append(ch)
        elif ch == "," and not in_quote:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts
