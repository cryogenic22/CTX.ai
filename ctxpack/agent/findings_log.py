"""Append-only verify findings log and deterministic lesson proposals.

``ctxpack verify`` records nothing unless ``--record-findings`` or
``--findings-log`` is set. Each finding becomes one JSON object per
line in ``.ctx/findings.jsonl`` (or the path that was named). The log
is the harness memory. ``ctxpack lessons suggest`` groups recurring
``(code, pattern)`` rows and prints a task-contract snippet a person
can copy. It never edits a contract and it never calls a model.

Pattern keys drop commit SHAs and line numbers so the same failure
groups across runs. Repeated runs of one commit share a ``head_sha``;
suggestions report both the raw ``count`` and ``distinct_heads``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
EVIDENCE_CHARS = 240
PATH_CHARS = 240
PATTERN_CHARS = 180
SHA_CHARS = 64
RANGE_CHARS = 200
DEFAULT_FINDINGS_LOG = ".ctx/findings.jsonl"
MIN_COUNT_DEFAULT = 3

_SHA_ONLY = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SHA_TOKEN = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{7,64}(?![0-9A-Za-z])")
_LINE_SUFFIX = re.compile(r":\d+(?::\d+)?$")
_FILENAME = re.compile(r"^[\w.@+-]+(?:\.[\w.+-]+)+$")
_GLOB_EVIDENCE = re.compile(
    r"^(forbidden_paths|one_way_paths|allowed_paths):(\S+)$")

# Codes whose useful pattern is a path glob (contract glob, else the
# parent directory, else the file itself).
_PATH_CODES = frozenset({
    "FORBIDDEN_PATH_TOUCHED",
    "ONE_WAY_PATH_TOUCHED",
    "OUT_OF_SCOPE_CHANGE",
})

# In-process threads. The file lock below covers other processes.
# On Windows a mandatory byte lock makes a second handle's write of
# that byte fail with PermissionError, so threads must not reach the
# file lock together.
_APPEND_LOCK = threading.Lock()

_RECORD_KEYS = (
    "base_sha",
    "blocking",
    "code",
    "evidence",
    "head_sha",
    "path",
    "pattern",
    "range",
    "schema_version",
    "severity",
)


class FindingsLogError(ValueError):
    """The findings log is missing a required field or has a bad line.

    ``lines`` is the 1-based line numbers that could not be read.
    An empty tuple means the failure is not a particular line.
    """

    def __init__(self, message: str, lines: tuple[int, ...] = ()) -> None:
        super().__init__(message)
        self.lines = lines


class FindingList(list[dict[str, Any]]):
    """Records from one log, plus any corrupt line numbers that were skipped."""

    def __init__(
        self,
        records: Iterable[dict[str, Any]] = (),
        corrupt_lines: tuple[int, ...] = (),
    ) -> None:
        super().__init__(records)
        self.corrupt_lines = corrupt_lines

    @property
    def corrupt_count(self) -> int:
        return len(self.corrupt_lines)


def finding_path(location: str) -> str:
    """Relative POSIX path for a finding location, or ``""``.

    Commit SHAs, absolute paths, and labels such as ``pr-body`` are not
    paths. A leading ``./`` is a relative marker; the dot in ``.github``
    is part of the name.
    """
    text = _normalize_rel(location)
    text = _LINE_SUFFIX.sub("", text)
    if not text or _SHA_ONLY.fullmatch(text):
        return ""
    if " " in text or ":" in text:
        return ""
    if "/" in text or _FILENAME.fullmatch(text):
        return _clip(text, PATH_CHARS)
    return ""


def finding_pattern(
    code: str,
    path: str,
    evidence: str,
    *,
    message: str = "",
) -> str:
    """Stable group key for ``(code, path, evidence)``.

    Path-scoped codes keep a directory glob or an exact file. Claim,
    verifier, and attestation codes keep a short reason with no SHA and
    no line number.
    """
    kind = _one_line(code, 80)
    ev = _one_line(evidence, EVIDENCE_CHARS)
    msg = _one_line(message, EVIDENCE_CHARS).lower()
    named = _glob_from_evidence(ev)
    if kind in _PATH_CODES:
        return _clip(named or _parent_glob(path) or kind.lower(), PATTERN_CHARS)
    if kind == "CONTRACT_RULE_VIOLATION":
        return _clip(_contract_pattern(ev, path), PATTERN_CHARS)
    if kind == "VERIFIER_EVIDENCE_MISSING":
        return _verifier_pattern(ev, msg)
    if kind == "UNVERIFIED_CLAIM":
        return "unverified_test_claim"
    if kind == "ATTESTATION_SHA_MISMATCH":
        return "sha_mismatch"
    if kind == "STALE_IDENTIFIER":
        return "stale_identifier"
    if kind in {"VERSION_PIN_DRIFT", "SUPERSEDED_STILL_IN_CODE"}:
        parent = _parent_glob(path)
        if parent:
            return _clip(parent, PATTERN_CHARS)
        if kind == "VERSION_PIN_DRIFT":
            return "version_pin"
        return "superseded_identifier"
    if kind == "UNRECORDED_MARKER":
        return "unrecorded_marker"
    if kind == "CONSTRAINT_CONFLICT":
        return "constraint_conflict"
    stable = _strip_volatile(ev) or kind.lower()
    return _clip(stable or "finding", PATTERN_CHARS)


def append_findings(
    report: Any,
    path: str | os.PathLike[str],
    *,
    repo_id: str | None = None,
) -> int:
    """Append one JSONL record per finding. Return how many were written.

    Parent directories are created when there is at least one finding.
    A report with no findings does not create the file. Each record is
    one line ending in ``\\n``, with sorted keys. The write is locked
    and fsync'd so a crash does not leave a half-written line mixed
    with another process's record. ``repo_id`` is stored only when it
    is a non-empty string; the default record matches the v1 field set.
    """
    rows = list(_iter_records(report, repo_id=repo_id))
    if not rows:
        return 0
    payload = "".join(
        json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        + "\n"
        for row in rows
    ).encode("utf-8")
    _append_bytes(os.fspath(path), payload)
    return len(rows)


def read_findings(
    path: str | os.PathLike[str],
    *,
    skip_corrupt: bool = False,
) -> FindingList:
    """Read a findings log in file order.

    Blank lines are ignored. An empty file yields an empty list. A line
    that is not a v1 object, or whose ``code`` is missing, is corrupt.
    The default raises :class:`FindingsLogError` and names every corrupt
    line. ``skip_corrupt=True`` returns the valid rows and sets
    ``corrupt_lines`` / ``corrupt_count`` on the list so nothing is
    dropped without a visible count.
    """
    raw = PathBytes.read(os.fspath(path))
    records: list[dict[str, Any]] = []
    corrupt: list[int] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        row = _parse_line(line)
        if row is None:
            corrupt.append(number)
            continue
        records.append(row)
    lines = tuple(corrupt)
    if lines and not skip_corrupt:
        listed = ", ".join(str(item) for item in lines)
        noun = "line" if len(lines) == 1 else "lines"
        raise FindingsLogError(
            f"findings log corrupt at {noun} {listed}",
            lines=lines,
        )
    return FindingList(records, lines)


def suggestions_payload(
    records: Sequence[Mapping[str, Any]],
    *,
    min_count: int = MIN_COUNT_DEFAULT,
    findings_log: str = DEFAULT_FINDINGS_LOG,
    status: str = "ok",
) -> dict[str, Any]:
    """Group ``records`` into copy-pasteable contract proposals.

    Groups with ``count < min_count`` are omitted. Order is
    ``(-count, code, pattern)``. ``distinct_heads`` counts non-empty
    ``head_sha`` values so re-runs of one commit stay visible.
    """
    if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 1:
        raise FindingsLogError("min_count must be an integer >= 1")
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        code = row.get("code")
        if not isinstance(code, str) or not code:
            continue
        raw_pattern = row.get("pattern")
        pattern = raw_pattern if isinstance(raw_pattern, str) else ""
        key = (code, pattern)
        bucket = groups.get(key)
        if bucket is None:
            bucket = {
                "code": code,
                "pattern": pattern,
                "count": 0,
                "heads": set(),
                "paths": set(),
            }
            groups[key] = bucket
        bucket["count"] += 1
        head = row.get("head_sha")
        if isinstance(head, str) and head:
            bucket["heads"].add(head)
        path = row.get("path")
        if isinstance(path, str) and path:
            bucket["paths"].add(path)
    ordered = sorted(
        groups.values(),
        key=lambda bucket: (-int(bucket["count"]), str(bucket["code"]), str(bucket["pattern"])),
    )
    suggestions: list[dict[str, Any]] = []
    for bucket in ordered:
        count = int(bucket["count"])
        if count < min_count:
            continue
        code = str(bucket["code"])
        pattern = str(bucket["pattern"])
        summary, patch = propose_contract(code, pattern)
        paths = sorted(bucket["paths"])[:3]
        suggestions.append({
            "code": code,
            "contract_patch": patch,
            "count": count,
            "distinct_heads": len(bucket["heads"]),
            "pattern": pattern,
            "proposal_summary": summary,
            "sample_paths": paths,
        })
    return {
        "corrupt_lines": [],
        "findings_log": findings_log.replace("\\", "/"),
        "min_count": min_count,
        "status": status,
        "suggestions": suggestions,
        "total_findings": len(records),
    }


def propose_contract(code: str, pattern: str) -> tuple[str, dict[str, Any]]:
    """Map one recurring ``(code, pattern)`` to a contract snippet.

    The snippet is for a person to review. Nothing here writes a file.
    """
    glob = _bare_glob(pattern)
    path_like = _is_path_pattern(glob)
    if code == "FORBIDDEN_PATH_TOUCHED" or pattern.startswith("forbidden_paths:"):
        if path_like:
            summary = (
                f"Add or keep `{glob}` in forbidden_paths in .ctx/contract.json, "
                "or narrow allowed_paths so the task does not include it."
            )
            return summary, {"forbidden_paths": [glob]}
        return _fallback(code, pattern)
    if code == "OUT_OF_SCOPE_CHANGE" or pattern.startswith("allowed_paths:"):
        if path_like:
            summary = (
                f"Add `{glob}` to allowed_paths if this task should touch it, "
                "or narrow the task scope so the path stays unchanged."
            )
            return summary, {"allowed_paths": [glob]}
        return _fallback(code, pattern)
    if code == "ONE_WAY_PATH_TOUCHED" or pattern.startswith("one_way_paths:"):
        if path_like:
            summary = (
                f"Keep `{glob}` in one_way_paths and document the one-way-ack: "
                "checklist in .github/pull_request_template.md. Run "
                "`ctxpack onboard` to wire the attestation block."
            )
            return summary, {"one_way_paths": [glob]}
        return _fallback(code, pattern)
    if code == "VERIFIER_EVIDENCE_MISSING":
        summary = (
            "Enable require_verifier_evidence: true with verifier_command "
            "and run `ctxpack onboard` to wire the PR template."
        )
        return summary, {
            "require_verifier_evidence": True,
            "verifier_command": "",
        }
    if code == "UNVERIFIED_CLAIM":
        summary = (
            "Enable require_test_evidence: true and add UNVERIFIED_CLAIM "
            "to blocking_codes."
        )
        return summary, {
            "blocking_codes": ["UNVERIFIED_CLAIM"],
            "require_test_evidence": True,
        }
    if code == "ATTESTATION_SHA_MISMATCH":
        summary = (
            "Run `ctxpack onboard` so the PR template and CI check enforce "
            "verified-sha:. Enable require_attestation_sha and add "
            "ATTESTATION_SHA_MISMATCH to blocking_codes."
        )
        return summary, {
            "blocking_codes": ["ATTESTATION_SHA_MISMATCH"],
            "require_attestation_sha": True,
        }
    if code == "STALE_IDENTIFIER":
        summary = (
            "Add a rename-completeness check, or add STALE_IDENTIFIER "
            "to blocking_codes."
        )
        return summary, {"blocking_codes": ["STALE_IDENTIFIER"]}
    return _fallback(code, pattern)


def render_suggestions(payload: Mapping[str, Any], fmt: str) -> str:
    """Render a suggestions payload as ``text``, ``markdown``, or ``json``."""
    if fmt == "json":
        return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    if fmt == "markdown":
        return _render_markdown(payload)
    if fmt == "text":
        return _render_text(payload)
    raise FindingsLogError(f"unknown suggestions format: {fmt}")


class PathBytes:
    """Indirection so tests can describe the read without a second API."""

    @staticmethod
    def read(path: str) -> bytes:
        with open(path, "rb") as handle:
            return handle.read()


def _iter_records(
    report: Any,
    *,
    repo_id: str | None,
) -> Iterable[dict[str, Any]]:
    findings = _report_findings(report)
    head = _report_text(report, ("head_sha", "head"), SHA_CHARS)
    base = _report_text(report, ("base_sha", "base"), SHA_CHARS)
    diff_range = _report_text(report, ("diff_range", "range_spec", "range"), RANGE_CHARS)
    extra = _repo_id(repo_id)
    for finding in findings:
        code = _text_field(finding, "code", 80)
        if not code:
            raise FindingsLogError("finding is missing a code")
        evidence = _text_field(finding, "evidence", EVIDENCE_CHARS)
        message = _text_field(finding, "message", EVIDENCE_CHARS)
        severity = _text_field(finding, "severity", 40)
        path = finding_path(_location_of(finding))
        pattern = finding_pattern(code, path, evidence, message=message)
        row: dict[str, Any] = {
            "base_sha": base,
            "blocking": _is_blocking(report, finding, code),
            "code": code,
            "evidence": evidence,
            "head_sha": head,
            "path": path,
            "pattern": pattern,
            "range": diff_range,
            "schema_version": SCHEMA_VERSION,
            "severity": severity,
        }
        if extra:
            row["repo_id"] = extra
        yield row


def _report_findings(report: Any) -> Sequence[Any]:
    if isinstance(report, Mapping):
        findings = report.get("findings")
    else:
        findings = getattr(report, "findings", None)
    if findings is None:
        raise FindingsLogError("report has no findings")
    if isinstance(findings, (str, bytes)) or not isinstance(findings, Sequence):
        raise FindingsLogError("report findings must be a sequence")
    return findings


def _is_blocking(report: Any, finding: Any, code: str) -> bool:
    if isinstance(report, Mapping):
        raw = report.get("blocking", ())
    else:
        raw = getattr(report, "blocking", ())
    if raw is None:
        return False
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        return False
    for item in raw:
        if item == code or item is finding:
            return True
        item_code = getattr(item, "code", None)
        if isinstance(item, Mapping):
            item_code = item.get("code")
        if item_code == code and item_code:
            return True
    return False


def _location_of(finding: Any) -> str:
    for name in ("location", "path"):
        value = _mapping_or_attr(finding, name)
        if isinstance(value, str) and value:
            return value
    return ""


def _text_field(finding: Any, name: str, limit: int) -> str:
    value = _mapping_or_attr(finding, name)
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return _one_line(value, limit)


def _mapping_or_attr(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _report_text(report: Any, names: tuple[str, ...], limit: int) -> str:
    for name in names:
        if isinstance(report, Mapping):
            value = report.get(name)
        else:
            value = getattr(report, name, None)
        if isinstance(value, str) and value.strip():
            return _one_line(value, limit)
    if isinstance(report, Mapping):
        return ""
    to_dict = getattr(report, "to_dict", None)
    if not callable(to_dict):
        return ""
    raw = to_dict()
    if not isinstance(raw, Mapping):
        return ""
    for name in names:
        value = raw.get(name)
        if isinstance(value, str) and value.strip():
            return _one_line(value, limit)
    return ""


def _repo_id(repo_id: str | None) -> str:
    if repo_id is None:
        return ""
    if not isinstance(repo_id, str):
        raise FindingsLogError("repo_id must be a string")
    return _one_line(repo_id, 120)


def _parse_line(line: bytes) -> dict[str, Any] | None:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    version = row.get("schema_version")
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        return None
    code = row.get("code")
    if not isinstance(code, str) or not code or "\x00" in code:
        return None
    for key in ("severity", "path", "pattern", "head_sha", "base_sha", "range", "evidence"):
        if key in row and not isinstance(row[key], str):
            return None
    if "blocking" in row and not isinstance(row["blocking"], bool):
        return None
    if "repo_id" in row and not isinstance(row["repo_id"], str):
        return None
    cleaned: dict[str, Any] = {
        "base_sha": row.get("base_sha") or "",
        "blocking": bool(row.get("blocking", False)),
        "code": code,
        "evidence": row.get("evidence") or "",
        "head_sha": row.get("head_sha") or "",
        "path": _normalize_rel(row.get("path") or ""),
        "pattern": row.get("pattern") or "",
        "range": row.get("range") or "",
        "schema_version": SCHEMA_VERSION,
        "severity": row.get("severity") or "",
    }
    repo = row.get("repo_id")
    if isinstance(repo, str) and repo:
        cleaned["repo_id"] = repo
    # Touch the canonical key tuple so a future field is a deliberate edit.
    for key in _RECORD_KEYS:
        if key not in cleaned:
            return None
    return cleaned


def _contract_pattern(evidence: str, path: str) -> str:
    match = _GLOB_EVIDENCE.match(evidence)
    if match and match.group(1) == "forbidden_paths":
        glob = _normalize_rel(match.group(2))
        return "forbidden_paths:" + (glob or _parent_glob(path) or "path")
    if evidence == "allowed_paths" or evidence.startswith("allowed_paths:"):
        glob = ""
        if evidence.startswith("allowed_paths:"):
            glob = _normalize_rel(evidence.split(":", 1)[1])
        return "allowed_paths:" + (glob or _parent_glob(path) or "path")
    if evidence.startswith("forbidden_vocabulary:"):
        return "forbidden_vocabulary:" + _strip_volatile(evidence.split(":", 1)[1])
    if evidence.startswith("required_vocabulary:"):
        return "required_vocabulary:" + _strip_volatile(evidence.split(":", 1)[1])
    if evidence.startswith("flag_off:"):
        return "flag_off:" + _strip_volatile(evidence.split(":", 1)[1])
    if evidence.startswith("flag_guard:"):
        return "flag_guard:" + _strip_volatile(evidence.split(":", 1)[1])
    parent = _parent_glob(path)
    if parent:
        return parent
    return "contract_rule"


def _verifier_pattern(evidence: str, message: str) -> str:
    if "sha" in message or _SHA_ONLY.fullmatch(evidence) or evidence.startswith("sha"):
        return "sha_mismatch"
    if "command" in message:
        return "command_mismatch"
    if "not a pass" in message or evidence in {"fail", "failed", "no-status", "error"}:
        return "verifier_not_pass"
    return "missing_verifier"


def _glob_from_evidence(evidence: str) -> str:
    match = _GLOB_EVIDENCE.match(evidence)
    if not match:
        return ""
    return _normalize_rel(match.group(2))


def _parent_glob(path: str) -> str:
    text = _normalize_rel(path)
    if not text:
        return ""
    if text.endswith("/**"):
        return text
    if "/" not in text:
        return text
    parent = text.rsplit("/", 1)[0]
    return parent + "/**"


def _bare_glob(pattern: str) -> str:
    for prefix in ("forbidden_paths:", "allowed_paths:", "one_way_paths:"):
        if pattern.startswith(prefix):
            return pattern[len(prefix):]
    return pattern


def _is_path_pattern(pattern: str) -> bool:
    if not pattern or " " in pattern:
        return False
    return "/" in pattern or "*" in pattern or pattern.startswith(".")


def _fallback(code: str, pattern: str) -> tuple[str, dict[str, Any]]:
    shown = pattern or code
    summary = (
        f"Add {code} to blocking_codes in the task contract. "
        f"Recurring pattern: {shown}."
    )
    return summary, {"blocking_codes": [code]}


def _normalize_rel(value: str) -> str:
    text = value.replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        return ""
    return text


def _strip_volatile(value: str) -> str:
    text = _SHA_TOKEN.sub("", value)
    text = _LINE_SUFFIX.sub("", text)
    return _one_line(text, PATTERN_CHARS).strip(" :")


def _one_line(value: str, limit: int) -> str:
    text = " ".join(value.replace("\x00", "").split())
    if len(text) > limit:
        return text[:limit]
    return text


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


def _render_text(payload: Mapping[str, Any]) -> str:
    if payload.get("status") == "missing":
        return f"No findings log found at {payload.get('findings_log', '')}\n"
    lines = [
        f"findings log: {payload.get('findings_log', '')}",
        f"total findings: {payload.get('total_findings', 0)}",
        f"min count: {payload.get('min_count', MIN_COUNT_DEFAULT)}",
        f"suggestions: {len(payload.get('suggestions') or [])}",
        "",
    ]
    suggestions = payload.get("suggestions") or []
    if not suggestions:
        lines.append(f"No pattern reached min count {payload.get('min_count', MIN_COUNT_DEFAULT)}.")
        lines.append("")
        return "\n".join(lines)
    for row in suggestions:
        if not isinstance(row, Mapping):
            continue
        sample = row.get("sample_paths") or []
        shown = ", ".join(str(item) for item in sample) if sample else "-"
        patch = json.dumps(
            row.get("contract_patch") or {},
            sort_keys=True,
            ensure_ascii=True,
        )
        lines.append(
            f"{row.get('code')} pattern={row.get('pattern')} "
            f"count={row.get('count')} distinct_heads={row.get('distinct_heads')}"
        )
        lines.append(f"  sample paths: {shown}")
        lines.append(f"  proposal: {row.get('proposal_summary')}")
        lines.append(f"  contract patch: {patch}")
        lines.append("")
    return "\n".join(lines)


def _render_markdown(payload: Mapping[str, Any]) -> str:
    log = payload.get("findings_log", "")
    if payload.get("status") == "missing":
        return f"No findings log found at `{log}`.\n"
    suggestions = payload.get("suggestions") or []
    lines = [
        "# ctxpack lessons suggest",
        "",
        f"findings log: `{log}`",
        f"total findings: {payload.get('total_findings', 0)}",
        f"min count: {payload.get('min_count', MIN_COUNT_DEFAULT)}",
        f"suggestions: {len(suggestions)}",
        "",
    ]
    if not suggestions:
        lines.append(
            f"No pattern reached min count {payload.get('min_count', MIN_COUNT_DEFAULT)}."
        )
        lines.append("")
        return "\n".join(lines)
    for row in suggestions:
        if not isinstance(row, Mapping):
            continue
        sample_paths = row.get("sample_paths") or []
        if sample_paths:
            sample = ", ".join(f"`{item}`" for item in sample_paths)
        else:
            sample = "-"
        patch = json.dumps(
            row.get("contract_patch") or {},
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        )
        lines.append(f"## {row.get('code')} `{row.get('pattern')}`")
        lines.append("")
        lines.append(f"- count: {row.get('count')}")
        lines.append(f"- distinct_heads: {row.get('distinct_heads')}")
        lines.append(f"- sample paths: {sample}")
        lines.append(f"- proposal: {row.get('proposal_summary')}")
        lines.append("- contract patch:")
        lines.append("")
        lines.append("```json")
        lines.append(patch)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _append_bytes(path: str, payload: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    with _APPEND_LOCK:
        lock_fd: int | None = None
        if sys.platform == "win32":
            lock_fd = _open_lock(path)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        locked_here = False
        try:
            if lock_fd is None:
                _lock_fd(fd)
                locked_here = True
            _ensure_trailing_newline(fd)
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            if locked_here:
                _unlock_fd(fd)
            os.close(fd)
            if lock_fd is not None:
                _unlock_fd(lock_fd)
                os.close(lock_fd)
        _fsync_dir(directory)


def _ensure_lock_seed(lock_path: str) -> None:
    """Create a one-byte lock file exactly once, before anyone locks it.

    A later writer must not rewrite byte 0: on Windows that byte is the
    mandatory lock region, and a write into it raises PermissionError.
    """
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return
    try:
        os.write(fd, b"\0")
        os.fsync(fd)
    finally:
        os.close(fd)


def _open_lock(path: str) -> int:
    lock_path = path + ".lock"
    _ensure_lock_seed(lock_path)
    fd = os.open(lock_path, os.O_RDWR)
    try:
        if os.fstat(fd).st_size < 1:
            # The creator crashed before the seed byte. Write it only
            # when the region is not already locked.
            try:
                os.write(fd, b"\0")
            except PermissionError:
                pass
        _lock_fd(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _lock_fd(fd: int) -> None:
    if sys.platform == "win32":
        _lock_windows(fd)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    if sys.platform == "win32":
        _unlock_windows(fd)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


def _lock_windows(fd: int) -> None:
    import msvcrt

    os.lseek(fd, 0, os.SEEK_SET)
    # Attribute lookup keeps this file type-clean on non-Windows checkers.
    # msvcrt.locking / LK_LOCK exist on Windows and are absent from the
    # Linux stub.
    getattr(msvcrt, "locking")(fd, getattr(msvcrt, "LK_LOCK"), 1)


def _unlock_windows(fd: int) -> None:
    import msvcrt

    os.lseek(fd, 0, os.SEEK_SET)
    getattr(msvcrt, "locking")(fd, getattr(msvcrt, "LK_UNLCK"), 1)


def _ensure_trailing_newline(fd: int) -> None:
    end = os.lseek(fd, 0, os.SEEK_END)
    if end <= 0:
        return
    os.lseek(fd, max(0, end - 1), os.SEEK_SET)
    last = os.read(fd, 1)
    os.lseek(fd, 0, os.SEEK_END)
    if last != b"\n":
        _write_all(fd, b"\n")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("failed to append findings log")
        view = view[written:]


def _fsync_dir(directory: str) -> None:
    if sys.platform == "win32":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "DEFAULT_FINDINGS_LOG",
    "EVIDENCE_CHARS",
    "SCHEMA_VERSION",
    "FindingList",
    "FindingsLogError",
    "append_findings",
    "finding_path",
    "finding_pattern",
    "propose_contract",
    "read_findings",
    "render_suggestions",
    "suggestions_payload",
]
