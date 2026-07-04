"""CompactBench driver — replay planted sessions through real Claude Code.

The loop the pre-registration calls for: inject a planted transcript into
Claude Code's project store, resume it headless with the autocompact
threshold forced low (``CLAUDE_AUTOCOMPACT_PCT_OVERRIDE``, a percentage
of the context window in (0, 100]), let real compaction fire K times,
and fork-resume probe sessions after each cycle.

Everything observable is read back deterministically from the transcript
file itself: compaction cycles are ``system`` entries with
``subtype == "compact_boundary"`` carrying ``compactMetadata``
(trigger/preTokens/postTokens), so cycle counting and token accounting
need no arm-specific instrumentation.

Replay invariants (verified against Claude Code 2.1.201):
- transcripts live at ``~/.claude/projects/<munged-cwd>/<session-uuid>.jsonl``
  where the munge is every non-alphanumeric character replaced by ``-``;
- session IDs must be valid UUIDs;
- entries need a valid ``uuid``/``parentUuid`` chain plus ``cwd``;
- an assistant ``tool_use`` must be answered by a ``tool_result``.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Any

from .planted_session_gen import _filler_pair

# Cosmetic transcript field; pinned so enrichment stays byte-deterministic
# across Claude Code upgrades.
PINNED_VERSION = "2.1.0"

# Window pinned via CLAUDE_CODE_AUTO_COMPACT_WINDOW during forced cycles
# (env min is 100K). The autocompact threshold is
# pct% of (window - max output reservation, ~32K).
FORCED_WINDOW = 100_000
_OUTPUT_RESERVATION = 32_000


def forced_threshold_tokens(pct: float) -> int:
    return int((FORCED_WINDOW - _OUTPUT_RESERVATION) * pct / 100)
_UUID_NS = uuid.uuid5(uuid.NAMESPACE_URL,
                      "https://github.com/cryogenic22/CTX.ai/compactbench")

ARMS = ("native", "claudemd", "grep", "llm-memory", "ctx", "oracle")


class DriverError(RuntimeError):
    pass


# ---------------------------------------------------------------- paths

def munge_project_dir(path: str) -> str:
    """Claude Code's project-store key: non-alphanumerics become '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def claude_home() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR",
                          os.path.join(os.path.expanduser("~"), ".claude"))


def transcript_path(workspace: str, sid: str) -> str:
    return os.path.join(claude_home(), "projects",
                        munge_project_dir(workspace), f"{sid}.jsonl")


def _claude_exe() -> str:
    """Resolve the claude binary, preferring the real .exe over the npm
    .cmd shim (batch shims break subprocess argument quoting)."""
    found = shutil.which("claude")
    if not found:
        raise DriverError("claude CLI not on PATH")
    if found.lower().endswith((".cmd", ".bat")):
        exe = os.path.join(os.path.dirname(found), "node_modules",
                           "@anthropic-ai", "claude-code", "bin", "claude.exe")
        if os.path.exists(exe):
            return exe
    return found


# ----------------------------------------------------------- enrichment

def enrich(entries: list[dict], sid: str, cwd: str,
           parent_uuid: "str | None" = None, salt: str = "plant") -> list[dict]:
    """Add the replay-required fields: deterministic uuid/parentUuid chain
    (uuid5 over sid+salt+index), cwd, pinned version. Same inputs, same
    bytes."""
    out: list[dict] = []
    parent = parent_uuid
    for i, entry in enumerate(entries):
        eid = str(uuid.uuid5(_UUID_NS, f"{sid}:{salt}:{i}"))
        enriched = dict(entry)
        enriched.update({
            "uuid": eid, "parentUuid": parent, "cwd": cwd,
            "sessionId": sid, "version": PINNED_VERSION,
            "userType": "external", "entrypoint": "cli",
        })
        out.append(enriched)
        parent = eid
    return out


def append_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def iter_entries(path: str):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def last_uuid(path: str) -> "str | None":
    last = None
    for e in iter_entries(path):
        if e.get("uuid"):
            last = e["uuid"]
    return last


# ----------------------------------------------------- transcript state

def compact_boundaries(path: str) -> list[dict]:
    """All compaction boundaries so far, oldest first, with metadata."""
    out = []
    if not os.path.exists(path):
        return out
    for e in iter_entries(path):
        if e.get("subtype") == "compact_boundary":
            out.append({"uuid": e.get("uuid"),
                        **(e.get("compactMetadata") or {})})
    return out


def tail_token_estimate(path: str) -> int:
    """Rough (bytes/4) token estimate of the live context: everything
    after the most recent compact summary, or the whole file if none."""
    if not os.path.exists(path):
        return 0
    tail_bytes = 0
    for e in iter_entries(path):
        line_len = len(json.dumps(e))
        if e.get("isCompactSummary") or e.get("subtype") == "compact_boundary":
            tail_bytes = 0
        tail_bytes += line_len
    return tail_bytes // 4


def inflation_entries(seed: int, cycle: int, sid: str, cwd: str,
                      parent: "str | None", approx_tokens: int) -> list[dict]:
    """Deterministic filler to push the live context back over the forced
    threshold between cycles. Distinct rng stream per (seed, cycle) so
    re-runs are byte-identical and never collide with the planted filler."""
    rng = random.Random(f"cb-inflate-{seed}-{cycle}")
    raw: list[dict] = []
    tokens = 0
    turn = 100_000 + cycle * 1_000
    while tokens < approx_tokens:
        pair = _filler_pair(rng, sid, turn, lines=30)
        raw.extend(pair)
        turn += len(pair)
        tokens += sum(len(json.dumps(p)) for p in pair) // 4
    return enrich(raw, sid, cwd, parent_uuid=parent, salt=f"inflate{cycle}")


def attempted_tool_commands(path: str) -> list[str]:
    """Commands a probe session *attempted* (tool_use entries in its fork
    transcript), in order. Permission-denied attempts are still recorded,
    which is exactly what adherence grading inspects: trying the
    forbidden action is the violation, whether or not it executed."""
    cmds: list[str] = []
    if not os.path.exists(path):
        return cmds
    for e in iter_entries(path):
        msg = e.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                inp = block.get("input") or {}
                cmds.append(str(inp.get("command") or json.dumps(inp)))
    return cmds


# -------------------------------------------------------- claude runner

@dataclass
class ClaudeResult:
    ok: bool
    result: str
    session_id: "str | None"
    usage: dict
    cost_usd: "float | None"
    duration_ms: "int | None"
    stderr: str
    raw: dict = field(default_factory=dict)


def run_claude(workspace: str, prompt: str, *,
               resume: "str | None" = None, fork: bool = False,
               model: "str | None" = None, pct: "float | None" = None,
               allowed_tools: "str | None" = None,
               disallowed_tools: "str | None" = None,
               max_turns: "int | None" = None,
               extra_env: "dict | None" = None,
               timeout: int = 900) -> ClaudeResult:
    """One headless Claude Code invocation in `workspace`.

    pct set  -> autocompact forced at that percent of the window.
    pct None -> autocompact hard-disabled (probes must not add a cycle).
    """
    cmd = [_claude_exe(), "-p", prompt, "--output-format", "json",
           "--setting-sources", "project"]
    if resume:
        cmd += ["--resume", resume]
    if fork:
        cmd += ["--fork-session"]
    if model:
        cmd += ["--model", model]
    if allowed_tools:
        cmd += ["--allowedTools", allowed_tools]
    if disallowed_tools:
        cmd += ["--disallowedTools", disallowed_tools]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]

    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE_") or k == "DISABLE_AUTO_COMPACT"
                   or k == "CLAUDECODE")}
    if pct is not None:
        # Two vars, both required (verified against 2.1.201): proactive
        # autocompact is SKIPPED when the context-window source is "auto"
        # (it defers to the reactive path); pinning the window via env
        # flips the source to "env" so the threshold check runs at all,
        # and the pct override then scales the threshold.
        env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = str(pct)
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(FORCED_WINDOW)
    else:
        env["DISABLE_AUTO_COMPACT"] = "1"
    if extra_env:
        env.update(extra_env)

    proc = subprocess.run(cmd, cwd=workspace, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    raw: dict = {}
    if proc.stdout:
        try:
            raw = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raw = {"unparsed_stdout": proc.stdout[-2000:]}
    return ClaudeResult(
        ok=(proc.returncode == 0 and not raw.get("is_error", False)),
        result=str(raw.get("result", "")),
        session_id=raw.get("session_id"),
        usage=raw.get("usage") or {},
        cost_usd=raw.get("total_cost_usd"),
        duration_ms=raw.get("duration_ms"),
        stderr=(proc.stderr or "")[-2000:],
        raw=raw)


# ------------------------------------------------------ workspace setup

# Deliberately NOT imperative-negation-shaped ("Do not use tools...")
# — the ctx arm's extractor would bank that phrasing as a session
# constraint, contaminating the gist. Tool suppression is enforced via
# --disallowedTools instead.
_NUDGE = "Acknowledge with exactly: ok."
_NO_TOOLS = ("Bash,Read,Grep,Glob,Edit,Write,NotebookEdit,WebFetch,"
             "WebSearch,Task,Agent,TodoWrite")


def setup_workspace(root: str, arm: str, seed: int, entries: list[dict],
                    manifest: dict, *, llm_memory: "str | None" = None) -> dict:
    """Create the per-(arm, seed) workspace and inject the planted
    transcript into Claude Code's project store. Returns run context."""
    if arm not in ARMS:
        raise DriverError(f"unknown arm {arm!r}")
    workspace = os.path.abspath(os.path.join(root, f"s{seed:04d}-{arm}"))
    os.makedirs(os.path.join(workspace, ".claude"), exist_ok=True)

    settings_path = os.path.join(workspace, ".claude", "settings.json")
    if arm == "ctx":
        from ctxpack.cli.main import _install_hooks_into
        if _install_hooks_into(workspace) is None:
            raise DriverError("ctx hook install failed")
    elif not os.path.exists(settings_path):
        with open(settings_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({}, f)

    if arm == "claudemd":
        # Operationalization of "hand-curated CLAUDE.md notes": the
        # planted ground rules verbatim — what a diligent team pins.
        rules = "\n".join(f"- {c['text']}" for c in manifest["constraints"])
        with open(os.path.join(workspace, "CLAUDE.md"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write("# Project notes\n\n## Ground rules\n\n" + rules + "\n")

    if arm == "grep":
        raw_log = os.path.join(workspace, "session-log.jsonl")
        with open(raw_log, "w", encoding="utf-8", newline="\n") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    if arm == "llm-memory":
        with open(os.path.join(workspace, "MEMORY.md"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(llm_memory or "(memory file unavailable)\n")

    sid = manifest["session"]
    tpath = transcript_path(workspace, sid)
    if os.path.exists(tpath):
        os.remove(tpath)  # workspace dirs are run-scoped scratch, not results
    append_jsonl(tpath, enrich(entries, sid, workspace))
    return {"arm": arm, "seed": seed, "workspace": workspace,
            "sid": sid, "transcript": tpath}


# ------------------------------------------------------ compaction loop

def force_cycles(ctx: dict, k_target: int, *, pct: float, model: str,
                 log=print) -> list[dict]:
    """Drive the session to k_target compaction cycles. Returns per-cycle
    records (boundary metadata + nudge usage). Oracle arms must not call
    this."""
    tpath, sid, seed = ctx["transcript"], ctx["sid"], ctx["seed"]
    workspace = ctx["workspace"]
    threshold = forced_threshold_tokens(pct)
    cycles: list[dict] = []
    done = len(compact_boundaries(tpath))
    stall = 0
    while done < k_target:
        est = tail_token_estimate(tpath)
        target = int(threshold * 1.4)
        if est < target:
            filler = inflation_entries(seed, done + stall * 100, sid,
                                       workspace, last_uuid(tpath),
                                       target - est)
            append_jsonl(tpath, filler)
        res = run_claude(workspace, _NUDGE, resume=sid, model=model,
                         pct=pct, disallowed_tools=_NO_TOOLS, max_turns=2)
        now = compact_boundaries(tpath)
        if len(now) <= done:
            stall += 1
            log(f"    cycle {done + 1}: no boundary after nudge "
                f"(stall {stall}) est={est} thr={threshold} "
                f"err={res.stderr[:200]!r}")
            if stall >= 3:
                raise DriverError(
                    f"autocompact never fired for {ctx['arm']}/s{seed} "
                    f"(est {est} tokens, threshold {threshold}): "
                    f"{res.stderr[:500]}")
            continue
        stall = 0
        done = len(now)
        cycles.append({"k": done, **now[-1],
                       "nudge_usage": res.usage, "nudge_cost": res.cost_usd})
        log(f"    cycle {done}: pre={now[-1].get('preTokens')} "
            f"post={now[-1].get('postTokens')} "
            f"trigger={now[-1].get('trigger')}")
    return cycles
