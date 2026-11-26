"""Delivery acknowledgement for a budgeted briefing.

``ctxpack brief --ack`` appends ``CTX-Ack: <token>``. ``check_ack``
reports whether that line shows up in a later transcript turn or in a
git commit body, and appends a receipt under the ledger. The receipt
records status and where it matched. It does not store machine paths.
"""

from __future__ import annotations

import json
import os
import re
import subprocess


def check_ack(
    token: str,
    *,
    transcript: str = "",
    repo: str = "",
    ledger_dir: str = ".claude/ctx",
) -> dict[str, object]:
    """Return ``acked`` or ``not_acked`` and append a receipt line.

    A match is the exact marker ``CTX-Ack: <token>`` in the transcript
    text or in a commit message body. Exit status is the caller's
    concern; this function always returns the receipt dict.
    """
    cleaned = str(token or "").strip()
    if not cleaned or any(ch.isspace() for ch in cleaned):
        raise ValueError("ack token must be a single non-empty token")
    evidence: list[str] = []
    if transcript and _file_has_token(transcript, cleaned):
        evidence.append("transcript")
    sha = ""
    for candidate in _repos(repo, ledger_dir):
        sha = _commit_with_token(candidate, cleaned)
        if sha:
            evidence.append(f"commit:{sha}")
            break
    receipt: dict[str, object] = {
        "evidence": evidence,
        "status": "acked" if evidence else "not_acked",
        "token": cleaned,
    }
    _append_receipt(ledger_dir, receipt)
    return receipt


def _repos(repo: str, ledger_dir: str) -> list[str]:
    if repo:
        return [repo]
    found: list[str] = []
    parent = os.path.dirname(os.path.abspath(ledger_dir))
    cwd = os.getcwd()
    for candidate in (parent, cwd):
        if candidate and candidate not in found:
            found.append(candidate)
    return found


def _has_token(text: str, token: str) -> bool:
    pattern = re.compile(
        r"CTX-Ack:[ \t]*" + re.escape(token) + r"(?![0-9A-Za-z])")
    return pattern.search(text or "") is not None


def _file_has_token(path: str, token: str) -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return False
    return _has_token(text, token)


def _commit_with_token(repo: str, token: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "log", "-n", "200",
             "--format=%H%x1e%B%x1c"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    for chunk in proc.stdout.split("\x1c"):
        if "\x1e" not in chunk:
            continue
        sha, _, body = chunk.partition("\x1e")
        sha = sha.strip()
        if sha and _has_token(body, token):
            return sha
    return ""


def _append_receipt(ledger_dir: str, receipt: dict[str, object]) -> None:
    os.makedirs(ledger_dir, exist_ok=True)
    path = os.path.join(ledger_dir, "ack-receipts.jsonl")
    line = json.dumps(receipt, sort_keys=True, ensure_ascii=True) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
