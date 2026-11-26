"""One budgeted briefing for the hook, the CLI, Python, and MCP.

Priority (highest first, overridable from ``[brief]`` in ``ctxpack.toml``):

1. conflicts — unresolved supersession, forks, changed choices, retractions
2. constraints — open constraints
3. decisions
4. dead_ends — ``FAILED-APPROACH`` rows
5. plan — ``plan.md`` or ``plan.json`` in the ledger, when present
6. files — names only, scratch/temp/generated paths left out

Inside a kind, newest first. Ties break by record id ascending.
Plan steps stay in file order.
Near-duplicates (whitespace, case, punctuation) collapse before the
budget runs; a collapsed duplicate is not a live fact and is not a
budget drop. A fact that does not fit is omitted whole. When anything
is omitted, the last line names the count per kind.

``chars`` counts code points after ``\\n`` normalization. ``tokens``
is the offline estimate in :func:`ctxpack.core.tokens.count_budget`.
Neither unit imports tiktoken or opens a socket.

Without ``ack``, the same ledger and arguments produce the same bytes.
``ack=True`` appends ``CTX-Ack: <token>`` and a one-line echo instruction.
Those lines are stripped at capture time and are not ledger facts.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from ..core.packer.toml_parser import toml_parse
from ..core.tokens import count_budget, normalize_newlines
from .live_set import choice_was, live_set_from_records

DEFAULT_BRIEF_BUDGET = 12000
DEFAULT_UNIT = "chars"
DEFAULT_PRIORITY: tuple[str, ...] = (
    "conflicts",
    "constraints",
    "decisions",
    "dead_ends",
    "plan",
    "files",
)

_KIND_NOUNS = {
    "conflicts": ("conflict", "conflicts"),
    "constraints": ("constraint", "constraints"),
    "decisions": ("decision", "decisions"),
    "dead_ends": ("dead end", "dead ends"),
    "plan": ("plan item", "plan items"),
    "files": ("file", "files"),
}
_SECTION_TITLES = {
    "conflicts": "Conflicts and changed choices",
    "constraints": "Open constraints",
    "decisions": "Decisions",
    "dead_ends": "Dead ends",
    "plan": "Plan progress",
    "files": "Files",
}
_CONFLICT_SUBS = (
    ("ambiguous", "Supersession unresolved"),
    ("fork", "Conflicts (unresolved fork)"),
    ("changed", "Changed choices"),
    ("retracted", "Retracted"),
    ("stale", ""),
)
_SUB_RANK = {name: i for i, (name, _) in enumerate(_CONFLICT_SUBS)}
_CONFIG_NAMES = ("ctxpack.toml", ".ctxpack.toml")
_DUP_RE = re.compile(r"[^\w]+", re.UNICODE)
_NOISE_SEGMENTS = frozenset({
    "tmp", "temp", "scratch", "filler", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".git",
    ".tox", "htmlcov", ".venv", "venv",
})
# Output directories are noise only at the repo root. ``tools/build`` and
# ``docs/dist`` are real project paths.
_ROOT_NOISE_SEGMENTS = frozenset({"build", "dist"})
_NOISE_SUFFIXES = (".pyc", ".pyo", ".tmp", ".bak", ".swp", ".log", ".orig")
_SCRATCH_STEMS = ("tmp", "temp")
_SCRATCH_SEPARATORS = "_-."
_ACK_TOKEN_RE = re.compile(r"^[^\s]+$")


@dataclass(frozen=True)
class BriefConfig:
    """Composer settings. Explicit arguments override a file."""

    budget: int = DEFAULT_BRIEF_BUDGET
    unit: str = DEFAULT_UNIT
    priority: tuple[str, ...] = DEFAULT_PRIORITY


@dataclass(frozen=True)
class _Item:
    kind: str
    record_id: str
    session_ord: int
    turn: int
    text: str
    subtype: str = ""


@dataclass
class BriefResult:
    """One composed briefing and the counts that explain it."""

    text: str
    unit: str
    budget: int
    shown: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)
    live: dict[str, int] = field(default_factory=dict)
    ack_token: str = ""

    def to_json(self) -> str:
        """JSON whose ``text`` field is the markdown briefing."""
        payload = {
            "budget": self.budget,
            "dropped": self.dropped,
            "live": self.live,
            "shown": self.shown,
            "text": self.text,
            "unit": self.unit,
        }
        if self.ack_token:
            payload["ack_token"] = self.ack_token
        return json.dumps(
            payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def load_brief_settings(ledger_dir: str = ".claude/ctx") -> BriefConfig:
    """``[brief]`` from the ledger dir, its parent, or that parent's parent.

    The nearest file wins. A missing file is the default budget, unit,
    and priority. The search does not use the process environment.
    """
    cur = os.path.abspath(ledger_dir)
    for _ in range(3):
        for name in _CONFIG_NAMES:
            path = os.path.join(cur, name)
            if os.path.isfile(path):
                return _config_from_file(path)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return BriefConfig()


def brief(
    ledger_dir: str = ".claude/ctx",
    *,
    budget: Optional[int] = None,
    unit: Optional[str] = None,
    ack: bool = False,
    ack_token: Optional[str] = None,
    done_milestones: Iterable[str] = (),
    priority: Optional[Sequence[str]] = None,
) -> str:
    """Budgeted briefing text for ``ledger_dir``.

    Same bytes as the CLI and the MCP tool for the same ledger and
    arguments when ``ack`` is false. See :func:`brief_result` for the
    drop counts.
    """
    return brief_result(
        ledger_dir,
        budget=budget,
        unit=unit,
        ack=ack,
        ack_token=ack_token,
        done_milestones=done_milestones,
        priority=priority,
    ).text


def brief_result(
    ledger_dir: str = ".claude/ctx",
    *,
    budget: Optional[int] = None,
    unit: Optional[str] = None,
    ack: bool = False,
    ack_token: Optional[str] = None,
    done_milestones: Iterable[str] = (),
    priority: Optional[Sequence[str]] = None,
) -> BriefResult:
    """Compose the briefing and the per-kind shown/dropped/live counts."""
    settings = load_brief_settings(ledger_dir)
    resolved_budget = settings.budget if budget is None else int(budget)
    resolved_unit = settings.unit if unit is None else str(unit)
    if resolved_unit not in ("chars", "tokens"):
        raise ValueError(
            f"unknown brief unit {resolved_unit!r}; expected chars or tokens")
    if resolved_budget < 0:
        raise ValueError("brief budget must be >= 0")
    order = _resolve_priority(priority if priority is not None
                              else settings.priority)
    token = ""
    if ack:
        token = ack_token if ack_token else secrets.token_hex(8)
        if not _ACK_TOKEN_RE.fullmatch(token):
            raise ValueError("ack token must be a single token with no whitespace")
    items = _collapse(_collect_items(
        ledger_dir, done_milestones=done_milestones), order)
    live = _counts(items, order)
    text, shown, dropped = _fit(
        items, live, resolved_budget, resolved_unit, order, ack_token=token)
    return BriefResult(
        text=text,
        unit=resolved_unit,
        budget=resolved_budget,
        shown=shown,
        dropped=dropped,
        live=live,
        ack_token=token,
    )


def _config_from_file(path: str) -> BriefConfig:
    with open(path, encoding="utf-8") as handle:
        data = toml_parse(handle.read(), filename=path)
    table = data.get("brief") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return BriefConfig()
    budget = DEFAULT_BRIEF_BUDGET
    if "budget" in table:
        raw = table.get("budget")
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise ValueError(f"brief budget must be an integer, got {raw!r}")
        try:
            budget = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"brief budget must be an integer, got {raw!r}") from exc
        if budget < 0:
            raise ValueError("brief budget must be >= 0")
    unit = DEFAULT_UNIT
    if "unit" in table:
        unit = str(table.get("unit") or "").strip().lower()
        if unit not in ("chars", "tokens"):
            raise ValueError(
                f"unknown brief unit {unit!r}; expected chars or tokens")
    priority = DEFAULT_PRIORITY
    if "priority" in table:
        priority = _resolve_priority(table.get("priority"))
    return BriefConfig(budget=budget, unit=unit, priority=priority)


def _resolve_priority(raw: object) -> tuple[str, ...]:
    """Known kinds in the requested order. Missing kinds follow, default order."""
    if raw is None:
        return DEFAULT_PRIORITY
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    elif isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw if str(p).strip()]
    else:
        return DEFAULT_PRIORITY
    known = set(DEFAULT_PRIORITY)
    ordered: list[str] = []
    for name in parts:
        if name in known and name not in ordered:
            ordered.append(name)
    for name in DEFAULT_PRIORITY:
        if name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def _session_order(ledger_dir: str) -> list[str]:
    from .checkpoint import _journal_session_order
    return _journal_session_order(ledger_dir)


def _collect_items(ledger_dir: str, *,
                   done_milestones: Iterable[str]) -> list[_Item]:
    records, files = _load_ledger(ledger_dir)
    order = _session_order(ledger_dir)
    index = {sid: i for i, sid in enumerate(order)}
    for sid in sorted({str(row.get("session") or "") for row in records} - set(index)):
        if sid:
            index[sid] = len(index)

    def _ord(session: str) -> int:
        return index.get(session or "", -1)

    live = live_set_from_records(records, done_milestones=done_milestones)
    items: list[_Item] = []
    for amb in live.ambiguous:
        joined = ", ".join(f"`{match}`" for match in amb.matches) or "(none)"
        items.append(_Item(
            kind="conflicts",
            record_id=f"amb:{amb.token}",
            session_ord=10 ** 6,
            turn=0,
            subtype="ambiguous",
            text=f"- `{amb.token}` matches {joined}; not applied.",
        ))
    for fork_i, fork in enumerate(live.conflicts):
        roots = ", ".join(f"`{root}`" for root in fork.roots) or "(none)"
        lines = [
            f"- unresolved fork of {roots}; neither head supersedes the other.",
        ]
        for hid, text in fork.heads:
            shown = text if text else "(text not in this ledger)"
            lines.append(f"  - `{hid}`: {shown}")
        items.append(_Item(
            kind="conflicts",
            record_id=f"fork:{fork_i}:{fork.roots[0] if fork.roots else ''}",
            session_ord=10 ** 6,
            turn=0,
            subtype="fork",
            text="\n".join(lines),
        ))
    for repl in live.replacements:
        reason = f" — {repl.reason}" if repl.reason else ""
        was = choice_was(repl.old_text) if repl.old_text else "(not in ledger)"
        now = repl.new_text if repl.new_text else "(not in ledger)"
        items.append(_Item(
            kind="conflicts",
            record_id=repl.new_id or repl.old_id,
            session_ord=_ord(repl.session),
            turn=repl.turn,
            subtype="changed",
            text=(
                f"- `{repl.old_id}` → `{repl.new_id}`{reason}\n"
                f"  - was: {was}\n"
                f"  - now: {now}"
            ),
        ))
    for fid, reason in live.retracted:
        suffix = f" — {reason}" if reason else ""
        items.append(_Item(
            kind="conflicts",
            record_id=f"retract:{fid}",
            session_ord=10 ** 6,
            turn=0,
            subtype="retracted",
            text=f"- `{fid}` withdrawn{suffix}.",
        ))
    if live.stale:
        n = len(live.stale)
        noun = "item" if n == 1 else "items"
        items.append(_Item(
            kind="conflicts",
            record_id="stale",
            session_ord=-1,
            turn=0,
            subtype="stale",
            text=f"_Dropped {n} stale {noun} scoped to a done milestone._",
        ))

    kind_of = {
        "CONSTRAINT": "constraints",
        "DECISION": "decisions",
        "FAILED-APPROACH": "dead_ends",
    }
    for fact in live.facts:
        kind = kind_of.get(fact.kind)
        if not kind or not (fact.text or "").strip():
            continue
        items.append(_Item(
            kind=kind,
            record_id=fact.fact_id or fact.text,
            session_ord=_ord(fact.session),
            turn=fact.turn,
            text=fact.text.strip(),
        ))
    items.extend(_plan_items(ledger_dir))
    for row in files:
        path = str(row.get("text") or "").strip()
        if not path or _is_noise_path(path):
            continue
        items.append(_Item(
            kind="files",
            record_id=str(row.get("fact_id") or path),
            session_ord=_ord(str(row.get("session") or "")),
            turn=int(row.get("turn") or 0),
            text=path,
        ))
    return items


def _load_ledger(ledger_dir: str) -> tuple[list[dict], list[dict]]:
    from ..core.parser import parse as parse_ctx
    from .session_reader import (
        _kind_of,
        _kv,
        _primary_value,
        _sections,
        _turn_of,
    )

    try:
        names = os.listdir(ledger_dir)
    except OSError:
        return [], []
    sids = sorted(
        name[len("session-"):-len(".ctx")]
        for name in names
        if name.startswith("session-") and name.endswith(".ctx")
    )
    records: list[dict] = []
    files: list[dict] = []
    for sid in sids:
        path = os.path.join(ledger_dir, f"session-{sid}.ctx")
        try:
            with open(path, encoding="utf-8") as handle:
                doc = parse_ctx(handle.read(), level=2)
        except Exception:  # noqa: BLE001 — one bad ledger must not kill the brief
            continue
        for section in _sections(doc):
            kind = _kind_of(section)
            fid = (_kv(section, "FACT-ID") or "").lower()
            text = _primary_value(section)
            turn = _turn_of(section)
            row = {
                "fact_id": fid,
                "kind": kind,
                "text": text,
                "turn": turn,
                "session": sid,
                "basis": _kv(section, "BASIS"),
                "supersedes": (_kv(section, "SUPERSEDES-FACT-ID") or "").lower(),
                "supersedes_reason": _kv(section, "SUPERSEDES-REASON"),
                "retracts": (_kv(section, "RETRACTS-FACT-ID") or "").lower(),
                "retract_reason": _kv(section, "REASON") if kind == "RETRACT" else "",
                "ambiguous": _kv(section, "ID-AMBIGUOUS"),
            }
            records.append(row)
            if kind == "FILE" and text:
                files.append(row)
    return records, files


def _plan_items(ledger_dir: str) -> list[_Item]:
    md_path = os.path.join(ledger_dir, "plan.md")
    json_path = os.path.join(ledger_dir, "plan.json")
    rows: list[tuple[int, str]] = []
    if os.path.isfile(md_path):
        try:
            with open(md_path, encoding="utf-8") as handle:
                raw = normalize_newlines(handle.read())
        except OSError:
            return []
        for i, line in enumerate(raw.split("\n")):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            rows.append((i, text))
    elif os.path.isfile(json_path):
        try:
            with open(json_path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return []
        entries = payload.get("items") if isinstance(payload, dict) else payload
        if isinstance(entries, list):
            for i, entry in enumerate(entries):
                if isinstance(entry, str):
                    text = entry.strip()
                elif isinstance(entry, dict):
                    text = str(entry.get("text") or entry.get("title") or "").strip()
                    status = str(entry.get("status") or "").strip()
                    if status and text:
                        text = f"{text} [{status}]"
                else:
                    text = ""
                if text:
                    rows.append((i, text))
    items: list[_Item] = []
    for i, text in rows:
        items.append(_Item(
            kind="plan",
            record_id=f"plan:{i:06d}",
            session_ord=0,
            # Line index, kept ascending by :func:`_collapse` for this kind.
            turn=i,
            text=text,
        ))
    return items


def _scratch_stem(name: str) -> bool:
    """True for a scratch filename, not a real source name.

    Exact stems ``tmp`` and ``temp`` (``tmp.py``, ``temp.c``) and
    ``tmp`` plus ``_``, ``-``, or ``.`` (``tmp_widget.py``) are scratch.
    ``template_engine.py``, ``temperature.py``, ``temp_sensor.c``, and
    ``scratchpad.py`` are not: ``temp`` is not matched as a prefix, and
    ``scratch`` / ``filler`` match directory segments only.
    """
    stem = name.lower()
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    if stem in _SCRATCH_STEMS:
        return True
    return (
        len(stem) > len("tmp")
        and stem.startswith("tmp")
        and stem[len("tmp")] in _SCRATCH_SEPARATORS
    )


def _is_noise_path(path: str) -> bool:
    norm = path.replace("\\", "/").strip()
    parts = [part for part in norm.split("/") if part not in ("", ".")]
    if not parts:
        return True
    name = parts[-1].lower()
    if name.endswith(_NOISE_SUFFIXES) or _scratch_stem(name):
        return True
    for index, part in enumerate(parts):
        low = part.lower()
        if low in _NOISE_SEGMENTS:
            return True
        if index == 0 and low in _ROOT_NOISE_SEGMENTS:
            return True
    return False


def _dup_key(text: str) -> str:
    flat = _DUP_RE.sub(" ", normalize_newlines(text).casefold())
    return " ".join(flat.split())


def _collapse(items: list[_Item], priority: Sequence[str]) -> list[_Item]:
    kind_rank = {name: i for i, name in enumerate(priority)}
    ordered = sorted(
        items,
        key=lambda it: (
            kind_rank.get(it.kind, 99),
            _SUB_RANK.get(it.subtype, 9),
            -it.session_ord,
            it.turn if it.kind == "plan" else -it.turn,
            it.record_id,
        ),
    )
    seen: set[tuple[str, str]] = set()
    out: list[_Item] = []
    for item in ordered:
        key = (item.kind, _dup_key(item.text) or item.record_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _counts(items: Sequence[_Item], priority: Sequence[str]) -> dict[str, int]:
    counts = {name: 0 for name in priority}
    for item in items:
        if item.kind in counts:
            counts[item.kind] += 1
    return counts


def _diff(live: dict[str, int], shown: dict[str, int],
          priority: Sequence[str]) -> dict[str, int]:
    return {name: live.get(name, 0) - shown.get(name, 0) for name in priority}


def _notice(dropped: dict[str, int], budget: int, unit: str,
            priority: Sequence[str]) -> str:
    parts: list[str] = []
    for name in priority:
        n = int(dropped.get(name, 0))
        if n <= 0:
            continue
        singular, plural = _KIND_NOUNS[name]
        word = singular if n == 1 else plural
        parts.append(f"dropped {n} {word}")
    joined = ", ".join(parts)
    larger = budget * 2 if budget > 0 else DEFAULT_BRIEF_BUDGET
    return (
        f"Omitted by budget: {joined}. "
        f"Run `ctxpack brief --budget {larger} --unit {unit}` "
        f"or `ctxpack brief --format json` "
        f"or inspect the ledger to fetch."
    )


def _ack_block(token: str) -> str:
    return (
        f"CTX-Ack: {token}\n"
        f"Echo `CTX-Ack: {token}` in your next reply or commit message.\n"
    )


def _render(shown: Sequence[_Item], dropped: dict[str, int], *,
            budget: int, unit: str, priority: Sequence[str],
            include_notice: bool) -> str:
    by_kind: dict[str, list[_Item]] = {name: [] for name in priority}
    for item in shown:
        if item.kind in by_kind:
            by_kind[item.kind].append(item)
    lines: list[str] = []
    for kind in priority:
        group = by_kind[kind]
        if not group:
            continue
        lines.append(f"## {_SECTION_TITLES[kind]}")
        if kind == "conflicts":
            for subtype, title in _CONFLICT_SUBS:
                sub = [item for item in group if item.subtype == subtype]
                if not sub:
                    continue
                if title:
                    lines.append(f"## {title}")
                for item in sub:
                    lines.append(item.text)
        else:
            for item in group:
                body = item.text
                if body.startswith(("- ", "_")):
                    lines.append(body)
                else:
                    lines.append(f"- {body}")
        lines.append("")
    body = "\n".join(lines).rstrip("\n")
    if include_notice and any(int(v) > 0 for v in dropped.values()):
        notice = _notice(dropped, budget, unit, priority)
        body = f"{body}\n{notice}" if body else notice
    if body and not body.endswith("\n"):
        body += "\n"
    return normalize_newlines(body)


def _fit(items: list[_Item], live: dict[str, int], budget: int, unit: str,
         priority: Sequence[str], *, ack_token: str) -> tuple[str, dict[str, int], dict[str, int]]:
    """Keep whole facts in priority order. A fact that does not fit is dropped.

    Later facts are still considered, so one oversized fact does not
    hide a smaller fact behind it. The drop notice is part of the
    measured text. When even the notice does not fit, the result is
    empty — never a cut sentence.
    """
    ack = _ack_block(ack_token) if ack_token else ""

    def assemble(shown: list[_Item]) -> tuple[str, dict[str, int], dict[str, int]]:
        shown_counts = _counts(shown, priority)
        dropped = _diff(live, shown_counts, priority)
        body = _render(
            shown, dropped, budget=budget, unit=unit, priority=priority,
            include_notice=any(v > 0 for v in dropped.values()),
        )
        text = body + ack if ack else body
        if text and not text.endswith("\n"):
            text += "\n"
        return normalize_newlines(text), shown_counts, dropped

    zeros = {name: 0 for name in priority}
    if budget == 0:
        return "", zeros, dict(live)

    chosen: list[_Item] = []
    for item in items:
        text, _, _ = assemble(chosen + [item])
        if count_budget(text, unit) <= budget:
            chosen.append(item)
    text, shown_counts, dropped = assemble(chosen)
    if count_budget(text, unit) <= budget:
        return text, shown_counts, dropped
    return "", zeros, dict(live)
