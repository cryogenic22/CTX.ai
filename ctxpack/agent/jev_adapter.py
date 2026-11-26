"""Optional advisory adapter for a pinned Jev model.

``ctxpack[jev]`` adds no third-party dependency. Transport is stdlib
``urllib.request``. The adapter never writes the ledger and never
decides ``ctxpack verify`` exit codes.

Modes:

- ``off`` (default): no network, pass-through filter, empty assessment.
- ``replay``: answers come only from a JSONL cassette. A query that is
  not in the cassette fails closed.
- ``shadow``: one live call when an API key is present. Failures are
  returned on the advisory result; they are not raised.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
QUESTIONS = (
    "constraint_breach",
    "silent_spec_change",
    "summary_overclaim",
    "stuck_loop",
)
_ANSWERS = frozenset({"yes", "no", "uncertain"})
_EXACT_PIN = re.compile(r"^jev-\d+\.\d+\.\d+$")

Transport = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class ReplayMiss(LookupError):
    """A replay cassette has no row for this query."""


@dataclass(frozen=True)
class AdvisoryAnswer:
    """One yes/no/uncertain advisory answer."""

    question: str
    answer: str


@dataclass(frozen=True)
class AdvisoryResult:
    """Advisory output. ``network`` is true only after a live attempt."""

    mode: str
    model: str
    network: bool
    selected_fact_ids: tuple[str, ...]
    answers: tuple[AdvisoryAnswer, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "answers": [{"answer": row.answer, "question": row.question}
                        for row in self.answers],
            "error": self.error,
            "mode": self.mode,
            "model": self.model,
            "network": self.network,
            "selected_fact_ids": list(self.selected_fact_ids),
        }


def _require_https(url: str) -> str:
    """Refuse any URL that would send the API key off TLS."""
    if not isinstance(url, str):
        raise ValueError("Jev URL must use https://")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Jev URL must use https://")
    return url


def _check_model(model: str, allow_unpinned: bool) -> str:
    if allow_unpinned:
        if not isinstance(model, str) or not model or any(c.isspace() for c in model):
            raise ValueError("model override must be a non-empty token")
        return model
    if not isinstance(model, str) or _EXACT_PIN.fullmatch(model) is None:
        raise ValueError(
            "model must be an exact pin such as jev-1.13.0; "
            "floating aliases are rejected unless allow_unpinned=True")
    return model


class JevClient:
    """Cassette or HTTP transport. The API key never enters a result."""

    def __init__(
        self,
        *,
        mode: str = "off",
        model: str = DEFAULT_MODEL,
        url: str = DEFAULT_URL,
        replay_path: str | Path | None = None,
        api_key: str | None = None,
        allow_unpinned: bool = False,
        transport: Transport | None = None,
    ) -> None:
        if mode not in {"off", "replay", "shadow"}:
            raise ValueError("mode must be off, replay, or shadow")
        self.mode = mode
        self.model = _check_model(model, allow_unpinned)
        self.url = _require_https(url)
        self.replay_path = Path(replay_path) if replay_path is not None else None
        self._api_key = api_key
        self.transport = transport
        if mode == "replay" and self.replay_path is None:
            raise ValueError("replay mode requires replay_path")

    def api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        return (os.environ.get("TYPESAFE_API_KEY")
                or os.environ.get("JEV_API_KEY")
                or "")

    def exchange(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a response object. ``off`` does not touch the network."""
        if self.mode == "off":
            return {}
        if self.mode == "replay":
            return self._replay(payload)
        return self._shadow(payload)

    def _replay(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        assert self.replay_path is not None
        try:
            text = self.replay_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReplayMiss("replay cassette is unreadable") from exc
        op = str(payload.get("op", ""))
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReplayMiss("replay cassette row is not JSON") from exc
            if not isinstance(row, dict) or row.get("op") != op:
                continue
            if op == "filter" and row.get("query") == payload.get("query"):
                return row
            if op == "assess" and _assess_key(row) == _assess_key(payload):
                return row
        raise ReplayMiss(f"replay cassette has no {op} row for this query")

    def _shadow(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        key = self.api_key()
        if not key:
            return {"error": "api key absent", "network": False}
        try:
            if self.transport is not None:
                data = self.transport(self.url, payload)
            else:
                data = _post_json(self.url, payload, key)
        except Exception as exc:  # advisory must not raise into the ledger
            return {"error": type(exc).__name__, "network": True}
        if not isinstance(data, Mapping):
            return {"error": "response was not an object", "network": True}
        cleaned = {k: v for k, v in data.items() if k not in {"api_key", "network"}}
        cleaned["network"] = True
        return cleaned


class JevAdapter:
    """Select facts and answer four checkpoint questions. Advisory only."""

    def __init__(self, client: JevClient | None = None, **kwargs: Any) -> None:
        self.client = client if client is not None else JevClient(**kwargs)

    @property
    def mode(self) -> str:
        return self.client.mode

    @property
    def model(self) -> str:
        return self.client.model

    def filter_live_facts(
        self,
        facts: Sequence[Mapping[str, Any]],
        query: str,
    ) -> AdvisoryResult:
        """Return relevant live-fact ids. Does not mutate ``facts``."""
        ids = tuple(_fact_id(fact) for fact in facts)
        if self.mode == "off":
            return AdvisoryResult(
                mode="off", model=self.model, network=False,
                selected_fact_ids=ids, answers=())
        payload = {
            "model": self.model,
            "op": "filter",
            "query": query,
            "fact_ids": list(ids),
        }
        try:
            row = self.client.exchange(payload)
        except ReplayMiss:
            if self.mode == "replay":
                raise
            return self._soft_error("ReplayMiss")
        except Exception as exc:
            return self._soft_error(type(exc).__name__)
        if row.get("error"):
            return AdvisoryResult(
                mode=self.mode, model=self.model,
                network=bool(row.get("network")),
                selected_fact_ids=(), answers=(),
                error=str(row.get("error")))
        try:
            selected = _selected(row, ids)
        except ReplayMiss:
            if self.mode == "replay":
                raise
            return self._soft_error("ReplayMiss", network=bool(row.get("network")))
        return AdvisoryResult(
            mode=self.mode, model=self.model,
            network=bool(row.get("network")),
            selected_fact_ids=selected, answers=())

    def assess_checkpoint(
        self,
        diff_summary: str,
        live_constraints: Sequence[str],
        pr_body: str = "",
    ) -> AdvisoryResult:
        """Ask the four scoped questions. ``off`` returns no answers."""
        constraints = tuple(sorted(str(item) for item in live_constraints))
        if self.mode == "off":
            return AdvisoryResult(
                mode="off", model=self.model, network=False,
                selected_fact_ids=(), answers=())
        payload = {
            "constraints": list(constraints),
            "diff_summary": diff_summary,
            "model": self.model,
            "op": "assess",
            "pr_body": pr_body,
            "questions": list(QUESTIONS),
        }
        try:
            row = self.client.exchange(payload)
        except ReplayMiss:
            if self.mode == "replay":
                raise
            return self._soft_error("ReplayMiss")
        except Exception as exc:
            return self._soft_error(type(exc).__name__)
        if row.get("error"):
            return AdvisoryResult(
                mode=self.mode, model=self.model,
                network=bool(row.get("network")),
                selected_fact_ids=(), answers=(),
                error=str(row.get("error")))
        try:
            answers = _answers(row)
        except ReplayMiss:
            if self.mode == "replay":
                raise
            return self._soft_error("ReplayMiss", network=bool(row.get("network")))
        return AdvisoryResult(
            mode=self.mode, model=self.model,
            network=bool(row.get("network")),
            selected_fact_ids=(), answers=answers)

    def _soft_error(self, error: str, network: bool = False) -> AdvisoryResult:
        return AdvisoryResult(
            mode=self.mode, model=self.model, network=network,
            selected_fact_ids=(), answers=(), error=error)


def _fact_id(fact: Mapping[str, Any]) -> str:
    for key in ("fact_id", "id"):
        value = fact.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _selected(row: Mapping[str, Any], known: Sequence[str]) -> tuple[str, ...]:
    raw = row.get("selected_fact_ids", ())
    if not isinstance(raw, list):
        raise ReplayMiss("replay filter row is missing selected_fact_ids")
    known_set = set(known)
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item in known_set and item not in out:
            out.append(item)
    return tuple(out)


def _answers(row: Mapping[str, Any]) -> tuple[AdvisoryAnswer, ...]:
    raw = row.get("answers")
    if not isinstance(raw, Mapping):
        raise ReplayMiss("replay assess row is missing answers")
    out: list[AdvisoryAnswer] = []
    for question in QUESTIONS:
        if question not in raw:
            raise ReplayMiss(f"replay assess row is missing {question}")
        answer = raw[question]
        if answer not in _ANSWERS:
            raise ReplayMiss(f"replay answer for {question} is not yes/no/uncertain")
        out.append(AdvisoryAnswer(question, str(answer)))
    return tuple(out)


def _assess_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    constraints = row.get("constraints", [])
    if isinstance(constraints, list):
        constraints = tuple(sorted(str(item) for item in constraints))
    else:
        constraints = ()
    return (
        str(row.get("diff_summary", "")),
        str(row.get("pr_body", "")),
        constraints,
    )


def _post_json(url: str, payload: Mapping[str, Any], api_key: str) -> Mapping[str, Any]:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": "ctxpack-jev/1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("response was not an object")
    return parsed
