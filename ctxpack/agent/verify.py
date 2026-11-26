"""Deterministic ledger-to-PR verifier (issue #16).

``ctxpack verify --range A..B`` compares commit messages, an optional PR
body, the working ledger, and an optional task contract. ``A..B`` and
``A...B`` name the same two refs. The changed-file set and the
stale-identifier baseline are the three-dot PR diff (merge base to head)
when a merge base exists, and a direct two-dot tree diff only when the
histories do not meet. Commit messages stay on ``git log A..B``. The
same inputs produce byte-identical JSON on Linux, macOS, and Windows.
Nothing here calls the network. An optional Jev adapter is a separate
advisory path and does not change this exit code.

Exit status is 0 unless a finding's code is in the blocking list. The
list comes from ``--block``, then ``ctxpack.toml`` ``[verify] block``,
then the contract's ``blocking_codes``. The default list is empty
(report-only). ``ONE_WAY_PATH_TOUCHED`` is the exception: it blocks
even when the list omits it, unless the PR body has ``one-way-ack:``
and a ``verified-sha:`` that prefixes head. A contract or git error
exits 2 from the CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..core.model import KeyValue
from ..core.parser import parse
from .conflict_lint import lint_decisions
from .contract import (
    FINDING_CODES,
    ContractError,
    FlagOffInvariant,
    TaskContract,
    load_contract,
    load_toml_mapping,
)
from .live_set import live_set_from_records
from .session_reader import _kv, ledger_facts

MAX_FINDINGS = 200
_EVIDENCE_CHARS = 240

SEVERITY = {
    "ATTESTATION_SHA_MISMATCH": "error",
    "CONSTRAINT_CONFLICT": "warning",
    "CONTRACT_RULE_VIOLATION": "error",
    "ONE_WAY_PATH_TOUCHED": "error",
    "STALE_IDENTIFIER": "warning",
    "SUPERSEDED_STILL_IN_CODE": "warning",
    "UNRECORDED_MARKER": "warning",
    "UNVERIFIED_CLAIM": "warning",
    "VERIFIER_EVIDENCE_MISSING": "error",
    "VERSION_PIN_DRIFT": "error",
}

_MARKER_LABEL = {
    "constraint": "Constraint",
    "dead end": "Dead end",
    "decision": "Decision",
    "rejected": "Rejected",
    "supersedes": "Supersedes",
}

_INLINE_CODE = re.compile(r"`[^`]*`")
_MARKER_LINE = re.compile(
    r"(?i)^(?:[-*•>]\s*)*(?:\*{1,2}|_{1,2})?"
    r"(decision|constraint|rejected|dead end|supersedes)"
    r"(?:\*{1,2}|_{1,2})?\s*:\s*(.*?)\s*$")
_BACKTICK = re.compile(r"`([^`\n]+)`")
_BARE_PATH = re.compile(
    r"(?<![\w./])((?:[\w.-]+/)+[\w.-]+\.[\w]+|(?:[\w.-]+\.(?:py|md|toml|json|yml|yaml|txt|rs|go|ts|tsx|js)))")
_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{3,}$")
_ID_TOKEN = re.compile(r"[0-9a-fA-F]{64}|[0-9a-fA-F]{16}")
_SUPERSEDES_PAYLOAD = re.compile(
    r"\s*[`']?([0-9a-fA-F]{64}|[0-9a-fA-F]{16})\b[`']?\s*(?:[—–\-:,]\s*)?(.*)")
_SUPERSEDES_FIELD = re.compile(
    r"(?im)^SUPERSEDES-FACT-ID:[ \t]*([0-9a-fA-F]{64}|[0-9a-fA-F]{16})[ \t]*$")
_DEFAULT_SHA = (
    re.compile(
        r"(?im)^[ \t>*-]*(?:verified-sha|attested-sha|head-sha)"
        r"\s*:\s*([0-9a-fA-F]{7,40})\b"),
)
# One-way acknowledgement is the ``verified-sha`` label only. A
# placeholder such as ``<7+ char head sha>`` does not match.
_VERIFIED_SHA_LINE = re.compile(
    r"(?im)^[ \t>*-]*(?:\*{1,2}|_{1,2})?verified-sha"
    r"(?:\*{1,2}|_{1,2})?\s*:\s*([0-9a-fA-F]{7,40})\b")
_ONE_WAY_ACK = re.compile(
    r"(?im)^[ \t>*-]*(?:\*{1,2}|_{1,2})?one-way-ack"
    r"(?:\*{1,2}|_{1,2})?\s*:\s*(\S.*?)\s*$")
_PASS_STATUS = frozenset({"pass", "ok", "passed", "green"})
_STATUS_WORD = (
    r"(?<![A-Za-z0-9_])(?P<status>passed|pass|green|ok|failed|fail|"
    r"skipped|error|red|not[-_ ]run)(?![A-Za-z0-9_])")
_STATUS_EXACT = re.compile(
    r"(?i)^(?:passed|pass|green|ok|failed|fail|skipped|error|red|not[-_ ]run)$")
_SHA_ALT = r"[0-9a-fA-F]{7,40}"
_SHA_EXACT = re.compile(rf"(?i)^{_SHA_ALT}$")
_VERIFIER_AT = re.compile(
    rf"(?i)^(?P<name>.*?)\s*{_STATUS_WORD}\s+@\s+(?P<sha>{_SHA_ALT})\s*$")
_VERIFIER_PAREN = re.compile(
    rf"(?i)^(?P<name>.*?)\s*{_STATUS_WORD}\s+\((?P<sha>{_SHA_ALT})\)\s*$")
_VERIFIER_TRAIL = re.compile(
    rf"(?i)^(?P<name>.*?)\s*{_STATUS_WORD}(?:\s+(?P<sha>{_SHA_ALT}))?\s*$")
_GREEN_CLAIM = re.compile(
    r"(?i)\b(?:all tests passed|tests passed|0 errors)\b"
    r"|\b\d+(?:\.\d+)?%\s*coverage\b"
    r"|\bcoverage(?:\s+is|\s*[:=])?\s*\d+(?:\.\d+)?%")
# Up to two words may sit between "run" and "pytest"/"tests"
# ("could not run required pytest", "did not run the full tests").
# Bare "tests skipped" / "skipped tests" is not an admission: a negated
# or partial skip ("no tests skipped", "e2e tests skipped") is normal.
_NOT_RUN = re.compile(
    r"(?i)\btests (?:were )?not run\b"
    r"|\bdid not run (?:\w+\s+){0,2}(?:pytest|tests?)\b"
    r"|\b(?:could not|couldn't|cannot|unable to) run "
    r"(?:\w+\s+){0,2}(?:pytest|tests?)\b"
    r"|\b(?:pytest|tests) could not be run\b")
_EVIDENCE = (
    re.compile(r"(?i)evidence-sha256:\s*[0-9a-f]{64}\b"),
    re.compile(r"(?i)test-command:\s*\S+"),
    re.compile(r"(?i)\b\d+\s+passed\b"),
)
_FLOATING = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:latest|floating)(?![A-Za-z0-9_])"
    r"|\"\*\"|'\*'"
    r"|(?<![\w.])[\^~]\d"
    r"|(?<![\w.])>=\s*\d")
_ON = frozenset({"true", "1", "on", "enabled", "yes"})
_TEXT_EXTS = (
    ".py", ".md", ".toml", ".json", ".yml", ".yaml", ".txt", ".rs",
    ".go", ".ts", ".tsx", ".js", ".css", ".html", ".cfg", ".ini",
)


class VerifyError(ValueError):
    """The range, git repo, or verifier config cannot be checked."""


@dataclass(frozen=True)
class Finding:
    """One deterministic verifier finding."""

    code: str
    severity: str
    fact_id: str | None
    location: str
    message: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "evidence": self.evidence,
            "fact_id": self.fact_id,
            "location": self.location,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class VerifyReport:
    """Sorted findings plus the exit code a caller should return."""

    range_spec: str
    base: str
    head: str
    findings: tuple[Finding, ...]
    blocking: tuple[str, ...]
    exit_code: int
    contract: str | None
    dropped: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "blocking": list(self.blocking),
            "contract": self.contract,
            "dropped": self.dropped,
            "exit_code": self.exit_code,
            "findings": [row.to_dict() for row in self.findings],
            "head": self.head,
            "range": self.range_spec,
        }


@dataclass(frozen=True)
class _Fact:
    fact_id: str
    kind: str
    texts: tuple[str, ...]
    source: str
    superseded: bool
    live: bool
    successor_text: str


@dataclass(frozen=True)
class _Marked:
    kind: str
    line: str
    payload: str
    location: str


@dataclass
class _Field:
    key: str
    value: str


@dataclass
class _Source:
    turn: int


@dataclass
class _Entity:
    name: str
    fields: list[_Field]
    sources: list[_Source]


def verify(
    range_spec: str,
    *,
    repo: str | os.PathLike[str] = ".",
    pr_body: str | None = None,
    pr_body_label: str = "pr-body",
    contract: str | os.PathLike[str] | TaskContract | None = None,
    ledger_dir: str | os.PathLike[str] | None = None,
    block: Sequence[str] | None = None,
    max_findings: int = MAX_FINDINGS,
) -> VerifyReport:
    """Verify ``range_spec`` (``A..B`` or ``A...B``) against the ledger and contract.

    ``pr_body`` is the description text, not a path. ``contract`` is a
    path or a loaded :class:`TaskContract`. The changed-file set and the
    stale-identifier baseline use the merge base when the two refs share
    one. Findings are sorted by ``(code, location, fact_id, message)``.
    """
    if max_findings < 1:
        raise VerifyError("max_findings must be >= 1")
    root = Path(repo)
    git = GitRepo(root)
    base_rev, head_rev = _split_range(range_spec)
    base = git.rev_parse(base_rev)
    head = git.rev_parse(head_rev)
    loaded = _load_contract(contract)
    blocking = _resolve_block(root, block, loaded)
    ledger = Path(ledger_dir) if ledger_dir is not None else root / ".claude/ctx"
    facts = _load_facts(ledger)
    # One merge-base for the diff and for stale identifiers. Commit
    # messages stay on the named base (``git log base..head``).
    effective_base = git.merge_base(base, head) or base
    commits = git.commits(base, head)
    changed = git.changed(effective_base, head)
    trees = {effective_base: git.tree(effective_base), head: git.tree(head)}
    blobs = _BlobCache(git)

    findings: list[Finding] = []
    marked = _collect_markers(commits, pr_body, pr_body_label)
    findings.extend(_unrecorded(marked, facts, ledger))
    findings.extend(_stale(facts, git, effective_base, head, trees))
    findings.extend(_superseded_in_code(facts, changed, blobs, head))
    findings.extend(_conflicts(marked, facts, ledger, changed, root))
    if pr_body is None and loaded is not None:
        if loaded.require_attestation_sha:
            findings.append(_finding(
                "ATTESTATION_SHA_MISMATCH", pr_body_label,
                "attestation SHA does not match head",
                "missing", None))
        if loaded.require_test_evidence:
            findings.append(_finding(
                "UNVERIFIED_CLAIM", pr_body_label,
                "claim lacks required test evidence",
                "missing", None))
        if loaded.require_verifier_evidence:
            findings.append(_finding(
                "VERIFIER_EVIDENCE_MISSING", pr_body_label,
                "verifier evidence is missing",
                "missing", None))
    elif pr_body is not None:
        findings.extend(_attestation(pr_body, head, loaded, pr_body_label))
        findings.extend(_claims(pr_body, loaded, pr_body_label))
        if loaded is not None and loaded.require_verifier_evidence:
            findings.extend(_verifier_evidence(
                pr_body, head, loaded, pr_body_label))
    if loaded is not None:
        findings.extend(_contract_rules(loaded, changed, blobs, base, head))
        findings.extend(_version_pins(loaded, changed, blobs, head))
        findings.extend(_one_way_paths(loaded, changed))

    ordered = _dedupe_sort(findings)
    effective = _effective_blocking(
        blocking, ordered, pr_body, head)
    exit_code = 1 if any(row.code in effective for row in ordered) else 0
    dropped = max(0, len(ordered) - max_findings)
    kept = tuple(ordered[:max_findings])
    return VerifyReport(
        range_spec=range_spec,
        base=base,
        head=head,
        findings=kept,
        blocking=effective,
        exit_code=exit_code,
        contract=loaded.name if loaded is not None else None,
        dropped=dropped,
    )


def render_json(report: VerifyReport) -> str:
    """JSON with sorted keys and ``\\n`` newlines, including a trailing newline."""
    return json.dumps(
        report.to_dict(), sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def render_markdown(report: VerifyReport) -> str:
    """Stable markdown rendering of ``report``."""
    lines = [
        f"# ctxpack verify {report.range_spec}",
        "",
        f"base: {report.base}",
        f"head: {report.head}",
        f"contract: {report.contract or '-'}",
        f"exit_code: {report.exit_code}",
        f"dropped: {report.dropped}",
        "blocking: " + (", ".join(report.blocking) if report.blocking else "-"),
        f"findings: {len(report.findings)}",
        "",
    ]
    for row in report.findings:
        lines.append(
            f"- {row.code} [{row.severity}] {row.location} "
            f"fact {row.fact_id or '-'}")
        lines.append(f"  message: {row.message}")
        lines.append(f"  evidence: {row.evidence}")
    lines.append("")
    return "\n".join(lines)


def run_cli(args: argparse.Namespace) -> int:
    """CLI entry. Returns 0, 1 (blocking finding), or 2 (cannot verify)."""
    try:
        pr_text = None
        pr_label = "pr-body"
        if getattr(args, "pr_body", None):
            pr_label = str(args.pr_body).replace("\\", "/")
            pr_text = Path(args.pr_body).read_text(encoding="utf-8")
        block = None
        if getattr(args, "block", None) is not None:
            block = [part.strip() for part in str(args.block).split(",")
                     if part.strip()]
        report = verify(
            args.range,
            repo=getattr(args, "repo", ".") or ".",
            pr_body=pr_text,
            pr_body_label=pr_label,
            contract=getattr(args, "contract", None),
            ledger_dir=getattr(args, "ledger_dir", None),
            block=block,
        )
        text = render_markdown(report) if args.format == "md" else render_json(report)
        sys.stdout.buffer.write(text.encode("utf-8"))
        return report.exit_code
    except (VerifyError, ContractError, OSError, UnicodeError) as exc:
        sys.stderr.write(f"ctxpack verify: {exc}\n")
        return 2


class GitRepo:
    """Git reads with locale and config pinned so output bytes stay stable."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        env["GIT_PAGER"] = "cat"
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["GIT_TERMINAL_PROMPT"] = "0"
        command = [
            "git", "-C", os.fspath(self.root),
            "-c", "core.quotepath=false",
            "-c", "core.autocrlf=false",
            "-c", "core.safecrlf=false",
            "-c", "i18n.logOutputEncoding=utf-8",
            *args,
        ]
        try:
            proc = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, check=False)
        except FileNotFoundError as exc:
            raise VerifyError("git is not available") from exc
        if check and proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise VerifyError(detail or f"git {args[0]} failed")
        return proc

    def rev_parse(self, rev: str) -> str:
        proc = self.run("rev-parse", "--verify", f"{rev}^{{commit}}")
        sha = proc.stdout.decode("utf-8").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise VerifyError(f"could not resolve {rev}")
        return sha

    def commits(self, base: str, head: str) -> list[tuple[str, str]]:
        proc = self.run(
            "log", "--reverse", "--format=%H%x1e%B%x1f", f"{base}..{head}")
        text = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        rows: list[tuple[str, str]] = []
        for part in text.split("\x1f"):
            part = part.strip("\n")
            if not part:
                continue
            sha, sep, message = part.partition("\x1e")
            sha = sha.strip().lower()
            if sep and re.fullmatch(r"[0-9a-f]{40}", sha):
                rows.append((sha, message.replace("\r\n", "\n")))
        return rows

    def merge_base(self, base: str, head: str) -> str | None:
        """Best common ancestor, or None when the histories do not meet."""
        proc = self.run("merge-base", base, head, check=False)
        if proc.returncode != 0:
            return None
        sha = proc.stdout.decode("utf-8").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            return None
        return sha

    def changed(self, base: str, head: str) -> list[str]:
        """Paths that differ between ``base`` and ``head``.

        ``verify`` passes the merge base (or the named base when the
        histories do not meet), which is ``git diff base...head``.
        """
        proc = self.run("diff", "--name-only", "-z", base, head)
        names: list[str] = []
        for raw in proc.stdout.split(b"\0"):
            if not raw:
                continue
            names.append(raw.decode("utf-8").replace("\\", "/"))
        return sorted(set(names))

    def tree(self, rev: str) -> set[str]:
        proc = self.run("ls-tree", "-r", "--name-only", "-z", rev)
        paths: set[str] = set()
        for raw in proc.stdout.split(b"\0"):
            if raw:
                paths.add(raw.decode("utf-8").replace("\\", "/"))
        return paths

    def blob(self, rev: str, path: str) -> bytes | None:
        proc = self.run("cat-file", "blob", f"{rev}:{path}", check=False)
        if proc.returncode != 0:
            return None
        return proc.stdout

    def contains(self, rev: str, literal: str) -> bool:
        proc = self.run(
            "grep", "-F", "-I", "--quiet", "-e", literal, rev, "--",
            check=False)
        if proc.returncode in (0, 1):
            return proc.returncode == 0
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise VerifyError(detail or "git grep failed")


class _BlobCache:
    def __init__(self, git: GitRepo) -> None:
        self.git = git
        self._cache: dict[tuple[str, str], str | None] = {}

    def text(self, rev: str, path: str) -> str | None:
        key = (rev, path)
        if key not in self._cache:
            raw = self.git.blob(rev, path)
            if raw is None or b"\0" in raw:
                self._cache[key] = None
            else:
                self._cache[key] = (
                    raw.decode("utf-8", "replace")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n"))
        return self._cache[key]


def _split_range(spec: str) -> tuple[str, str]:
    """Split ``A..B`` or ``A...B`` into the two refs.

    Both spellings name the same commits. The file diff is three-dot
    either way; this only rejects a spec that is not two refs.
    """
    if not isinstance(spec, str) or any(ch.isspace() for ch in spec):
        raise VerifyError("range must be A..B or A...B")
    if spec.count("...") == 1 and spec.count("..") == 1:
        base, head = spec.split("...", 1)
    elif "..." not in spec and spec.count("..") == 1:
        base, head = spec.split("..", 1)
    else:
        raise VerifyError("range must be A..B or A...B")
    if not base or not head:
        raise VerifyError("range must be A..B or A...B")
    return base, head


def _load_contract(
    contract: str | os.PathLike[str] | TaskContract | None,
) -> TaskContract | None:
    if contract is None or contract == "":
        return None
    if isinstance(contract, TaskContract):
        return contract
    return load_contract(Path(os.fspath(contract)))


def _resolve_block(
    repo: Path,
    block: Sequence[str] | None,
    contract: TaskContract | None,
) -> tuple[str, ...]:
    if block is not None:
        codes = list(block)
    else:
        configured = _toml_block(repo)
        if configured is not None:
            codes = configured
        elif contract is not None:
            codes = list(contract.blocking_codes)
        else:
            codes = []
    unknown = sorted({code for code in codes if code not in FINDING_CODES})
    if unknown:
        raise VerifyError("unknown blocking code: " + ", ".join(unknown))
    return tuple(sorted(set(codes)))


def _toml_block(repo: Path) -> list[str] | None:
    path = repo / "ctxpack.toml"
    if not path.is_file():
        return None
    try:
        data = load_toml_mapping(path.read_text(encoding="utf-8"))
    except ContractError as exc:
        raise VerifyError(str(exc)) from exc
    section = data.get("verify")
    if not isinstance(section, dict) or "block" not in section:
        return None
    block = section["block"]
    if (not isinstance(block, list)
            or not all(isinstance(item, str) and item for item in block)):
        raise VerifyError(
            "ctxpack.toml [verify] block must be a list of strings")
    return list(block)


def _load_facts(ledger: Path) -> list[_Fact]:
    """Ledger facts, classified with the same live set the brief uses.

    ``events.jsonl`` supersession and retraction rows are folded in as
    well, so a declared override counts whether it was written on the
    section or only in the event journal.
    """
    if not ledger.is_dir():
        return []
    paths = sorted(
        (path for path in ledger.iterdir()
         if path.is_file() and path.name.startswith("session-")
         and path.name.endswith(".ctx")),
        key=lambda path: path.name)
    pending: list[tuple[str, str, tuple[str, ...], str, str]] = []
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            doc = parse(path.read_text(encoding="utf-8"), level=2,
                        filename=path.name)
        except Exception as exc:
            raise VerifyError(f"cannot parse ledger file {path.name}") from exc
        session = path.name[len("session-"):-len(".ctx")]
        for row in ledger_facts(doc):
            section = row["section"]
            text_list: list[str] = [str(row["text"])]
            for child in section.children:
                if isinstance(child, KeyValue) and child.value not in text_list:
                    text_list.append(child.value)
            fact_id = str(row["fact_id"] or "")
            kind = str(row["kind"])
            status = _kv(section, "STATUS").strip().lower()
            turn = row["turn"] if isinstance(row["turn"], int) else 0
            pending.append((fact_id, kind, tuple(text_list), path.name, status))
            records.append({
                "fact_id": fact_id.lower(),
                "kind": kind,
                "text": str(row["text"]),
                "turn": turn,
                "session": session,
                "basis": _kv(section, "BASIS"),
                "supersedes": (_kv(section, "SUPERSEDES-FACT-ID") or "").lower(),
                "supersedes_reason": _kv(section, "SUPERSEDES-REASON"),
                "retracts": (_kv(section, "RETRACTS-FACT-ID") or "").lower(),
                "retract_reason": _kv(section, "REASON") if kind == "RETRACT" else "",
                "ambiguous": _kv(section, "ID-AMBIGUOUS"),
            })
    records.extend(_event_records(ledger))
    live = live_set_from_records(records)
    superseded_ids = {item.old_id for item in live.replacements}
    for row in records:
        base = str(row.get("supersedes") or "")
        head = str(row.get("fact_id") or "")
        if base and head and base != head:
            superseded_ids.add(base.lower())
    retracted_ids = {fact_id for fact_id, _reason in live.retracted}
    stale_ids = {item.fact_id for item in live.stale}
    text_by_id: dict[str, str] = {}
    for fact_id, _kind, text_values, _source, _status in pending:
        if fact_id:
            text_by_id[fact_id.lower()] = "\n".join(text_values)
    successor_by_old: dict[str, str] = {}
    for repl in live.replacements:
        parts = [successor_by_old.get(repl.old_id, ""), repl.new_text,
                 text_by_id.get(repl.new_id, "")]
        successor_by_old[repl.old_id] = "\n".join(part for part in parts if part)
    facts: list[_Fact] = []
    for fact_id, kind, text_values, source, status in pending:
        fid = fact_id.lower()
        is_superseded = (
            status == "superseded" or (bool(fid) and fid in superseded_ids))
        dropped = is_superseded or (
            bool(fid) and fid in (retracted_ids | stale_ids))
        facts.append(_Fact(
            fact_id=fact_id,
            kind=kind,
            texts=text_values,
            source=source,
            superseded=is_superseded,
            live=not dropped,
            successor_text=successor_by_old.get(fid, ""),
        ))
    facts.sort(key=lambda fact: (fact.source, fact.fact_id, fact.kind, fact.texts))
    return facts


def _event_records(ledger: Path) -> list[dict[str, Any]]:
    path = ledger / "events.jsonl"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerifyError("cannot read ledger events") from exc
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        detail = _detail_map(row.get("detail"))
        event = row.get("event")
        if event == "fact_superseded":
            base = str(row.get("fact_id") or "").lower()
            head = str(detail.get("by") or "").lower()
            if base and head and base != head:
                records.append({
                    "fact_id": head,
                    "kind": "DECISION",
                    "text": "",
                    "turn": row.get("turn") or 0,
                    "session": str(row.get("session") or ""),
                    "supersedes": base,
                    "supersedes_reason": str(detail.get("reason") or ""),
                })
        elif event == "fact_retracted":
            target = str(row.get("fact_id") or "").lower()
            if target:
                records.append({
                    "fact_id": "",
                    "kind": "",
                    "retracts": target,
                    "retract_reason": str(detail.get("reason") or ""),
                })
    return records


def _detail_map(value: Any) -> dict[str, Any]:
    """A JSON object, or an empty map when the field is absent or not an object."""
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _collect_markers(
    commits: Sequence[tuple[str, str]],
    pr_body: str | None,
    pr_label: str,
) -> list[_Marked]:
    marked: list[_Marked] = []
    for sha, message in commits:
        for kind, line, payload in _marker_lines(message):
            marked.append(_Marked(kind, line, payload, sha))
    if pr_body is not None:
        for kind, line, payload in _marker_lines(pr_body):
            marked.append(_Marked(kind, line, payload, pr_label))
    return marked


def _marker_lines(text: str) -> list[tuple[str, str, str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    found: list[tuple[str, str, str]] = []
    fenced = False
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        prose = _INLINE_CODE.sub(" ", stripped)
        match = _MARKER_LINE.match(prose)
        if not match:
            continue
        kind = match.group(1).lower()
        payload = " ".join(match.group(2).split())
        if len(payload) < 8:
            continue
        found.append((kind, " ".join(stripped.split()), payload))
    return found


def _unrecorded(
    marked: Sequence[_Marked],
    facts: Sequence[_Fact],
    ledger: Path,
) -> list[Finding]:
    known = _supersede_ids(ledger)
    corpus = "\n".join(text for fact in facts for text in fact.texts)
    norm_corpus = " ".join(corpus.split())
    rows: list[Finding] = []
    for mark in marked:
        payload = " ".join(mark.payload.split())
        if payload in norm_corpus:
            continue
        if mark.kind == "supersedes" and _supersede_recorded(payload, known):
            continue
        rows.append(_finding(
            "UNRECORDED_MARKER", mark.location,
            f"{_MARKER_LABEL[mark.kind]} marker is not recorded in the ledger",
            mark.line, None))
    return rows


def _supersede_ids(ledger: Path) -> set[str]:
    ids: set[str] = set()
    events = ledger / "events.jsonl"
    if events.is_file():
        try:
            text = events.read_text(encoding="utf-8")
        except OSError as exc:
            raise VerifyError("cannot read ledger events") from exc
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or row.get("event") != "fact_superseded":
                continue
            detail = _detail_map(row.get("detail"))
            for token in (str(row.get("fact_id") or ""), str(detail.get("by") or "")):
                if _ID_TOKEN.fullmatch(token):
                    ids.add(token.lower())
    if not ledger.is_dir():
        return ids
    for path in sorted(ledger.glob("session-*.ctx"), key=lambda item: item.name):
        try:
            body = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise VerifyError(f"cannot read ledger file {path.name}") from exc
        for match in _SUPERSEDES_FIELD.finditer(body):
            ids.add(match.group(1).lower())
    return ids


def _supersede_recorded(payload: str, known: set[str]) -> bool:
    return any(token.lower() in known for token in _ID_TOKEN.findall(payload))


def _stale(
    facts: Sequence[_Fact],
    git: GitRepo,
    base: str,
    head: str,
    trees: Mapping[str, set[str]],
) -> list[Finding]:
    rows: list[Finding] = []
    for fact in facts:
        if not fact.live:
            continue
        for ident in _identifiers("\n".join(fact.texts)):
            if _identifier_stale(ident, git, base, head, trees):
                rows.append(_finding(
                    "STALE_IDENTIFIER", fact.source,
                    "live fact names an identifier missing at head",
                    ident, fact.fact_id or None))
    return rows


def _identifiers(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        token = token.strip().strip("`").replace("\\", "/")
        if token in seen or not _concrete(token):
            return
        seen.add(token)
        found.append(token)

    for match in _BACKTICK.finditer(text):
        add(match.group(1))
    blanked = _BACKTICK.sub(" ", text)
    for match in _BARE_PATH.finditer(blanked):
        add(match.group(1))
    found.sort()
    return found


def _concrete(token: str) -> bool:
    if len(token) < 4 or len(token) > 200 or any(ch.isspace() for ch in token):
        return False
    if "://" in token:
        return False
    return _is_path(token) or _SYMBOL.fullmatch(token) is not None


def _is_path(token: str) -> bool:
    if "://" in token or any(ch.isspace() for ch in token):
        return False
    if "/" in token:
        return True
    return token.endswith(_TEXT_EXTS)


def _path_exists(token: str, tree: set[str]) -> bool:
    if token in tree:
        return True
    if "/" not in token:
        suffix = "/" + token
        return any(path.endswith(suffix) for path in tree)
    return False


def _identifier_stale(
    ident: str,
    git: GitRepo,
    base: str,
    head: str,
    trees: Mapping[str, set[str]],
) -> bool:
    """True when ``ident`` exists at ``base`` and is gone at ``head``.

    ``base`` is the merge base when the range has one, so a path added
    only on the named base after the branch point is not stale.
    """
    if _is_path(ident):
        return (_path_exists(ident, trees[base])
                and not _path_exists(ident, trees[head]))
    if _SYMBOL.fullmatch(ident) is None:
        return False
    return git.contains(base, ident) and not git.contains(head, ident)


def _superseded_in_code(
    facts: Sequence[_Fact],
    changed: Sequence[str],
    blobs: _BlobCache,
    head: str,
) -> list[Finding]:
    texts: list[tuple[str, str]] = []
    for path in changed:
        body = blobs.text(head, path)
        if body is not None:
            texts.append((path, body))
    rows: list[Finding] = []
    for fact in facts:
        if not fact.superseded:
            continue
        for ident in _identifiers("\n".join(fact.texts)):
            if _ident_in(ident, fact.successor_text):
                continue
            for path, body in texts:
                if _ident_in(ident, body):
                    rows.append(_finding(
                        "SUPERSEDED_STILL_IN_CODE", path,
                        "superseded fact identifier still appears in a changed file",
                        ident, fact.fact_id or None))
    return rows


def _ident_in(ident: str, text: str) -> bool:
    """True when ``ident`` appears as its own token, not inside a longer name."""
    if not ident or not text:
        return False
    return re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(ident)}(?![A-Za-z0-9_])",
        text,
    ) is not None


def _conflicts(
    marked: Sequence[_Marked],
    facts: Sequence[_Fact],
    ledger: Path,
    changed: Sequence[str],
    repo: Path,
) -> list[Finding]:
    decisions = _decision_rows(marked, facts, changed, repo, ledger)
    if not decisions:
        return []
    entities = []
    locations: dict[str, str] = {}
    for index, (text, location, fact_id, sup_id, sup_reason) in enumerate(decisions):
        entities.append(_Entity(
            name=f"DECISION-{index:04d}",
            fields=[
                _Field("DECISION", text),
                _Field("BASIS", "marker_stated"),
                _Field("FACT-ID", fact_id),
                _Field("SUPERSEDES-FACT-ID", sup_id),
                _Field("SUPERSEDES-REASON", sup_reason),
            ],
            sources=[_Source(10**6 + index)],
        ))
        locations[fact_id] = location
    rows = lint_decisions(entities, os.fspath(ledger), "verify01")
    findings: list[Finding] = []
    for row in rows:
        if row.get("resolved"):
            continue
        against_raw = str(row.get("against_fact_id") or "")
        decision_id = str(row.get("decision_fact_id") or "")
        against_id = against_raw if against_raw else None
        findings.append(_finding(
            "CONSTRAINT_CONFLICT",
            locations.get(decision_id, "ledger"),
            "decision conflicts with a live constraint",
            str(row.get("phrase") or ""),
            against_id))
    return findings


def _decision_rows(
    marked: Sequence[_Marked],
    facts: Sequence[_Fact],
    changed: Sequence[str],
    repo: Path,
    ledger: Path,
) -> list[tuple[str, str, str, str, str]]:
    """(marker line, location, fact id, supersedes id, supersedes reason)."""
    grouped: dict[str, list[_Marked]] = {}
    order: list[str] = []
    for mark in marked:
        if mark.location not in grouped:
            grouped[mark.location] = []
            order.append(mark.location)
        grouped[mark.location].append(mark)
    raw: list[tuple[str, str, str, str]] = []
    for location in order:
        lines = grouped[location]
        for index, mark in enumerate(lines):
            if mark.kind != "decision":
                continue
            sup_id, sup_reason = "", ""
            if index + 1 < len(lines) and lines[index + 1].kind == "supersedes":
                sup_id, sup_reason = _split_supersedes(lines[index + 1].payload)
            line = mark.line if mark.line.lower().startswith("decision:") else (
                "Decision: " + mark.payload)
            raw.append((line, location, sup_id, sup_reason))
    for fact in facts:
        if fact.kind != "DECISION" or fact.superseded:
            continue
        if not _ledger_file_changed(fact.source, ledger, repo, changed):
            continue
        text = next((item for item in fact.texts
                     if item.lower().lstrip().startswith("decision:")), "")
        if not text:
            continue
        raw.append((" ".join(text.split()), fact.source, "", ""))
    dedup: dict[str, tuple[str, str, str, str]] = {}
    for line, location, sup_id, sup_reason in raw:
        payload = line.split(":", 1)[1].strip() if ":" in line else line
        key = " ".join(payload.split())
        dedup.setdefault(key, (line, location, sup_id, sup_reason))
    rows: list[tuple[str, str, str, str, str]] = []
    for key in sorted(dedup):
        line, location, sup_id, sup_reason = dedup[key]
        fact_id = _decision_fact_id(key, facts)
        rows.append((line, location, fact_id, sup_id, sup_reason))
    return rows


def _split_supersedes(payload: str) -> tuple[str, str]:
    match = _SUPERSEDES_PAYLOAD.match(payload.strip())
    if not match or not match.group(2).strip():
        return "", ""
    return match.group(1).lower(), match.group(2).strip()


def _decision_fact_id(payload: str, facts: Sequence[_Fact]) -> str:
    needle = " ".join(payload.split())
    for fact in facts:
        if fact.fact_id and any(needle in " ".join(text.split()) for text in fact.texts):
            return fact.fact_id.lower()
    return hashlib.sha256(needle.encode("utf-8")).hexdigest()[:16]


def _ledger_file_changed(
    source: str,
    ledger: Path,
    repo: Path,
    changed: Sequence[str],
) -> bool:
    try:
        rel = (ledger / source).resolve().relative_to(repo.resolve()).as_posix()
    except (OSError, ValueError):
        return False
    return rel in set(changed)


def _attestation(
    pr_body: str,
    head: str,
    contract: TaskContract | None,
    label: str,
) -> list[Finding]:
    compiled: list[re.Pattern[str]] = list(_DEFAULT_SHA)
    if contract is not None:
        for raw_pattern in contract.attestation_sha_patterns:
            compiled.append(re.compile(raw_pattern))
    found: list[str] = []
    seen: set[str] = set()
    for compiled_pattern in compiled:
        for match in compiled_pattern.finditer(pr_body):
            token = match.group(1).strip().lower()
            if token not in seen:
                seen.add(token)
                found.append(token)
    rows: list[Finding] = []
    if contract is not None and contract.require_attestation_sha and not found:
        rows.append(_finding(
            "ATTESTATION_SHA_MISMATCH", label,
            "attestation SHA does not match head",
            "missing", None))
    for token in found:
        if not re.fullmatch(r"[0-9a-f]{7,40}", token) or not head.startswith(token):
            rows.append(_finding(
                "ATTESTATION_SHA_MISMATCH", label,
                "attestation SHA does not match head",
                token, None))
    return rows


def _claims(
    pr_body: str,
    contract: TaskContract | None,
    label: str,
) -> list[Finding]:
    visible = _unfenced(pr_body)
    needs = contract is not None and contract.require_test_evidence
    not_run = _NOT_RUN.search(visible)
    match = _GREEN_CLAIM.search(visible)
    has_evidence = any(pattern.search(visible) for pattern in _EVIDENCE)
    # A green claim contradicted by a not-run admission stays unverified.
    # A standalone admission counts only when the contract requires
    # evidence and the body has none: a later "N passed" count is that
    # evidence (a historical "could not run" note followed by a pass count).
    if not_run is not None and match is not None:
        claim = " ".join(match.group(0).split())
        return [_finding(
            "UNVERIFIED_CLAIM", label,
            "claim states tests were not run",
            claim, None)]
    if not_run is not None and needs and not has_evidence:
        claim = " ".join(not_run.group(0).split())
        return [_finding(
            "UNVERIFIED_CLAIM", label,
            "claim states tests were not run",
            claim, None)]
    if match is None:
        return []
    claim = " ".join(match.group(0).split())
    if needs and not has_evidence:
        return [_finding(
            "UNVERIFIED_CLAIM", label,
            "claim lacks required test evidence",
            claim, None)]
    return []


def _contract_rules(
    contract: TaskContract,
    changed: Sequence[str],
    blobs: _BlobCache,
    base: str,
    head: str,
) -> list[Finding]:
    rows: list[Finding] = []
    for path in changed:
        for pattern in contract.forbidden_paths:
            if _glob_match(path, pattern):
                rows.append(_finding(
                    "CONTRACT_RULE_VIOLATION", path,
                    "changed file matches a forbidden path",
                    f"forbidden_paths:{pattern}", None))
        if contract.allowed_paths and not any(
                _glob_match(path, pattern) for pattern in contract.allowed_paths):
            rows.append(_finding(
                "CONTRACT_RULE_VIOLATION", path,
                "changed file is outside allowed paths",
                "allowed_paths", None))
    for rule in contract.flag_off_invariants:
        rows.extend(_flag_rule(rule, changed, blobs, base, head))
    for pattern, terms in contract.forbidden_vocabulary:
        for path in changed:
            if not _glob_match(path, pattern):
                continue
            body = blobs.text(head, path)
            if body is None:
                continue
            for term in terms:
                if term in body:
                    rows.append(_finding(
                        "CONTRACT_RULE_VIOLATION", path,
                        "changed file contains forbidden vocabulary",
                        f"forbidden_vocabulary:{term}", None))
    for pattern, terms in contract.required_vocabulary:
        for path in changed:
            if not _glob_match(path, pattern):
                continue
            body = blobs.text(head, path)
            if body is None:
                continue
            for term in terms:
                if term not in body:
                    rows.append(_finding(
                        "CONTRACT_RULE_VIOLATION", path,
                        "changed file misses required vocabulary",
                        f"required_vocabulary:{term}", None))
    return rows


def _flag_rule(
    rule: FlagOffInvariant,
    changed: Sequence[str],
    blobs: _BlobCache,
    base: str,
    head: str,
) -> list[Finding]:
    rows: list[Finding] = []
    for path in changed:
        if any(_glob_match(path, pattern) for pattern in rule.config_globs):
            before = _flag_value(blobs.text(base, path), rule.flag)
            after = _flag_value(blobs.text(head, path), rule.flag)
            if (after is not None and after.lower() in _ON
                    and (before is None or before.lower() not in _ON)):
                rows.append(_finding(
                    "CONTRACT_RULE_VIOLATION", path,
                    "changed file flips a default-off flag on",
                    f"flag_off:{rule.flag}", None))
        if any(_glob_match(path, pattern) for pattern in rule.guarded_globs):
            body = blobs.text(head, path)
            if body is not None and re.search(
                    rf"\b{re.escape(rule.flag)}\b", body) is None:
                rows.append(_finding(
                    "CONTRACT_RULE_VIOLATION", path,
                    "changed file bypasses a flag guard",
                    f"flag_guard:{rule.flag}", None))
    return rows


def _flag_value(text: str | None, flag: str) -> str | None:
    if not text:
        return None
    pattern = re.compile(
        rf"(?m)^[ \t]*[\"']?{re.escape(flag)}[\"']?[ \t]*[:=][ \t]*"
        rf"[\"']?([A-Za-z0-9_.-]+)[\"']?")
    found = pattern.findall(text)
    return found[-1] if found else None


def _version_pins(
    contract: TaskContract,
    changed: Sequence[str],
    blobs: _BlobCache,
    head: str,
) -> list[Finding]:
    rows: list[Finding] = []
    for key, pin in contract.pinned_versions:
        if _pin_key_is_path(key):
            for path in changed:
                if not _glob_match(path, key) and path != key:
                    continue
                body = blobs.text(head, path)
                if body is None:
                    continue
                reasons = _pin_reasons(body, pin, _pin_label(key, pin))
                if reasons:
                    rows.append(_finding(
                        "VERSION_PIN_DRIFT", path,
                        "pinned version does not match a changed file",
                        f"pin={pin}; {','.join(reasons)}", None))
        else:
            for path in changed:
                body = blobs.text(head, path)
                if body is None:
                    continue
                values = _field_values(body, key)
                if any(value != pin for value in values):
                    rows.append(_finding(
                        "VERSION_PIN_DRIFT", path,
                        "pinned version does not match a changed file",
                        f"pin={pin}; field-mismatch", None))
    return rows


def _pin_key_is_path(key: str) -> bool:
    return any(ch in key for ch in "*?[") or "/" in key or "." in key


def _pin_label(key: str, pin: str) -> str:
    """Name a line must mention before a pin rule looks at it.

    A field key is that name. A path or glob pin uses the package prefix
    of ``jev-1.13.0`` (``jev``). A bare semver has no extra label, so
    every line in the pinned file is in scope.
    """
    if not _pin_key_is_path(key):
        return key
    match = re.match(r"^([A-Za-z][\w]*?)-\d+\.\d+\.\d+$", pin)
    return match.group(1) if match else ""


def _pin_reasons(text: str, pin: str, label: str) -> list[str]:
    reasons: list[str] = []
    if pin not in text:
        reasons.append("missing-exact")
    scoped = _lines_mentioning(text, label) if label else text
    if _FLOATING.search(scoped):
        reasons.append("floating-alias")
    if _family_mismatch(scoped, pin):
        reasons.append("mismatched-token")
    reasons.sort()
    return reasons


def _lines_mentioning(text: str, label: str) -> str:
    return "\n".join(line for line in text.splitlines() if label in line)


def _family_mismatch(text: str, pin: str) -> bool:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)$", pin)
    if not match:
        return False
    major, minor, patch = match.group(1), match.group(2), match.group(3)
    exact = f"{major}.{minor}.{patch}"
    pattern = re.compile(
        rf"(?<![\w.]){re.escape(major)}\.{re.escape(minor)}(?:\.\d+)?(?![\w.])")
    return any(token != exact for token in pattern.findall(text))


def _field_values(text: str, field: str) -> list[str]:
    pattern = re.compile(
        rf"(?m)(?:^|[^A-Za-z0-9_])[\"']?{re.escape(field)}[\"']?\s*[:=]\s*"
        rf"(?:[\"']([^\"'\n]+)[\"']|([A-Za-z0-9._*^~+-]+))")
    values: list[str] = []
    for quoted, bare in pattern.findall(text):
        values.append(quoted or bare)
    return values


def _effective_blocking(
    blocking: tuple[str, ...],
    findings: Sequence[Finding],
    pr_body: str | None,
    head: str,
) -> tuple[str, ...]:
    """Blocking codes, with one-way paths always blocking unless waived.

    A waiver is an unfenced ``one-way-ack: <reason>`` line plus a
    ``verified-sha:`` that is a 7+ hex prefix of ``head``. The finding
    stays in the report; only the block is removed. Advisory mode (an
    empty blocking list, or a list that names other codes) does not
    waive an unacknowledged one-way touch.
    """
    codes = set(blocking)
    touched = any(row.code == "ONE_WAY_PATH_TOUCHED" for row in findings)
    if touched and _one_way_acknowledged(pr_body, head):
        codes.discard("ONE_WAY_PATH_TOUCHED")
    elif touched:
        codes.add("ONE_WAY_PATH_TOUCHED")
    return tuple(sorted(codes))


def _one_way_acknowledged(pr_body: str | None, head: str) -> bool:
    if not pr_body:
        return False
    visible = _unfenced(pr_body)
    if _ONE_WAY_ACK.search(visible) is None:
        return False
    shas = [match.group(1).lower() for match in _VERIFIED_SHA_LINE.finditer(visible)]
    if not shas:
        return False
    head_sha = head.lower()
    return all(
        re.fullmatch(r"[0-9a-f]{7,40}", token) and head_sha.startswith(token)
        for token in shas)


def _one_way_paths(
    contract: TaskContract,
    changed: Sequence[str],
) -> list[Finding]:
    rows: list[Finding] = []
    if not contract.one_way_paths:
        return rows
    for path in changed:
        for pattern in contract.one_way_paths:
            if _glob_match(path, pattern):
                rows.append(_finding(
                    "ONE_WAY_PATH_TOUCHED", path,
                    "changed file matches a one-way path",
                    f"one_way_paths:{pattern}", None))
    return rows


@dataclass(frozen=True)
class _Attestation:
    payload: str
    status: str
    shas: tuple[str, ...]
    sha_invalid: bool


def _verifier_evidence(
    pr_body: str,
    head: str,
    contract: TaskContract,
    label: str,
) -> list[Finding]:
    """Require an explicit passing verifier attestation. Fail closed.

    Accepted unfenced forms (label case-insensitive):

    - ``verifier: <command> | pass | <sha>``
    - ``verifier: <command> pass @ <sha>``
    - ``verifier: <command> pass (<sha>)``
    - ``verifier: pass <sha>``
    - ``verifier-cmd: <command>`` plus ``verifier-result: pass``

    Status must be ``pass``, ``ok``, ``passed``, or ``green``. A SHA is
    optional; when present it must be at least 7 hex characters and a
    prefix of ``head``. When ``verifier_command`` is set, that text must
    appear on the attestation. Angle-bracket placeholders are ignored,
    so an unfilled template is not a pass.
    """
    visible = _unfenced(pr_body)
    command = contract.verifier_command.strip()
    candidates = _verifier_candidates(visible)
    if not candidates:
        return [_finding(
            "VERIFIER_EVIDENCE_MISSING", label,
            "verifier evidence is missing",
            "missing", None)]
    defects = [
        _attestation_defect(row, command, head) for row in candidates]
    if any(defect is None for defect in defects):
        return []
    return [_verifier_finding(label, defects[0] or "missing", command)]


def _verifier_candidates(visible: str) -> list[_Attestation]:
    rows: list[_Attestation] = []
    for payload in _real_payloads(_labeled_lines(visible, "verifier")):
        rows.append(_payload_attestation(payload))
    commands = _real_payloads(_labeled_lines(visible, "verifier-cmd"))
    results = _real_payloads(_labeled_lines(visible, "verifier-result"))
    paired = _pair_attestation(commands, results)
    if paired is not None:
        rows.append(paired)
    return rows


def _labeled_lines(text: str, label: str) -> list[str]:
    pattern = re.compile(
        rf"(?im)^[ \t>*-]*(?:\*{{1,2}}|_{{1,2}})?"
        rf"{re.escape(label)}"
        rf"(?:\*{{1,2}}|_{{1,2}})?\s*:\s*(.*?)\s*$")
    return [match.group(1).strip() for match in pattern.finditer(text)]


def _real_payloads(lines: Iterable[str]) -> list[str]:
    """Drop unfilled template lines. ``<command>`` is not an attestation."""
    return [line for line in lines if "<" not in line and ">" not in line]


def _canon_status(token: str) -> str:
    return re.sub(r"[-_]+", " ", token.strip().lower())


def _payload_attestation(payload: str) -> _Attestation:
    _name, status, sha, sha_invalid = _parse_verifier_payload(payload)
    shas = (sha.lower(),) if sha else ()
    if sha_invalid and not shas:
        shas = ("invalid",)
    return _Attestation(payload, status, shas, sha_invalid)


def _parse_verifier_payload(payload: str) -> tuple[str, str, str, bool]:
    """Return ``(name, status, sha, sha_invalid)``."""
    if "|" in payload:
        return _parse_verifier_pipes(payload)
    for pattern in (_VERIFIER_AT, _VERIFIER_PAREN, _VERIFIER_TRAIL):
        match = pattern.fullmatch(payload.strip())
        if match is None:
            continue
        status = _canon_status(match.group("status") or "")
        sha = (match.group("sha") or "").lower()
        name = (match.group("name") or "").strip()
        return name, status, sha, False
    return payload.strip(), "", "", False


def _parse_verifier_pipes(payload: str) -> tuple[str, str, str, bool]:
    parts = [part.strip() for part in payload.split("|")]
    parts = [part for part in parts if part]
    if len(parts) == 3:
        name, status_tok, sha_tok = parts
        status = _canon_status(status_tok) if _STATUS_EXACT.fullmatch(status_tok) else ""
        if _SHA_EXACT.fullmatch(sha_tok):
            return name, status, sha_tok.lower(), False
        return name, status, sha_tok, True
    if len(parts) == 2:
        left, right = parts
        if _STATUS_EXACT.fullmatch(left) and _SHA_EXACT.fullmatch(right):
            return "", _canon_status(left), right.lower(), False
        if _STATUS_EXACT.fullmatch(right) and _SHA_EXACT.fullmatch(left):
            return "", _canon_status(right), left.lower(), False
        if _STATUS_EXACT.fullmatch(right):
            return left, _canon_status(right), "", False
        if _STATUS_EXACT.fullmatch(left):
            return right, _canon_status(left), "", False
    return payload.strip(), "", "", False


def _pair_attestation(
    commands: Sequence[str],
    results: Sequence[str],
) -> _Attestation | None:
    if not commands or not results:
        return None
    statuses: list[str] = []
    shas: list[str] = []
    sha_invalid = False
    for result in results:
        _name, status, sha, bad = _parse_verifier_payload(result)
        if bad:
            sha_invalid = True
        if status:
            statuses.append(status)
        if sha:
            shas.append(sha.lower())
    for command in commands:
        for token in command.split():
            if _SHA_EXACT.fullmatch(token):
                shas.append(token.lower())
    bad_status = next(
        (item for item in statuses if _canon_status(item) not in _PASS_STATUS),
        "")
    status = bad_status or (statuses[0] if statuses else "")
    payload = " ".join([*commands, *results])
    return _Attestation(payload, status, tuple(shas), sha_invalid)


def _attestation_defect(
    row: _Attestation,
    command: str,
    head: str,
) -> str | None:
    if row.sha_invalid:
        shown = next((item for item in row.shas if item != "invalid"), "")
        return f"sha:{shown or 'invalid'}"
    canon = _canon_status(row.status) if row.status else ""
    if canon not in _PASS_STATUS:
        return f"status:{canon}" if canon else "no-status"
    if command and command.lower() not in row.payload.lower():
        return "command"
    head_sha = head.lower()
    for sha in row.shas:
        token = sha.lower()
        if (not re.fullmatch(r"[0-9a-f]{7,40}", token)
                or not head_sha.startswith(token)):
            return f"sha:{token}"
    return None


def _verifier_finding(label: str, defect: str, command: str) -> Finding:
    if defect == "command":
        return _finding(
            "VERIFIER_EVIDENCE_MISSING", label,
            "verifier evidence does not name the contract command",
            command or "command", None)
    if defect.startswith("sha:"):
        evidence = defect.split(":", 1)[1] or "sha"
        return _finding(
            "VERIFIER_EVIDENCE_MISSING", label,
            "verifier evidence SHA does not match head",
            evidence, None)
    if defect == "no-status" or defect.startswith("status:"):
        evidence = defect.split(":", 1)[1] if ":" in defect else "no-status"
        return _finding(
            "VERIFIER_EVIDENCE_MISSING", label,
            "verifier evidence is not a pass",
            evidence or "no-status", None)
    return _finding(
        "VERIFIER_EVIDENCE_MISSING", label,
        "verifier evidence is missing",
        "missing", None)


def _unfenced(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    fenced = False
    for raw in text.split("\n"):
        if raw.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            kept.append(raw)
    return "\n".join(kept)


def _glob_normalize(value: str) -> str:
    """Slash-normalize and strip one leading ``./``.

    ``str.lstrip("./")`` would also strip the dot in ``.github``, so
    ``.github/**`` used to match ``github/x.yml``. Only a ``./`` prefix
    is a relative-path marker; a leading dot that is part of the name
    stays.
    """
    value = value.replace("\\", "/").strip()
    if value.startswith("./"):
        value = value[2:]
    return value


def _glob_match(path: str, pattern: str) -> bool:
    path = _glob_normalize(path)
    pattern = _glob_normalize(pattern)
    if _glob_parts(path.split("/"), pattern.split("/")):
        return True
    if "/" not in pattern:
        return _glob_parts([path.rsplit("/", 1)[-1]], pattern.split("/"))
    return False


def _glob_parts(path: list[str], pattern: list[str]) -> bool:
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        if _glob_parts(path, rest):
            return True
        return bool(path) and _glob_parts(path[1:], pattern)
    if not path:
        return False
    if _segment_match(path[0], head):
        return _glob_parts(path[1:], rest)
    return False


def _segment_match(segment: str, pattern: str) -> bool:
    return re.fullmatch(_segment_regex(pattern), segment) is not None


def _segment_regex(pattern: str) -> str:
    out: list[str] = []
    for char in pattern:
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
    return "".join(out)


def _finding(
    code: str,
    location: str,
    message: str,
    evidence: str,
    fact_id: str | None,
) -> Finding:
    cleaned = " ".join(str(evidence).split())[:_EVIDENCE_CHARS]
    fid = fact_id or None
    return Finding(
        code=code,
        severity=SEVERITY[code],
        fact_id=fid,
        location=location.replace("\\", "/"),
        message=message,
        evidence=cleaned,
    )


def _dedupe_sort(findings: Iterable[Finding]) -> list[Finding]:
    uniq: dict[tuple[str, str, str, str, str], Finding] = {}
    for row in findings:
        key = (row.code, row.location, row.fact_id or "", row.message, row.evidence)
        uniq.setdefault(key, row)
    return sorted(uniq.values(), key=lambda row: (
        row.code, row.location, row.fact_id or "", row.message, row.evidence))


__all__ = [
    "FINDING_CODES",
    "Finding",
    "MAX_FINDINGS",
    "VerifyError",
    "VerifyReport",
    "render_json",
    "render_markdown",
    "run_cli",
    "verify",
]
