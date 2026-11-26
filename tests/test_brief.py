"""Budgeted brief: one composer, one counter, delivery ack (#10, #25)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

import pytest

from ctxpack.agent.ack import check_ack
from ctxpack.agent.brief import brief, brief_result
from ctxpack.agent.checkpoint import run_checkpoint
from ctxpack.cli.main import main
from ctxpack.core.tokens import count_budget
from ctxpack.integrations.mcp_server import handle_brief


def _entry(role, content, sid="44444444-d", ts="2026-10-04T10:00:00Z"):
    if role == "assistant" and isinstance(content, str):
        content = [{"type": "text", "text": content}]
    return {
        "type": role,
        "sessionId": sid,
        "timestamp": ts,
        "isSidechain": False,
        "isMeta": False,
        "cwd": ".",
        "message": {"role": role, "content": content},
    }


def _write(path, rows):
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return str(path)


def _pack(tmp_path, rows, name="session.jsonl"):
    transcript = _write(tmp_path / name, rows)
    out = tmp_path / "ctx"
    run_checkpoint(transcript, str(out), as_of="2026-10-04")
    return str(out)


def _decision_rows(n=120, dead_every=10):
    rows = []
    for i in range(n):
        rows.append(_entry("user", f"step {i}", ts=f"2026-10-04T10:{i // 60:02d}:{i % 60:02d}Z"))
        text = (
            f"Decision: module m{i} uses strategy s{i} because "
            f"constraint c{i} applies to the parser path."
        )
        if dead_every and i % dead_every == 0:
            text += f"\nThat approach didn't work because the cache key {i} collided."
        rows.append(_entry(
            "assistant", [{"type": "text", "text": text}],
            ts=f"2026-10-04T11:{i // 60:02d}:{i % 60:02d}Z",
        ))
    return rows


def test_chars_and_tokens_are_offline_and_stable():
    text = "alpha\r\nbeta\rgamma"
    assert count_budget(text, "chars") == len("alpha\nbeta\ngamma")
    assert count_budget("", "chars") == 0
    assert count_budget("", "tokens") == 0
    assert count_budget("abcd", "tokens") == 1
    assert count_budget("abcde", "tokens") == max(1, (5 + 3) // 4)
    with pytest.raises(ValueError):
        count_budget("x", "bpe")


def test_cli_python_and_mcp_are_byte_identical(tmp_path, capsys):
    ledger = _pack(tmp_path, _decision_rows(4, dead_every=2))
    text = brief(ledger, budget=3000, unit="chars")
    mcp = handle_brief({
        "ledger_dir": ledger, "budget": 3000, "unit": "chars", "format": "md",
    })
    assert main(["brief", "--ledger", ledger, "--budget", "3000",
                 "--unit", "chars"]) == 0
    cli = capsys.readouterr().out
    assert text == mcp == cli
    assert text.endswith("\n")
    again = brief(ledger, budget=3000, unit="chars")
    assert again == text


def test_json_text_field_matches_markdown(tmp_path, capsys):
    ledger = _pack(tmp_path, _decision_rows(3, dead_every=0))
    text = brief(ledger, budget=4000, unit="chars")
    assert main(["brief", "--ledger", ledger, "--budget", "4000",
                 "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["text"] == text
    mcp = handle_brief({
        "ledger_dir": ledger, "budget": 4000, "format": "json",
    })
    assert json.loads(mcp)["text"] == text


def test_budget_sweep_never_exceeds_and_accounts(tmp_path):
    ledger = _pack(tmp_path, _decision_rows(120, dead_every=10))
    wide = brief_result(ledger, budget=100000, unit="chars")
    assert wide.live["decisions"] == 120
    assert wide.live["dead_ends"] == 12
    assert wide.dropped["decisions"] == 0
    assert wide.dropped["dead_ends"] == 0
    for budget in (2000, 4000, 8000, 12000, 14000):
        result = brief_result(ledger, budget=budget, unit="chars")
        assert count_budget(result.text, "chars") <= budget
        for kind in result.live:
            assert result.shown[kind] + result.dropped[kind] == result.live[kind]
        if result.dropped["dead_ends"]:
            noun = "dead end" if result.dropped["dead_ends"] == 1 else "dead ends"
            assert f"dropped {result.dropped['dead_ends']} {noun}" in result.text
        else:
            assert "didn't work" in result.text
        if result.dropped["decisions"]:
            noun = "decision" if result.dropped["decisions"] == 1 else "decisions"
            assert f"dropped {result.dropped['decisions']} {noun}" in result.text


def test_tight_budget_names_omitted_dead_ends(tmp_path):
    ledger = _pack(tmp_path, _decision_rows(120, dead_every=10))
    result = brief_result(ledger, budget=2000, unit="chars")
    assert count_budget(result.text, "chars") <= 2000
    if result.shown["dead_ends"]:
        assert "didn't work" in result.text
    assert result.dropped["dead_ends"] + result.shown["dead_ends"] == 12
    if result.dropped["dead_ends"]:
        assert f"{result.dropped['dead_ends']} dead end" in result.text


def test_changed_choice_is_not_cut_mid_sentence(tmp_path):
    old = (
        "Decision: the renderer keeps the full content and the trailing "
        "clause stays whole so a budget cut cannot end on content and."
    )
    from ctxpack.core import factid
    old_id = factid.fact_id("DECISION", old)
    new = "Decision: the renderer stores the title in mdsite.toml."
    rows = [
        _entry("user", "set the title", sid="11111111-a"),
        _entry("assistant", old, sid="11111111-a"),
        _entry("user", "change it", sid="22222222-b", ts="2026-10-05T10:00:00Z"),
        _entry("assistant",
               f"{new}\nSupersedes: {old_id} — mdsite.toml now owns the title.",
               sid="22222222-b", ts="2026-10-05T10:01:00Z"),
    ]
    ledger = _pack(tmp_path, rows)
    phrase = "content and the trailing clause stays whole"
    wide = brief(ledger, budget=8000)
    assert phrase in wide
    assert "Changed choices" in wide
    tight = brief_result(ledger, budget=240, unit="chars")
    assert count_budget(tight.text, "chars") <= 240
    if phrase in tight.text:
        assert "cannot end on content and" in tight.text
    else:
        assert "content and" not in tight.text
        assert tight.dropped["conflicts"] >= 1
        assert "dropped" in tight.text
    assert not tight.text.rstrip("\n").endswith("content and")


def test_near_duplicates_collapse(tmp_path):
    rows = [
        _entry("assistant", "Decision: Use Redis for the cache."),
        _entry("assistant", "Decision: use redis for the cache!",
               ts="2026-10-04T10:05:00Z"),
    ]
    ledger = _pack(tmp_path, rows)
    result = brief_result(ledger, budget=8000)
    assert result.live["decisions"] == 1
    assert result.text.lower().count("use redis for the cache") == 1


def test_newest_decision_comes_first(tmp_path):
    rows = [
        _entry("assistant", "Decision: keep the cache in memory."),
        _entry("assistant", "Decision: move the cache to redis.",
               ts="2026-10-04T12:00:00Z"),
    ]
    ledger = _pack(tmp_path, rows)
    text = brief(ledger, budget=8000)
    assert text.index("move the cache to redis") < text.index("keep the cache in memory")


def test_noise_files_do_not_crowd_the_brief(tmp_path):
    rows = [
        _entry("assistant", [
            {"type": "text", "text": "Decision: edit the retry helper."},
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "src/retry.py"}},
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "tmp/filler-notes.tmp"}},
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "scratch/draft.log"}},
        ]),
    ]
    ledger = _pack(tmp_path, rows)
    result = brief_result(ledger, budget=8000)
    assert "src/retry.py" in result.text
    assert "filler" not in result.text
    assert "scratch" not in result.text
    assert result.live["files"] == 1
    assert result.dropped["files"] == 0


def test_real_project_files_stay_scratch_paths_go(tmp_path):
    keep = [
        "src/template_engine.py",
        "app/temperature.py",
        "app/temp_sensor.c",
        "src/tmpl.py",
        "lib/scratchpad.py",
        "tools/build/gen.py",
        "docs/dist/README.md",
    ]
    drop = [
        "tmp/notes.py",
        "temp/cache.py",
        "scratch/draft.md",
        "filler/pad.txt",
        "src/tmp_widget.py",
        "build/out.js",
        "dist/bundle.js",
        ".cache/state.json",
    ]
    blocks = [{"type": "text", "text": "Decision: touch the real sources."}]
    blocks.extend(
        {"type": "tool_use", "name": "Edit", "input": {"file_path": path}}
        for path in keep + drop
    )
    ledger = _pack(tmp_path, [_entry("assistant", blocks)])
    result = brief_result(ledger, budget=8000)
    for path in keep:
        assert path in result.text
    for path in drop:
        assert path not in result.text
    assert result.live["files"] == len(keep)
    assert result.dropped["files"] == 0


def test_plan_steps_stay_in_file_order(tmp_path):
    ledger = _pack(tmp_path, [_entry("assistant", "Decision: follow the plan.")])
    (tmp_path / "ctx" / "plan.md").write_text(
        "- step 1 write the composer\n"
        "- step 2 wire the hook\n"
        "- step 3 check the ack\n",
        encoding="utf-8",
    )
    text = brief(ledger, budget=8000)
    assert text.index("step 1") < text.index("step 2") < text.index("step 3")


def test_drop_notice_asks_for_a_larger_budget(tmp_path):
    ledger = _pack(tmp_path, _decision_rows(40, dead_every=4))
    result = brief_result(ledger, budget=2000, unit="chars")
    assert "Omitted by budget:" in result.text
    assert "--budget 2000" not in result.text
    assert "--budget 4000" in result.text
    assert "--format json" in result.text


def test_plan_section_is_absent_without_a_plan_file(tmp_path):
    ledger = _pack(tmp_path, [_entry("assistant", "Decision: ship the brief.")])
    assert "Plan progress" not in brief(ledger, budget=8000)
    plan = tmp_path / "ctx" / "plan.md"
    plan.write_text("# Plan\n\n- [x] composer\n- [ ] ack receipts\n", encoding="utf-8")
    text = brief(ledger, budget=8000)
    assert "Plan progress" in text
    assert "ack receipts" in text
    assert "- # Plan" not in text


def test_priority_is_configurable(tmp_path):
    dead = "Rejected: the in-memory cache collided on the first key."
    decision = "Decision: " + ("keep a very long parser strategy " * 12)
    rows = [_entry("assistant", decision + "\n" + dead)]
    ledger = _pack(tmp_path, rows)
    (tmp_path / "ctxpack.toml").write_text(
        "[brief]\npriority = [\"dead_ends\", \"decisions\"]\n",
        encoding="utf-8",
    )
    custom = brief_result(ledger, budget=360, unit="chars")
    assert "collided on the first key" in custom.text
    assert "very long parser strategy" not in custom.text
    assert custom.dropped["decisions"] == 1


def test_dead_ends_keep_a_minimum_share_at_the_floor(tmp_path):
    """Decisions must not spend the whole budget once it reaches 1500 chars."""
    rows = []
    for i in range(12):
        rows.append(_entry(
            "assistant",
            f"Decision: keep policy {i:02d} because " + ("x" * 200),
            ts=f"2026-10-04T10:{i // 60:02d}:{i % 60:02d}Z",
        ))
    rows.append(_entry(
        "assistant",
        "Rejected: the first layout collided because " + ("y" * 500),
        ts="2026-10-04T12:00:00Z",
    ))
    rows.append(_entry(
        "assistant",
        "Rejected: the second layout collided because " + ("z" * 500),
        ts="2026-10-04T12:01:00Z",
    ))
    ledger = _pack(tmp_path, rows)
    below = brief_result(ledger, budget=1499, unit="chars")
    above = brief_result(ledger, budget=1500, unit="chars")
    wide = brief_result(ledger, budget=12000, unit="chars")
    for result in (below, above, wide):
        assert count_budget(result.text, result.unit) <= result.budget
        for kind in result.live:
            assert result.shown[kind] + result.dropped[kind] == result.live[kind]
    assert below.live["dead_ends"] == 2
    assert below.shown["dead_ends"] == 0
    assert above.shown["dead_ends"] >= 2
    assert wide.shown["dead_ends"] >= 2
    token_floor = count_budget("x" * 1500, "tokens")
    under_tokens = brief_result(ledger, budget=token_floor - 1, unit="tokens")
    at_tokens = brief_result(ledger, budget=token_floor, unit="tokens")
    assert count_budget(at_tokens.text, "tokens") <= token_floor
    assert at_tokens.shown["dead_ends"] >= min(2, at_tokens.live["dead_ends"])
    assert under_tokens.shown["dead_ends"] + under_tokens.dropped["dead_ends"] == (
        under_tokens.live["dead_ends"])


def test_default_budget_is_12000_chars(tmp_path):
    ledger = _pack(tmp_path, _decision_rows(8, dead_every=4))
    result = brief_result(ledger)
    assert result.budget == 12000
    assert result.unit == "chars"
    assert count_budget(result.text, "chars") <= 12000


def test_token_unit_stays_within_budget(tmp_path):
    ledger = _pack(tmp_path, _decision_rows(30, dead_every=5))
    result = brief_result(ledger, budget=80, unit="tokens")
    assert count_budget(result.text, "tokens") <= 80
    for kind in result.live:
        assert result.shown[kind] + result.dropped[kind] == result.live[kind]


def test_ultra_tiny_budget_does_not_cut_a_fact(tmp_path):
    ledger = _pack(tmp_path, [_entry(
        "assistant", "Decision: keep the full sentence intact.")])
    result = brief_result(ledger, budget=1, unit="chars")
    assert count_budget(result.text, "chars") <= 1
    assert "Decision:" not in result.text
    assert brief_result(ledger, budget=0).text == ""


def test_same_ledger_with_and_without_tiktoken(tmp_path, monkeypatch):
    rows = _decision_rows(6, dead_every=3)
    transcript = _write(tmp_path / "session.jsonl", rows)
    first = tmp_path / "with"
    run_checkpoint(str(transcript), str(first), as_of="2026-10-04")
    gist_with = (first / "latest-gist.md").read_bytes()
    brief_with = brief(str(first), budget=4000).encode("utf-8")

    import builtins
    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tiktoken" or name.startswith("tiktoken."):
            raise ImportError("simulated missing tiktoken")
        return real_import(name, globals, locals, fromlist, level)

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("briefing opened a socket")

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(socket, "socket", refuse_network)
    monkeypatch.setattr(socket, "create_connection", refuse_network)
    import ctxpack.benchmarks.metrics.cost as cost
    monkeypatch.setattr(
        cost, "count_bpe_tokens",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("budget path called tiktoken")))

    second = tmp_path / "without"
    run_checkpoint(str(transcript), str(second), as_of="2026-10-04")
    gist_without = (second / "latest-gist.md").read_bytes()
    brief_without = brief(str(second), budget=4000).encode("utf-8")
    assert gist_with == gist_without
    assert brief_with == brief_without


def test_hashseed_does_not_change_the_brief(tmp_path):
    ledger = _pack(tmp_path, _decision_rows(5, dead_every=2))
    code = (
        "import os\n"
        "from ctxpack.agent.brief import brief\n"
        f"print(brief({ledger!r}, budget=2500, unit='chars'), end='')\n"
    )
    outs = []
    for seed in ("0", "17"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, env=env, check=False,
        )
        assert proc.returncode == 0, proc.stderr
        outs.append(proc.stdout)
    assert outs[0] == outs[1]
    assert outs[0] == brief(ledger, budget=2500, unit="chars")


def test_ack_round_trip_and_not_banked(tmp_path, capsys):
    ledger = _pack(tmp_path, [_entry(
        "assistant", "Decision: pin the ack token outside the ledger.")])
    quiet_a = brief(ledger, budget=4000)
    quiet_b = brief(ledger, budget=4000)
    assert quiet_a == quiet_b
    assert "CTX-Ack:" not in quiet_a

    token = "abcdef0123456789"
    acked = brief(ledger, budget=4000, ack=True, ack_token=token)
    assert f"CTX-Ack: {token}" in acked
    assert f"Echo `CTX-Ack: {token}`" in acked
    assert count_budget(acked, "chars") <= 4000

    transcript = tmp_path / "later.jsonl"
    _write(transcript, [
        _entry("assistant", "Decision: pin the ack token outside the ledger."),
        _entry("assistant",
               f"CTX-Ack: {token}\n"
               f"Echo `CTX-Ack: {token}` in your next reply or commit message.\n"
               "Decision: record the real follow-up in the ledger.",
               ts="2026-10-04T12:00:00Z"),
    ])
    packed = tmp_path / "echo"
    run_checkpoint(str(transcript), str(packed), as_of="2026-10-04")
    from ctxpack.agent.ledger import ledger_stem
    blob = (packed / f"session-{ledger_stem('44444444-d')}.ctx").read_text(
        encoding="utf-8")
    assert token not in blob
    assert "CTX-Ack:" not in blob
    assert "record the real follow-up" in blob

    assert main(["ack", "check", "--token", token,
                 "--transcript", str(transcript),
                 "--ledger", str(tmp_path / "receipts"),
                 "--repo", str(tmp_path / "not-a-repo")]) == 0
    status = capsys.readouterr().out.strip()
    assert status == "acked"
    receipt = (tmp_path / "receipts" / "ack-receipts.jsonl").read_text(encoding="utf-8")
    assert '"status": "acked"' in receipt
    assert "transcript" in receipt

    assert main(["ack", "check", "--token", "ffffffffffffffff",
                 "--transcript", str(transcript),
                 "--ledger", str(tmp_path / "receipts"),
                 "--repo", str(tmp_path / "not-a-repo"),
                 "--format", "json"]) == 1
    missing = json.loads(capsys.readouterr().out)
    assert missing["status"] == "not_acked"


def test_ack_ignores_user_and_tool_results(tmp_path):
    token = "abc123deadbeef"
    repo = str(tmp_path / "not-a-repo")
    user_only = tmp_path / "user.jsonl"
    _write(user_only, [_entry("user", f"please echo CTX-Ack: {token}")])
    tool_only = tmp_path / "tool.jsonl"
    _write(tool_only, [_entry("user", [{
        "type": "tool_result",
        "content": f"stdout of ctxpack brief --ack\nCTX-Ack: {token}\n",
    }])])
    assistant_tool = tmp_path / "assistant-tool.jsonl"
    _write(assistant_tool, [_entry("assistant", [{
        "type": "tool_result",
        "content": f"CTX-Ack: {token}",
    }])])
    assistant = tmp_path / "assistant.jsonl"
    _write(assistant, [_entry("assistant", f"CTX-Ack: {token}")])
    assert check_ack(
        token, transcript=str(user_only), repo=repo,
        ledger_dir=str(tmp_path / "r1"))["status"] == "not_acked"
    assert check_ack(
        token, transcript=str(tool_only), repo=repo,
        ledger_dir=str(tmp_path / "r2"))["status"] == "not_acked"
    assert check_ack(
        token, transcript=str(assistant_tool), repo=repo,
        ledger_dir=str(tmp_path / "r3"))["status"] == "not_acked"
    acked = check_ack(
        token, transcript=str(assistant), repo=repo,
        ledger_dir=str(tmp_path / "r4"))
    assert acked["status"] == "acked"
    assert acked["evidence"] == ["transcript"]


def test_ack_found_in_commit_body(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"],
                   cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"],
                   cwd=repo, check=True, capture_output=True)
    (repo / "note.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True, capture_output=True)
    token = "0123456789abcdef"
    subprocess.run(
        ["git", "commit", "-m", f"record delivery\n\nCTX-Ack: {token}\n"],
        cwd=repo, check=True, capture_output=True,
    )
    ledger = tmp_path / "ctx"
    assert main(["ack", "check", "--token", token, "--repo", str(repo),
                 "--ledger", str(ledger)]) == 0
    assert capsys.readouterr().out.strip() == "acked"
    line = (ledger / "ack-receipts.jsonl").read_text(encoding="utf-8")
    assert "commit:" in line
    assert str(repo) not in line


def test_explicit_tokenizer_fails_without_tiktoken(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tiktoken" or name.startswith("tiktoken."):
            raise ImportError("simulated missing tiktoken")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    import importlib

    import ctxpack.benchmarks.metrics.cost as cost
    importlib.reload(cost)
    with pytest.raises(RuntimeError, match="refusing to switch"):
        cost.count_bpe_tokens("hello", model="claude")


def test_startup_hook_uses_the_composer(tmp_path, capsys):
    ledger = _pack(tmp_path, [_entry(
        "assistant", "Decision: the hook and the brief share one composer.")])
    text = brief(ledger, budget=12000, unit="chars")
    payload = json.dumps({"session_id": "new", "cwd": str(tmp_path)})
    proc = subprocess.run(
        [sys.executable, "-m", "ctxpack.cli.main", "hook", "session-start",
         "--out", ledger],
        input=payload, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    emitted = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "the hook and the brief share one composer" in emitted
    assert emitted.strip() == text.strip()


def test_session_start_redaction_cannot_exceed_budget(tmp_path):
    """`[REDACTED:type]` is measured before the hook budget is final.

    The unredacted brief fits the budget exactly. Replacing a short token
    with ``[REDACTED:gitlab-token]`` would push that text over the budget
    if the hook measured first and redacted after. The emitted context
    stays inside the budget and does not contain the raw token.
    """
    secret = "glpat-abcdefghij"
    ledger = _pack(tmp_path, [
        _entry("assistant",
               "Decision: keep the long filler policy because " + ("x" * 240)),
        _entry("assistant",
               "Decision: pin the retry helper and keep the plain token slot.",
               ts="2026-10-04T12:00:00Z"),
    ])
    for path in (tmp_path / "ctx").glob("session-*.ctx"):
        body = path.read_text(encoding="utf-8")
        assert "plain" in body
        path.write_text(body.replace("plain", secret, 1), encoding="utf-8")
    raw = brief(ledger, budget=12000, unit="chars")
    assert secret in raw
    budget = count_budget(raw, "chars")
    (tmp_path / "ctx" / "ctxpack.toml").write_text(
        f"[brief]\nbudget = {budget}\n", encoding="utf-8")
    payload = json.dumps({"session_id": "new-session", "cwd": str(tmp_path)})
    proc = subprocess.run(
        [sys.executable, "-m", "ctxpack.cli.main", "hook", "session-start",
         "--out", ledger],
        input=payload, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert secret not in proc.stdout
    assert "glpat-" not in proc.stdout
    emitted = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert count_budget(emitted, "chars") <= budget
    assert "[REDACTED:gitlab-token]" in emitted
